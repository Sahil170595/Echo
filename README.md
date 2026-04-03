# Echo — Channel Adapters for Chimera

Echo is the messaging bridge between external platforms (Slack, Discord, Telegram, WhatsApp, Email) and the JARVIS AI gateway. Each adapter is a lightweight HTTP relay: platform event in, JARVIS API call, platform response back.

## Architecture

```
Slack/Discord/Telegram/WhatsApp/Email
        |
        v
   Echo Adapter (~150-200 LOC each)
        |
        v
   POST /jarvis/v2/chat (HTTP)
        |
        v
   JARVIS AI Gateway
   (memory, routing, workflows, tools)
```

Echo does not contain intelligence. It is a message relay with platform-specific formatting. All intelligence lives in JARVIS (Banterpacks repo).

## Adapters

| Adapter | Platform | Status | Transport |
|---------|----------|--------|-----------|
| `slack/` | Slack (Bot API + Socket Mode) | **Production** | WebSocket (Socket Mode) |
| `discord/` | Discord (Bot API + Gateway) | **Production** | WebSocket (Gateway) |
| `telegram/` | Telegram (Bot API) | **Production** | Long Polling |
| `whatsapp/` | WhatsApp (Meta Cloud API) | **Production** | Webhook (HTTP) |
| `email/` | Email (IMAP/SMTP) | **Production** | IMAP Poll + SMTP |

## Quick Start

```bash
# Install (pick your adapter)
pip install -e ".[slack]"
pip install -e ".[discord]"
pip install -e ".[telegram]"
pip install -e "."  # email and whatsapp use core aiohttp only

# Configure (shared)
export JARVIS_URL=http://localhost:8400
export JARVIS_DEVICE_KEY=your-device-key

# --- Slack ---
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
python -m echo.slack

# --- Discord ---
export DISCORD_BOT_TOKEN=your-bot-token
python -m echo.discord

# --- Telegram ---
export TELEGRAM_BOT_TOKEN=your-bot-token
python -m echo.telegram

# --- WhatsApp ---
export WHATSAPP_ACCESS_TOKEN=your-access-token
export WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
export ECHO_WHATSAPP_VERIFY_TOKEN=your-verify-token
python -m echo.whatsapp

# --- Email ---
export ECHO_EMAIL_IMAP_HOST=imap.gmail.com
export ECHO_EMAIL_SMTP_HOST=smtp.gmail.com
export ECHO_EMAIL_ADDRESS=you@gmail.com
export ECHO_EMAIL_PASSWORD=your-app-password
python -m echo.email
```

## Configuration

All adapters share these environment variables:

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `JARVIS_URL` | Yes | `http://localhost:8400` | JARVIS gateway URL |
| `JARVIS_DEVICE_KEY` | Yes | — | Device key for JARVIS auth |

### Access Control

Each adapter supports restricting who can interact:

| Adapter | Variable | Format |
|---------|----------|--------|
| Telegram | `ECHO_TELEGRAM_ALLOWED_CHATS` | Comma-separated chat IDs |
| WhatsApp | `ECHO_WHATSAPP_ALLOWED_NUMBERS` | Comma-separated phone numbers |
| Email | `ECHO_EMAIL_ALLOWED_SENDERS` | Comma-separated email addresses |

Slack and Discord use platform-native permissions (channel membership, server roles).

## Docker

```bash
# Single adapter
docker build -t echo .
docker run -e ECHO_ADAPTER=telegram -e TELEGRAM_BOT_TOKEN=... echo

# Via docker-compose (from Banterpacks)
docker compose -f docker/docker-compose.yml --profile channels up -d
```

## How It Works

1. User sends message on Slack/Discord/Telegram/WhatsApp/Email
2. Echo receives the platform event (webhook, websocket, or IMAP poll)
3. Echo calls `POST /jarvis/v2/chat` with the message
4. JARVIS processes: memory retrieval, LLM response, constitutional routing
5. Echo receives the response (sync or via polling)
6. Echo formats and sends the response back to the platform

Memory, learning, workflows, proactive — all handled by JARVIS. Echo is stateless.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

## Related Repos

| Repo | Purpose |
|------|---------|
| [Banterpacks](https://github.com/Sahil170595/Banterpacks) | Core intelligence (JARVIS, TDD002, Chimera, TDD005) |
| [Chimeradroid](https://github.com/Sahil170595/Chimeradroid) | Mobile companion (Unity, offline-first) |
| [Chimera_Multi_agent](https://github.com/Sahil170595/Chimera_Multi_agent) | Muse Protocol (observability, autonomous agents) |
