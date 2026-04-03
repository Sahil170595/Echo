"""Email adapter for JARVIS using IMAP polling + SMTP replies.

Polls an IMAP mailbox for new messages, forwards them to JARVIS,
and replies via SMTP. Thread-based session tracking using sender address
with persistent SQLite sessions.

## Setup

1. Enable IMAP access on your email provider (Gmail: App Passwords recommended)
2. Set environment variables (see below)
3. For Gmail: use an App Password, not your account password

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| ECHO_EMAIL_IMAP_HOST | Yes | — | IMAP server (e.g., imap.gmail.com) |
| ECHO_EMAIL_IMAP_PORT | No | 993 | IMAP port (SSL) |
| ECHO_EMAIL_SMTP_HOST | Yes | — | SMTP server (e.g., smtp.gmail.com) |
| ECHO_EMAIL_SMTP_PORT | No | 587 | SMTP port (STARTTLS) |
| ECHO_EMAIL_ADDRESS | Yes | — | Email address to monitor and send from |
| ECHO_EMAIL_PASSWORD | Yes | — | Email password or app password |
| ECHO_EMAIL_ALLOWED_SENDERS | No | — | Comma-separated allowed sender emails (default: all) |
| ECHO_EMAIL_POLL_INTERVAL | No | 30 | Seconds between IMAP polls |
| JARVIS_URL | Yes | http://localhost:8400 | JARVIS gateway URL |
| JARVIS_DEVICE_KEY | Yes | — | Device key for JARVIS auth |
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import os
import smtplib
import uuid
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Any

from echo.shared.client import JarvisClient
from echo.shared.format import to_plain
from echo.shared.sessions import get_session, set_session

logger = logging.getLogger(__name__)

PLATFORM = "email"
POLL_INTERVAL_SECONDS = 30


def _get_config() -> dict[str, Any]:
    """Load email configuration from environment."""
    imap_host = os.environ.get("ECHO_EMAIL_IMAP_HOST", "")
    smtp_host = os.environ.get("ECHO_EMAIL_SMTP_HOST", "")
    address = os.environ.get("ECHO_EMAIL_ADDRESS", "")
    password = os.environ.get("ECHO_EMAIL_PASSWORD", "")

    if not all([imap_host, smtp_host, address, password]):
        missing = []
        if not imap_host:
            missing.append("ECHO_EMAIL_IMAP_HOST")
        if not smtp_host:
            missing.append("ECHO_EMAIL_SMTP_HOST")
        if not address:
            missing.append("ECHO_EMAIL_ADDRESS")
        if not password:
            missing.append("ECHO_EMAIL_PASSWORD")
        raise ValueError(f"Missing required env vars: {', '.join(missing)}")

    allowed_raw = os.environ.get("ECHO_EMAIL_ALLOWED_SENDERS", "").strip()
    allowed_senders: set[str] | None = None
    if allowed_raw:
        allowed_senders = {s.strip().lower() for s in allowed_raw.split(",") if s.strip()}

    return {
        "imap_host": imap_host,
        "imap_port": int(os.environ.get("ECHO_EMAIL_IMAP_PORT", "993")),
        "smtp_host": smtp_host,
        "smtp_port": int(os.environ.get("ECHO_EMAIL_SMTP_PORT", "587")),
        "address": address,
        "password": password,
        "allowed_senders": allowed_senders,
        "poll_interval": int(os.environ.get("ECHO_EMAIL_POLL_INTERVAL", str(POLL_INTERVAL_SECONDS))),
    }


def _fetch_unseen(config: dict[str, Any]) -> list[dict[str, str]]:
    """Connect to IMAP and fetch unseen messages."""
    messages = []
    try:
        imap = imaplib.IMAP4_SSL(config["imap_host"], config["imap_port"])
        imap.login(config["address"], config["password"])
        imap.select("INBOX")

        _status, data = imap.search(None, "UNSEEN")
        msg_ids = data[0].split() if data[0] else []

        for msg_id in msg_ids:
            _status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0]
            if isinstance(raw, tuple):
                raw_bytes = raw[1]
            else:
                continue

            msg = email.message_from_bytes(raw_bytes)

            # Extract plain text body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")
                        break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")

            _name, sender_addr = parseaddr(msg.get("From", ""))
            subject = msg.get("Subject", "(no subject)")
            message_id = msg.get("Message-ID", "")

            if sender_addr and body.strip():
                messages.append({
                    "from": sender_addr.lower(),
                    "subject": subject,
                    "body": body.strip(),
                    "message_id": message_id,
                })

        imap.close()
        imap.logout()
    except Exception as exc:
        logger.error("IMAP fetch failed: %s", exc, exc_info=True)

    return messages


def _send_reply(config: dict[str, Any], to: str, subject: str, body: str, in_reply_to: str = "") -> None:
    """Send a reply via SMTP."""
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = config["address"]
        msg["To"] = to
        msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as smtp:
            smtp.starttls()
            smtp.login(config["address"], config["password"])
            smtp.send_message(msg)

        logger.info("Sent reply to %s: %s", to, subject)
    except Exception as exc:
        logger.error("SMTP send failed: %s", exc, exc_info=True)


async def _process_email(
    jarvis: JarvisClient,
    config: dict[str, Any],
    msg: dict[str, str],
) -> None:
    """Forward one email to JARVIS and send the reply."""
    sender = msg["from"]

    allowed = config.get("allowed_senders")
    if allowed and sender not in allowed:
        logger.info("Ignoring email from unauthorized sender %s", sender)
        return

    logger.info("Processing email from %s: %s", sender, msg["subject"])

    session_id = get_session(PLATFORM, sender)

    try:
        response = await jarvis.chat(
            message=msg["body"],
            session_id=session_id,
            idempotency_key=f"email-{msg.get('message_id', uuid.uuid4().hex)}",
        )
    except Exception as exc:
        logger.error("JARVIS call failed for email from %s: %s", sender, exc, exc_info=True)
        return

    if response.session_id:
        set_session(PLATFORM, sender, response.session_id)

    reply_text = to_plain(response.text or "I processed your email but have no response.")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _send_reply,
        config,
        sender,
        msg["subject"],
        reply_text,
        msg.get("message_id", ""),
    )


async def _poll_loop(jarvis: JarvisClient, config: dict[str, Any]) -> None:
    """Main polling loop: fetch unseen emails, process, repeat."""
    poll_interval = config.get("poll_interval", POLL_INTERVAL_SECONDS)
    logger.info("Starting email poll loop (every %ds)", poll_interval)

    while True:
        try:
            loop = asyncio.get_event_loop()
            messages = await loop.run_in_executor(None, _fetch_unseen, config)

            if messages:
                logger.info("Found %d new email(s)", len(messages))

            for msg in messages:
                await _process_email(jarvis, config, msg)

        except Exception as exc:
            logger.error("Poll loop error: %s", exc, exc_info=True)

        await asyncio.sleep(poll_interval)


def main():
    """Run the Email adapter."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = _get_config()
    jarvis = JarvisClient()

    logger.info("Starting Echo Email adapter...")
    logger.info("JARVIS URL: %s", os.environ.get("JARVIS_URL", "http://localhost:8400"))
    logger.info("Monitoring: %s", config["address"])
    logger.info(
        "Allowed senders: %s",
        config["allowed_senders"] if config["allowed_senders"] else "all",
    )

    asyncio.run(_poll_loop(jarvis, config))


if __name__ == "__main__":
    main()
