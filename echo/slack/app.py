"""Slack adapter for JARVIS with streaming responses.

Uses async Slack Bolt for proper concurrency. Streams JARVIS responses
via WebSocket and edits the Slack message progressively as tokens arrive.

## Setup

1. Create a Slack App at https://api.slack.com/apps
2. Enable Socket Mode (Settings > Socket Mode)
3. Add Bot Token Scopes: chat:write, app_mentions:read, channels:history, im:history
4. Subscribe to Events: message.channels, message.im, app_mention
5. Install to workspace
6. Set environment variables (see below)

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| SLACK_BOT_TOKEN | Yes | Bot User OAuth Token (xoxb-...) |
| SLACK_APP_TOKEN | Yes | App-Level Token for Socket Mode (xapp-...) |
| JARVIS_URL | Yes | JARVIS gateway URL |
| JARVIS_DEVICE_KEY | Yes | Device key for JARVIS auth |
| ECHO_SLACK_RESPOND_TO_BOTS | No | Set "1" to respond to bot messages (default: ignore) |
"""

from __future__ import annotations

import logging
import os
import uuid

from echo.shared.client import JarvisClient
from echo.shared.format import to_slack
from echo.shared.sessions import get_session, set_session
from echo.shared.stream import JarvisStreamClient, StreamAccumulator, TERMINAL_EVENTS

logger = logging.getLogger(__name__)

PLATFORM = "slack"


def create_slack_app():
    """Create and configure the async Slack Bolt app."""
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    respond_to_bots = os.environ.get("ECHO_SLACK_RESPOND_TO_BOTS", "") == "1"

    if not bot_token:
        raise ValueError("SLACK_BOT_TOKEN is required")
    if not app_token:
        raise ValueError("SLACK_APP_TOKEN is required")

    app = AsyncApp(token=bot_token)
    jarvis = JarvisClient()
    stream_client = JarvisStreamClient()

    @app.event("message")
    async def handle_message(event, say, client):
        await _handle_event(event, say, client, jarvis, stream_client, respond_to_bots)

    @app.event("app_mention")
    async def handle_mention(event, say, client):
        await _handle_event(event, say, client, jarvis, stream_client, respond_to_bots)

    return app, AsyncSocketModeHandler(app, app_token)


async def _handle_event(
    event: dict,
    say,
    client,
    jarvis: JarvisClient,
    stream_client: JarvisStreamClient,
    respond_to_bots: bool,
):
    """Process a Slack event by streaming JARVIS response with progressive edits."""
    # Skip bot messages (unless configured otherwise)
    if event.get("bot_id") and not respond_to_bots:
        return
    # Skip message edits, deletes, etc.
    subtype = event.get("subtype")
    if subtype and subtype not in ("file_share",):
        return

    text = (event.get("text") or "").strip()
    if not text:
        return

    # Strip bot mention from text
    if text.startswith("<@"):
        parts = text.split(">", 1)
        if len(parts) > 1:
            text = parts[1].strip()
        if not text:
            return

    channel_id = event.get("channel", "")
    user_id = event.get("user", "")

    logger.info("Slack message from %s in %s: %s", user_id, channel_id, text[:100])

    # Persistent session lookup
    session_id = get_session(PLATFORM, channel_id)
    idempotency_key = f"slack-{event.get('client_msg_id', uuid.uuid4().hex)}"

    # Post initial "thinking" message that we'll edit with streamed content
    initial = await say("...")
    msg_ts = initial.get("ts") if isinstance(initial, dict) else None

    # Try streaming first, fall back to sync
    streamed = False
    if msg_ts:
        streamed = await _stream_response(
            client, channel_id, msg_ts,
            jarvis, stream_client,
            text, session_id, idempotency_key,
        )

    if not streamed:
        # Fallback: sync request
        try:
            response = await jarvis.chat(
                message=text,
                session_id=session_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            logger.error("JARVIS call failed: %s", exc, exc_info=True)
            if msg_ts:
                await client.chat_update(
                    channel=channel_id, ts=msg_ts,
                    text="Sorry, I couldn't process that right now.",
                )
            else:
                await say("Sorry, I couldn't process that right now.")
            return

        if response.session_id:
            set_session(PLATFORM, channel_id, response.session_id)

        reply = to_slack(response.text or "I processed your message but have no response.")
        if msg_ts:
            await client.chat_update(channel=channel_id, ts=msg_ts, text=reply)
        else:
            await say(reply)

    logger.info("Replied in %s", channel_id)


async def _stream_response(
    client,
    channel_id: str,
    msg_ts: str,
    jarvis: JarvisClient,
    stream_client: JarvisStreamClient,
    message: str,
    session_id: str | None,
    idempotency_key: str,
) -> bool:
    """Stream JARVIS response and edit the Slack message progressively.

    Returns True if streaming succeeded, False to fall back to sync.
    """
    try:
        # Start async turn
        response = await jarvis.chat_async(
            message=message,
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
                    formatted = to_slack(accumulator.flush())
                    try:
                        await client.chat_update(
                            channel=channel_id, ts=msg_ts, text=formatted,
                        )
                    except Exception as exc:
                        logger.debug("Edit throttled: %s", exc)

            elif event.type == "assistant.final":
                final_text = event.text or accumulator.full_text
                if final_text:
                    formatted = to_slack(final_text)
                    await client.chat_update(
                        channel=channel_id, ts=msg_ts, text=formatted,
                    )
                return True

            elif event.type in TERMINAL_EVENTS:
                # Turn failed/cancelled
                if accumulator.full_text:
                    formatted = to_slack(accumulator.full_text)
                    await client.chat_update(
                        channel=channel_id, ts=msg_ts, text=formatted,
                    )
                else:
                    await client.chat_update(
                        channel=channel_id, ts=msg_ts,
                        text="Sorry, something went wrong.",
                    )
                return True

        # Stream ended without terminal event — use whatever we have
        if accumulator.full_text:
            formatted = to_slack(accumulator.full_text)
            await client.chat_update(channel=channel_id, ts=msg_ts, text=formatted)
            return True

        return False

    except Exception as exc:
        logger.warning("Streaming failed, falling back to sync: %s", exc, exc_info=True)
        return False


def main():
    """Run the Slack adapter."""
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    logger.info("Starting Echo Slack adapter (streaming)...")
    logger.info("JARVIS URL: %s", os.environ.get("JARVIS_URL", "http://localhost:8400"))

    app, handler = create_slack_app()
    asyncio.run(handler.start_async())


if __name__ == "__main__":
    main()
