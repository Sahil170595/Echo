"""Discord adapter for JARVIS with streaming responses.

Streams JARVIS responses via WebSocket and edits the Discord message
progressively as tokens arrive. Shows typing indicator during processing.

## Setup

1. Create a Discord Application at https://discord.com/developers/applications
2. Create a Bot under the application
3. Enable Message Content Intent (Bot > Privileged Gateway Intents)
4. Generate invite URL with scopes: bot, applications.commands
   Bot permissions: Send Messages, Read Message History, View Channels
5. Invite bot to your server
6. Set environment variables (see below)

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| DISCORD_BOT_TOKEN | Yes | Discord bot token |
| JARVIS_URL | Yes | JARVIS gateway URL |
| JARVIS_DEVICE_KEY | Yes | Device key for JARVIS auth |
| ECHO_DISCORD_PREFIX | No | Command prefix (default: "!jarvis ") |
| ECHO_DISCORD_RESPOND_TO_MENTIONS | No | Set "1" to respond to @mentions (default: "1") |
"""

from __future__ import annotations

import logging
import os
import uuid

import discord

from echo.shared.client import JarvisClient
from echo.shared.format import to_discord
from echo.shared.sessions import get_session, set_session
from echo.shared.stream import JarvisStreamClient, StreamAccumulator, TERMINAL_EVENTS

logger = logging.getLogger(__name__)

PLATFORM = "discord"
DISCORD_MAX_LENGTH = 2000


class EchoDiscordBot(discord.Client):
    """Discord bot that bridges messages to JARVIS with streaming."""

    def __init__(self, jarvis: JarvisClient, stream_client: JarvisStreamClient, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, **kwargs)
        self.jarvis = jarvis
        self.stream_client = stream_client
        self.prefix = os.environ.get("ECHO_DISCORD_PREFIX", "!jarvis ")
        self.respond_to_mentions = os.environ.get(
            "ECHO_DISCORD_RESPOND_TO_MENTIONS", "1"
        ) == "1"

    async def on_ready(self):
        logger.info("Discord bot connected as %s", self.user)

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
        if message.author.bot:
            return

        text = message.content.strip()
        is_mention = self.user in message.mentions if self.user else False
        is_dm = isinstance(message.channel, discord.DMChannel)
        has_prefix = text.lower().startswith(self.prefix.lower())

        if not (is_dm or (is_mention and self.respond_to_mentions) or has_prefix):
            return

        if has_prefix:
            text = text[len(self.prefix):].strip()
        elif is_mention and self.user:
            text = text.replace(f"<@{self.user.id}>", "").strip()

        if not text:
            return

        logger.info(
            "Discord message from %s in %s: %s",
            message.author.name, message.channel.id, text[:100],
        )

        channel_id = str(message.channel.id)
        session_id = get_session(PLATFORM, channel_id)
        idempotency_key = f"discord-{message.id or uuid.uuid4().hex}"

        # Post initial "thinking" reply that we'll edit
        reply_msg = await message.reply("...")

        # Try streaming
        streamed = await self._stream_response(
            reply_msg, text, session_id, idempotency_key, channel_id,
        )

        if not streamed:
            # Fallback: sync with typing indicator
            async with message.channel.typing():
                try:
                    response = await self.jarvis.chat(
                        message=text,
                        session_id=session_id,
                        idempotency_key=idempotency_key,
                    )
                except Exception as exc:
                    logger.error("JARVIS call failed: %s", exc, exc_info=True)
                    await reply_msg.edit(content="Sorry, I couldn't process that right now.")
                    return

                if response.session_id:
                    set_session(PLATFORM, channel_id, response.session_id)

                reply = to_discord(response.text or "I processed your message but have no response.")
                chunks = _split_message(reply, DISCORD_MAX_LENGTH)

                await reply_msg.edit(content=chunks[0])
                for chunk in chunks[1:]:
                    await message.reply(chunk)

        logger.info("Replied in %s", channel_id)

    async def _stream_response(
        self,
        reply_msg: discord.Message,
        text: str,
        session_id: str | None,
        idempotency_key: str,
        channel_id: str,
    ) -> bool:
        """Stream JARVIS response with progressive Discord message edits."""
        try:
            response = await self.jarvis.chat_async(
                message=text,
                session_id=session_id,
                idempotency_key=idempotency_key,
            )

            if not response.turn_id or not response.session_id:
                return False

            set_session(PLATFORM, channel_id, response.session_id)
            accumulator = StreamAccumulator(throttle_seconds=1.2)  # Discord rate limit

            async for event in self.stream_client.stream(response.session_id, response.turn_id):
                if event.type == "assistant.delta" and event.delta:
                    accumulator.feed(event.delta)

                    if accumulator.should_flush():
                        content = to_discord(accumulator.flush())
                        # Truncate to Discord limit for progressive updates
                        if len(content) > DISCORD_MAX_LENGTH:
                            content = content[:DISCORD_MAX_LENGTH - 3] + "..."
                        try:
                            await reply_msg.edit(content=content)
                        except discord.HTTPException as exc:
                            logger.debug("Edit rate limited: %s", exc)

                elif event.type == "assistant.final":
                    final_text = event.text or accumulator.full_text
                    if final_text:
                        formatted = to_discord(final_text)
                        chunks = _split_message(formatted, DISCORD_MAX_LENGTH)
                        await reply_msg.edit(content=chunks[0])
                        for chunk in chunks[1:]:
                            await reply_msg.channel.send(chunk)
                    return True

                elif event.type in TERMINAL_EVENTS:
                    if accumulator.full_text:
                        await reply_msg.edit(content=to_discord(accumulator.full_text))
                    else:
                        await reply_msg.edit(content="Sorry, something went wrong.")
                    return True

            if accumulator.full_text:
                formatted = to_discord(accumulator.full_text)
                chunks = _split_message(formatted, DISCORD_MAX_LENGTH)
                await reply_msg.edit(content=chunks[0])
                for chunk in chunks[1:]:
                    await reply_msg.channel.send(chunk)
                return True

            return False

        except Exception as exc:
            logger.warning("Streaming failed, falling back to sync: %s", exc, exc_info=True)
            return False

    async def close(self):
        await self.jarvis.close()
        await self.stream_client.close()
        await super().close()


def _split_message(text: str, max_length: int = DISCORD_MAX_LENGTH) -> list[str]:
    """Split a message into chunks that fit Discord's character limit."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


def main():
    """Run the Discord adapter."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN is required")

    logger.info("Starting Echo Discord adapter (streaming)...")
    logger.info("JARVIS URL: %s", os.environ.get("JARVIS_URL", "http://localhost:8400"))

    jarvis = JarvisClient()
    stream_client = JarvisStreamClient()
    bot = EchoDiscordBot(jarvis=jarvis, stream_client=stream_client)
    bot.run(token)


if __name__ == "__main__":
    main()
