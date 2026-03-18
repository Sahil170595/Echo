"""Discord adapter for JARVIS using discord.py.

Listens for messages and mentions in Discord, forwards them to JARVIS,
and posts the response back to the channel.

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

logger = logging.getLogger(__name__)

# Session tracking: map Discord channel_id to JARVIS session_id
_channel_sessions: dict[int, str] = {}


class EchoDiscordBot(discord.Client):
    """Discord bot that bridges messages to JARVIS."""

    def __init__(self, jarvis: JarvisClient, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, **kwargs)
        self.jarvis = jarvis
        self.prefix = os.environ.get("ECHO_DISCORD_PREFIX", "!jarvis ")
        self.respond_to_mentions = os.environ.get(
            "ECHO_DISCORD_RESPOND_TO_MENTIONS", "1"
        ) == "1"

    async def on_ready(self):
        logger.info("Discord bot connected as %s", self.user)

    async def on_message(self, message: discord.Message):
        # Don't respond to ourselves
        if message.author == self.user:
            return
        # Don't respond to other bots
        if message.author.bot:
            return

        text = message.content.strip()
        is_mention = self.user in message.mentions if self.user else False
        is_dm = isinstance(message.channel, discord.DMChannel)
        has_prefix = text.lower().startswith(self.prefix.lower())

        # Respond to: DMs, @mentions, or prefix commands
        if not (is_dm or (is_mention and self.respond_to_mentions) or has_prefix):
            return

        # Strip prefix or mention
        if has_prefix:
            text = text[len(self.prefix):].strip()
        elif is_mention and self.user:
            text = text.replace(f"<@{self.user.id}>", "").strip()

        if not text:
            return

        logger.info(
            "Discord message from %s in %s: %s",
            message.author.name,
            message.channel.id,
            text[:100],
        )

        # Get or create JARVIS session for this channel
        session_id = _channel_sessions.get(message.channel.id)

        # Show typing indicator while waiting for JARVIS
        async with message.channel.typing():
            try:
                response = await self.jarvis.chat(
                    message=text,
                    session_id=session_id,
                    idempotency_key=f"discord-{message.id or uuid.uuid4().hex}",
                    mode="sync",
                    wait_ms=15000,
                )
            except Exception as exc:
                logger.error("JARVIS call failed: %s", exc)
                await message.reply("Sorry, I couldn't process that right now.")
                return

        # Track session for continuity
        if response.session_id:
            _channel_sessions[message.channel.id] = response.session_id

        # Send response (split if >2000 chars — Discord limit)
        reply = response.text or "I processed your message but have no response."
        chunks = _split_message(reply, max_length=2000)
        for chunk in chunks:
            await message.reply(chunk)

        logger.info(
            "Replied in %s: %s",
            message.channel.id,
            reply[:100],
        )

    async def close(self):
        await self.jarvis.close()
        await super().close()


def _split_message(text: str, max_length: int = 2000) -> list[str]:
    """Split a message into chunks that fit Discord's character limit."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Try to split at a newline
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            # No newline found, split at max_length
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

    logger.info("Starting Echo Discord adapter...")
    logger.info("JARVIS URL: %s", os.environ.get("JARVIS_URL", "http://localhost:8400"))

    jarvis = JarvisClient()
    bot = EchoDiscordBot(jarvis=jarvis)
    bot.run(token)


if __name__ == "__main__":
    main()
