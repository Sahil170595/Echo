"""Telegram adapter for JARVIS with streaming responses.

Streams JARVIS responses via WebSocket and edits the Telegram message
progressively as tokens arrive. Uses Telegram HTML formatting.

## Setup

1. Message @BotFather on Telegram → /newbot → follow prompts
2. Copy the bot token
3. Set environment variables (see below)

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| TELEGRAM_BOT_TOKEN | Yes | Bot token from @BotFather |
| JARVIS_URL | Yes | JARVIS gateway URL |
| JARVIS_DEVICE_KEY | Yes | Device key for JARVIS auth |
| ECHO_TELEGRAM_ALLOWED_CHATS | No | Comma-separated chat IDs to restrict access (default: all) |
"""

from __future__ import annotations

import logging
import os
import uuid

from echo.shared.client import JarvisClient
from echo.shared.format import to_telegram
from echo.shared.sessions import get_session, set_session
from echo.shared.stream import JarvisStreamClient, StreamAccumulator, TERMINAL_EVENTS

logger = logging.getLogger(__name__)

PLATFORM = "telegram"
TELEGRAM_MAX_LENGTH = 4096


def _parse_allowed_chats() -> set[int] | None:
    """Parse ECHO_TELEGRAM_ALLOWED_CHATS env var into a set of chat IDs."""
    raw = os.environ.get("ECHO_TELEGRAM_ALLOWED_CHATS", "").strip()
    if not raw:
        return None
    try:
        return {int(c.strip()) for c in raw.split(",") if c.strip()}
    except ValueError:
        logger.warning("Invalid ECHO_TELEGRAM_ALLOWED_CHATS: %s — allowing all", raw)
        return None


def _split_message(text: str, max_length: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Split a message into chunks that fit Telegram's character limit."""
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


async def start_command(update, context) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "Hi! I'm connected to JARVIS. Send me a message and I'll forward it."
    )


async def handle_message(update, context) -> None:
    """Handle incoming text messages with streaming."""
    from telegram.constants import ChatAction

    message = update.message
    if not message or not message.text:
        return

    chat_id = message.chat_id
    user = message.from_user

    # Access control
    allowed_chats = context.bot_data.get("allowed_chats")
    if allowed_chats and chat_id not in allowed_chats:
        logger.info("Ignoring message from unauthorized chat %s", chat_id)
        return

    text = message.text.strip()
    if not text:
        return

    username = user.username or user.first_name or str(user.id) if user else "unknown"
    logger.info("Telegram message from %s in %s: %s", username, chat_id, text[:100])

    session_id = get_session(PLATFORM, str(chat_id))
    jarvis: JarvisClient = context.bot_data["jarvis"]
    stream_client: JarvisStreamClient = context.bot_data["stream_client"]
    idempotency_key = f"telegram-{message.message_id or uuid.uuid4().hex}"

    # Show typing and post initial "thinking" message
    await message.chat.send_action(ChatAction.TYPING)
    reply_msg = await message.reply_text("...")

    # Try streaming
    streamed = await _stream_response(
        reply_msg, jarvis, stream_client,
        text, session_id, idempotency_key, str(chat_id),
    )

    if not streamed:
        # Fallback: sync
        try:
            response = await jarvis.chat(
                message=text,
                session_id=session_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            logger.error("JARVIS call failed: %s", exc, exc_info=True)
            await reply_msg.edit_text("Sorry, I couldn't process that right now.")
            return

        if response.session_id:
            set_session(PLATFORM, str(chat_id), response.session_id)

        reply = response.text or "I processed your message but have no response."
        formatted = to_telegram(reply)
        chunks = _split_message(formatted, TELEGRAM_MAX_LENGTH)

        try:
            await reply_msg.edit_text(chunks[0], parse_mode="HTML")
        except Exception:
            # If HTML parse fails, send as plain text
            await reply_msg.edit_text(chunks[0])

        for chunk in chunks[1:]:
            try:
                await message.reply_text(chunk, parse_mode="HTML")
            except Exception:
                await message.reply_text(chunk)

    logger.info("Replied in %s", chat_id)


async def _stream_response(
    reply_msg,
    jarvis: JarvisClient,
    stream_client: JarvisStreamClient,
    text: str,
    session_id: str | None,
    idempotency_key: str,
    channel_id: str,
) -> bool:
    """Stream JARVIS response with progressive Telegram message edits."""
    try:
        response = await jarvis.chat_async(
            message=text,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )

        if not response.turn_id or not response.session_id:
            return False

        set_session(PLATFORM, channel_id, response.session_id)
        accumulator = StreamAccumulator(throttle_seconds=1.0)

        async for event in stream_client.stream(response.session_id, response.turn_id):
            if event.type == "assistant.delta" and event.delta:
                accumulator.feed(event.delta)

                if accumulator.should_flush():
                    content = accumulator.flush()
                    if len(content) > TELEGRAM_MAX_LENGTH:
                        content = content[:TELEGRAM_MAX_LENGTH - 3] + "..."
                    try:
                        await reply_msg.edit_text(content)
                    except Exception as exc:
                        logger.debug("Edit failed (rate limit or unchanged): %s", exc)

            elif event.type == "assistant.final":
                final_text = event.text or accumulator.full_text
                if final_text:
                    formatted = to_telegram(final_text)
                    chunks = _split_message(formatted, TELEGRAM_MAX_LENGTH)
                    try:
                        await reply_msg.edit_text(chunks[0], parse_mode="HTML")
                    except Exception:
                        await reply_msg.edit_text(chunks[0])
                    for chunk in chunks[1:]:
                        try:
                            await reply_msg.reply_text(chunk, parse_mode="HTML")
                        except Exception:
                            await reply_msg.reply_text(chunk)
                return True

            elif event.type in TERMINAL_EVENTS:
                if accumulator.full_text:
                    await reply_msg.edit_text(accumulator.full_text)
                else:
                    await reply_msg.edit_text("Sorry, something went wrong.")
                return True

        if accumulator.full_text:
            formatted = to_telegram(accumulator.full_text)
            chunks = _split_message(formatted, TELEGRAM_MAX_LENGTH)
            try:
                await reply_msg.edit_text(chunks[0], parse_mode="HTML")
            except Exception:
                await reply_msg.edit_text(chunks[0])
            return True

        return False

    except Exception as exc:
        logger.warning("Streaming failed, falling back to sync: %s", exc, exc_info=True)
        return False


def main():
    """Run the Telegram adapter."""
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    logger.info("Starting Echo Telegram adapter (streaming)...")
    logger.info("JARVIS URL: %s", os.environ.get("JARVIS_URL", "http://localhost:8400"))

    jarvis = JarvisClient()
    stream_client = JarvisStreamClient()
    allowed_chats = _parse_allowed_chats()

    app = ApplicationBuilder().token(token).build()
    app.bot_data["jarvis"] = jarvis
    app.bot_data["stream_client"] = stream_client
    app.bot_data["allowed_chats"] = allowed_chats

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Allowed chats: %s", allowed_chats if allowed_chats else "all")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
