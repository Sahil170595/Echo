"""WhatsApp adapter for JARVIS using Meta Cloud API.

Receives messages via webhook, forwards them to JARVIS,
and replies via the WhatsApp Business API. Uses sync mode
(WhatsApp doesn't support editing sent messages).

## Setup

1. Create a Meta Developer account at https://developers.facebook.com
2. Create a Business App → Add WhatsApp product
3. Configure webhook:
   - Callback URL: https://your-domain/webhook
   - Verify token: set ECHO_WHATSAPP_VERIFY_TOKEN
   - Subscribe to: messages
4. Get a permanent access token (System User token recommended)
5. Set environment variables (see below)

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| WHATSAPP_ACCESS_TOKEN | Yes | — | Meta API access token |
| WHATSAPP_PHONE_NUMBER_ID | Yes | — | Your WhatsApp Business phone number ID |
| ECHO_WHATSAPP_VERIFY_TOKEN | Yes | — | Webhook verification token (you choose this) |
| ECHO_WHATSAPP_PORT | No | 8090 | Port for webhook server |
| ECHO_WHATSAPP_ALLOWED_NUMBERS | No | — | Comma-separated allowed phone numbers (default: all) |
| JARVIS_URL | Yes | http://localhost:8400 | JARVIS gateway URL |
| JARVIS_DEVICE_KEY | Yes | — | Device key for JARVIS auth |
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

import aiohttp
from aiohttp import web

from echo.shared.client import JarvisClient
from echo.shared.format import to_whatsapp
from echo.shared.sessions import get_session, set_session

logger = logging.getLogger(__name__)

PLATFORM = "whatsapp"
META_API_BASE = "https://graph.facebook.com/v21.0"
WEBHOOK_PORT = 8090
WHATSAPP_MAX_LENGTH = 4096


def _parse_allowed_numbers() -> set[str] | None:
    """Parse ECHO_WHATSAPP_ALLOWED_NUMBERS into a set."""
    raw = os.environ.get("ECHO_WHATSAPP_ALLOWED_NUMBERS", "").strip()
    if not raw:
        return None
    return {n.strip() for n in raw.split(",") if n.strip()}


def _split_message(text: str, max_length: int = WHATSAPP_MAX_LENGTH) -> list[str]:
    """Split a message into chunks that fit WhatsApp's character limit."""
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


class WhatsAppAdapter:
    """WhatsApp Cloud API webhook handler."""

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        verify_token: str,
        jarvis: JarvisClient,
        allowed_numbers: set[str] | None = None,
    ) -> None:
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.verify_token = verify_token
        self.jarvis = jarvis
        self.allowed_numbers = allowed_numbers
        self._http_session: aiohttp.ClientSession | None = None

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
        return self._http_session

    async def close(self) -> None:
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        await self.jarvis.close()

    async def handle_verify(self, request: web.Request) -> web.Response:
        """Handle Meta webhook verification (GET /webhook)."""
        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token")
        challenge = request.query.get("hub.challenge")

        if mode == "subscribe" and token == self.verify_token:
            logger.info("Webhook verified successfully")
            return web.Response(text=challenge or "", status=200)

        logger.warning("Webhook verification failed: mode=%s", mode)
        return web.Response(text="Forbidden", status=403)

    async def handle_webhook(self, request: web.Request) -> web.Response:
        """Handle incoming WhatsApp messages (POST /webhook)."""
        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400)

        # Always return 200 quickly — process async
        messages = self._extract_messages(data)
        for msg in messages:
            asyncio.create_task(self._process_message(msg))

        return web.Response(status=200)

    async def handle_health(self, _request: web.Request) -> web.Response:
        """Health check endpoint."""
        healthy = await self.jarvis.health()
        status = 200 if healthy else 503
        return web.json_response(
            {"status": "ok" if healthy else "degraded", "jarvis": healthy},
            status=status,
        )

    def _extract_messages(self, data: dict) -> list[dict[str, str]]:
        """Extract text messages from the webhook payload."""
        messages = []
        try:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        if msg.get("type") != "text":
                            continue
                        text = msg.get("text", {}).get("body", "").strip()
                        sender = msg.get("from", "")
                        msg_id = msg.get("id", "")
                        if text and sender:
                            messages.append({
                                "from": sender,
                                "text": text,
                                "id": msg_id,
                            })
        except Exception as exc:
            logger.error("Failed to parse webhook payload: %s", exc, exc_info=True)

        return messages

    async def _process_message(self, msg: dict[str, str]) -> None:
        """Forward a WhatsApp message to JARVIS and reply."""
        sender = msg["from"]

        if self.allowed_numbers and sender not in self.allowed_numbers:
            logger.info("Ignoring message from unauthorized number %s", sender)
            return

        logger.info("WhatsApp message from %s: %s", sender, msg["text"][:100])

        session_id = get_session(PLATFORM, sender)

        try:
            response = await self.jarvis.chat(
                message=msg["text"],
                session_id=session_id,
                idempotency_key=f"whatsapp-{msg.get('id', uuid.uuid4().hex)}",
            )
        except Exception as exc:
            logger.error("JARVIS call failed: %s", exc, exc_info=True)
            await self._send_message(sender, "Sorry, I couldn't process that right now.")
            return

        if response.session_id:
            set_session(PLATFORM, sender, response.session_id)

        reply = to_whatsapp(response.text or "I processed your message but have no response.")
        chunks = _split_message(reply, WHATSAPP_MAX_LENGTH)
        for chunk in chunks:
            await self._send_message(sender, chunk)

        logger.info("Replied to %s: %s", sender, reply[:100])

    async def _send_message(self, to: str, text: str) -> None:
        """Send a text message via WhatsApp Cloud API."""
        session = await self._get_http_session()
        url = f"{META_API_BASE}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("WhatsApp send failed: %s %s", resp.status, body[:200])
        except Exception as exc:
            logger.error("WhatsApp send error: %s", exc, exc_info=True)


def main():
    """Run the WhatsApp adapter webhook server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    verify_token = os.environ.get("ECHO_WHATSAPP_VERIFY_TOKEN", "")

    if not access_token:
        raise ValueError("WHATSAPP_ACCESS_TOKEN is required")
    if not phone_number_id:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID is required")
    if not verify_token:
        raise ValueError("ECHO_WHATSAPP_VERIFY_TOKEN is required")

    port = int(os.environ.get("ECHO_WHATSAPP_PORT", str(WEBHOOK_PORT)))

    logger.info("Starting Echo WhatsApp adapter...")
    logger.info("JARVIS URL: %s", os.environ.get("JARVIS_URL", "http://localhost:8400"))
    logger.info("Webhook port: %d", port)

    jarvis = JarvisClient()
    allowed_numbers = _parse_allowed_numbers()
    adapter = WhatsAppAdapter(
        access_token=access_token,
        phone_number_id=phone_number_id,
        verify_token=verify_token,
        jarvis=jarvis,
        allowed_numbers=allowed_numbers,
    )

    logger.info("Allowed numbers: %s", allowed_numbers if allowed_numbers else "all")

    app = web.Application()
    app.router.add_get("/webhook", adapter.handle_verify)
    app.router.add_post("/webhook", adapter.handle_webhook)
    app.router.add_get("/health", adapter.handle_health)

    async def on_cleanup(_app):
        await adapter.close()

    app.on_cleanup.append(on_cleanup)

    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
