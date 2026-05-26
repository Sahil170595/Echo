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

import asyncio
import logging
import os
import time
import uuid

from echo.shared.client import JarvisClient
from echo.shared.format import to_telegram
from echo.shared.sessions import get_session, set_session
from echo.shared.stream import JarvisStreamClient, StreamAccumulator, TERMINAL_EVENTS

logger = logging.getLogger(__name__)

PLATFORM = "telegram"
TELEGRAM_MAX_LENGTH = 4096


async def _safe_edit(msg, text: str, **kwargs) -> None:
    """Edit a Telegram message, treating the benign "message is not modified"
    response as success.

    Telegram returns ``BadRequest("message is not modified")`` when an edit's
    content matches what's already displayed. That happens routinely here: the
    streamed deltas already render a short reply in full, then the
    ``assistant.final`` edit re-sends identical text. It is NOT an error — the
    message is already correct. Treating it as one previously bubbled up, made
    ``_stream_response`` report failure, and triggered a redundant sync-fallback
    turn (a second JARVIS call) that then crashed on the same no-op edit. Other
    ``BadRequest``s (e.g. HTML entity-parse errors) still propagate so callers
    can fall back to plain text.
    """
    from telegram.error import BadRequest

    try:
        await msg.edit_text(text, **kwargs)
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        raise


async def _render_final(reply_msg, text: str) -> None:
    """Render a final answer into the Telegram message.

    Edits ``reply_msg`` with the HTML-formatted first chunk (falling back to
    plain text if Telegram rejects the entities), then sends any overflow
    chunks as follow-up messages. Central so the streaming-final, incomplete-
    stream, and sync-fallback paths all render identically.
    """
    formatted = to_telegram(text)
    chunks = _split_message(formatted, TELEGRAM_MAX_LENGTH)
    try:
        await _safe_edit(reply_msg, chunks[0], parse_mode="HTML")
    except Exception:
        await _safe_edit(reply_msg, chunks[0])
    for chunk in chunks[1:]:
        try:
            await reply_msg.reply_text(chunk, parse_mode="HTML")
        except Exception:
            await reply_msg.reply_text(chunk)


async def _typing_keepalive(chat, interval: float = 4.0) -> None:
    """Re-send the TYPING chat action every ``interval`` seconds until cancelled.

    Telegram's typing indicator expires after ~5s. A slow turn (slow-path
    debate, cold model) can run far longer than that with no token yet, leaving
    the user staring at a dead ``"..."``. This keeps "typing…" alive for the
    whole turn; the caller cancels it once the reply is rendered.
    """
    from telegram.constants import ChatAction

    logged = False
    try:
        while True:
            await chat.send_action(ChatAction.TYPING)
            await asyncio.sleep(interval)
            if not logged:
                # Fires once per turn that outlives the first interval — i.e.
                # exactly the slow turns where the keepalive earns its keep.
                logged = True
                logger.info(
                    "Slow turn (>%.0fs) — keeping the typing indicator alive", interval
                )
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # never let keepalive failure break the turn
        logger.debug("typing keepalive stopped: %s", exc)


def _parse_allowed_chats() -> set[int] | None:
    """Parse ECHO_TELEGRAM_ALLOWED_CHATS env var into a set of chat IDs."""
    raw = os.environ.get("ECHO_TELEGRAM_ALLOWED_CHATS", "").strip()
    if not raw:
        return None
    try:
        return {int(c.strip()) for c in raw.split(",") if c.strip()}
    except ValueError:
        # Fail CLOSED: the var was set (operator intended a restriction) but is
        # malformed. Returning None would "allow all" — silently opening the bot
        # to anyone. An empty set rejects everyone until the config is fixed.
        logger.error(
            "Invalid ECHO_TELEGRAM_ALLOWED_CHATS: %r — failing closed (rejecting all). "
            "Fix the value (comma-separated numeric chat ids) or unset it to allow all.",
            raw,
        )
        return set()


def _is_authorized(context, chat_id: int) -> bool:
    """Return True if this chat may use the bot.

    ``allowed_chats is None`` means no restriction (var unset → allow all). A
    set — including an empty one (malformed config, fail-closed) — is an
    allowlist: only listed chats pass.
    """
    allowed_chats = context.bot_data.get("allowed_chats")
    if allowed_chats is None:
        return True
    return chat_id in allowed_chats


