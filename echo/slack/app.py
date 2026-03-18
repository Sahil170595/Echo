"""Slack adapter for JARVIS using Slack Bolt (Socket Mode).

Listens for messages and app mentions in Slack, forwards them to JARVIS,
and posts the response back to the channel.

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

import asyncio
import logging
import os
import uuid

from echo.shared.client import JarvisClient

logger = logging.getLogger(__name__)

# Session tracking: map Slack channel_id to JARVIS session_id
_channel_sessions: dict[str, str] = {}


def create_slack_app():
    """Create and configure the Slack Bolt app."""
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    respond_to_bots = os.environ.get("ECHO_SLACK_RESPOND_TO_BOTS", "") == "1"

    if not bot_token:
        raise ValueError("SLACK_BOT_TOKEN is required")
    if not app_token:
        raise ValueError("SLACK_APP_TOKEN is required")

    app = App(token=bot_token)
    jarvis = JarvisClient()

    @app.event("message")
    def handle_message(event, say):
        """Handle direct messages and channel messages."""
        _handle_event(event, say, jarvis, respond_to_bots)

    @app.event("app_mention")
    def handle_mention(event, say):
        """Handle @mentions of the bot."""
        _handle_event(event, say, jarvis, respond_to_bots)

    return app, SocketModeHandler(app, app_token)


def _handle_event(event: dict, say, jarvis: JarvisClient, respond_to_bots: bool):
    """Process a Slack event by forwarding to JARVIS."""
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

    # Strip bot mention from text (for @mentions)
    # Slack sends "<@BOT_ID> message" — strip the mention prefix
    if text.startswith("<@"):
        parts = text.split(">", 1)
        if len(parts) > 1:
            text = parts[1].strip()
        if not text:
            return

    channel_id = event.get("channel", "")
    user_id = event.get("user", "")

    logger.info(
        "Slack message from %s in %s: %s",
        user_id,
        channel_id,
        text[:100],
    )

    # Get or create JARVIS session for this channel
    session_id = _channel_sessions.get(channel_id)

    # Run async JARVIS call in a sync context (Slack Bolt is sync)
    loop = asyncio.new_event_loop()
    try:
        response = loop.run_until_complete(
            jarvis.chat(
                message=text,
                session_id=session_id,
                idempotency_key=f"slack-{event.get('client_msg_id', uuid.uuid4().hex)}",
                mode="sync",
                wait_ms=15000,
            )
        )
    except Exception as exc:
        logger.error("JARVIS call failed: %s", exc)
        say("Sorry, I couldn't process that right now.")
        return
    finally:
        loop.run_until_complete(jarvis.close())
        loop.close()

    # Track session for continuity
    if response.session_id:
        _channel_sessions[channel_id] = response.session_id

    # Send response
    reply = response.text or "I processed your message but have no response."
    say(reply)

    logger.info(
        "Replied in %s: %s",
        channel_id,
        reply[:100],
    )


def main():
    """Run the Slack adapter."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    logger.info("Starting Echo Slack adapter...")
    logger.info("JARVIS URL: %s", os.environ.get("JARVIS_URL", "http://localhost:8400"))

    app, handler = create_slack_app()
    handler.start()


if __name__ == "__main__":
    main()