def _split_message(text: str, max_length: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Split a message into chunks that fit Telegram's character limit.

    Prefers a newline, then a space, before a hard cut — and never splits inside
    an HTML ``<tag>`` (which would break ``parse_mode=HTML`` for that chunk).
    Note: a formatting span crossing the boundary (e.g. an open ``<b>`` whose
    ``</b>`` lands in the next chunk) still degrades to plain text per the
    render fallback — fully tag-balanced splitting is out of scope.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Prefer a newline, then a space, to avoid mid-word cuts.
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = text.rfind(" ", 0, max_length)
        if split_at == -1:
            split_at = max_length
        # Don't cut inside a tag: if an unclosed '<' precedes the split point,
        # back up to before it.
        head = text[:split_at]
        last_open = head.rfind("<")
        if last_open > head.rfind(">"):
            split_at = last_open
        if split_at <= 0:  # never stall (e.g. a tag longer than the budget)
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

    if not _is_authorized(context, chat_id):
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
    t0 = time.monotonic()
    await message.chat.send_action(ChatAction.TYPING)
    reply_msg = await message.reply_text("...")

    # Keep "typing…" alive for the whole turn — a slow-path debate or cold model
    # can outlast Telegram's ~5s indicator before the first token arrives.
    keepalive = asyncio.create_task(_typing_keepalive(message.chat))
    try:
        streamed = await _stream_response(
            reply_msg, jarvis, stream_client,
            text, session_id, idempotency_key, str(chat_id),
        )

        if not streamed:
            # Fallback: sync request/response.
            try:
                response = await jarvis.chat(
                    message=text,
                    session_id=session_id,
                    idempotency_key=idempotency_key,
                )
            except Exception as exc:
                logger.error("JARVIS call failed: %s", exc, exc_info=True)
                await _safe_edit(reply_msg, "Sorry, I couldn't process that right now.")
                return

            if response.status == "busy":
                # JARVIS allows one active turn per session (409): the user
                # double-texted before the previous turn finished.
                await _safe_edit(
                    reply_msg,
                    "I'm still finishing your previous message — give me a moment, "
                    "then send that again.",
                )
                return

            if response.session_id:
                set_session(PLATFORM, str(chat_id), response.session_id)

            reply = response.text or (
                "My language model is briefly unavailable — try again in a moment."
            )
            await _render_final(reply_msg, reply)
    finally:
        keepalive.cancel()

    logger.info("Replied in %s (%.1fs)", chat_id, time.monotonic() - t0)


async def handle_unsupported(update, context) -> None:
    """Reply gracefully to non-text messages (voice, photo, sticker, document).

    The text handler filters these out; without this they vanish silently. We
    don't transcribe/OCR (that's a feature, not an edge-case fix) — just tell
    the user so they aren't left wondering, and log it so the path is observable.
    """
    message = update.message
    if not message:
        return
    if not _is_authorized(context, message.chat_id):
        return

    kind = (
        "photo" if message.photo else
        "voice" if message.voice else
        "audio" if message.audio else
        "video" if message.video else
        "video_note" if message.video_note else
        "document" if message.document else
        "sticker" if message.sticker else
        "location" if message.location else
        "other"
    )
    logger.info("Unsupported message (%s) from %s — declined", kind, message.chat_id)
    await message.reply_text(
        "I can only handle text messages right now — send me a text message."
    )


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
                    await _render_final(reply_msg, final_text)
                return True

            elif event.type in TERMINAL_EVENTS:
                if accumulator.full_text:
                    await _safe_edit(reply_msg, accumulator.full_text)
                else:
                    await _safe_edit(reply_msg, "Sorry, something went wrong.")
                return True

        # Stream ended without a terminal event (WS dropped or reconnects
        # exhausted). Don't trust the partial accumulator as if it were final —
        # poll the turn for the authoritative answer, falling back to the
        # partial only if the poll also fails.
        if response.turn_id:
            final = await jarvis.poll_turn(response.turn_id)
            if final:
                await _render_final(reply_msg, final)
                return True
        if accumulator.full_text:
            await _render_final(reply_msg, accumulator.full_text)
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
    # httpx logs every request URL at INFO — which includes the bot token
    # (api.telegram.org/bot<TOKEN>/...). Quiet it so the token never reaches logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)

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
    # Non-text (voice, photo, sticker, document) — reply gracefully instead of
    # dropping it silently. Excludes service/status messages.
    app.add_handler(
        MessageHandler(~filters.TEXT & ~filters.StatusUpdate.ALL, handle_unsupported)
    )

    logger.info(
        "Allowed chats: %s", allowed_chats if allowed_chats is not None else "all"
    )

    # Default to processing messages queued during downtime — don't silently
    # lose a message because the adapter bounced. Set ECHO_TELEGRAM_DROP_PENDING=1
    # to discard the backlog on start instead.
    drop_pending = os.environ.get(
        "ECHO_TELEGRAM_DROP_PENDING", "false"
    ).strip().lower() in ("1", "true", "yes")
    app.run_polling(drop_pending_updates=drop_pending)


if __name__ == "__main__":
    main()
