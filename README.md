# Echo — Channel Adapters for Chimera

Echo is the messaging bridge between external platforms (Slack, Discord, email, Telegram) and the JARVIS AI gateway. Each adapter is a lightweight HTTP relay: platform event in, JARVIS API call, platform response back.

## Architecture

```
Slack/Discord/Email/Telegram
        |
        v
   Echo Adapter (~200 LOC each)
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

| Adapter | Platform | Status |
|---------|----------|--------|
| `slack/` | Slack (Bot API + Events API) | In progress |
| `discord/` | Discord (Bot API + Gateway) | Planned |
| `email/` | Email (IMAP/SMTP) | Planned |
| `telegram/` | Telegram (Bot API) | Planned |

## Quick Start

```bash
# Install
pip install -e ".[slack]"

# Configure
export JARVIS_URL=http://localhost:8400
export JARVIS_DEVICE_KEY=your-device-key
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...

# Run Slack adapter
python -m echo.slack
```

## Configuration

All adapters share these environment variables:

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `JARVIS_URL` | Yes | `http://localhost:8400` | JARVIS gateway URL |
| `JARVIS_DEVICE_KEY` | Yes | — | Device key for JARVIS auth |

Each adapter has additional platform-specific variables (see adapter README).

## How It Works

1. User sends message on Slack/Discord/etc.
2. Echo receives the platform event (webhook or websocket)
3. Echo calls `POST /jarvis/v2/chat` with the message
4. JARVIS processes: memory retrieval, LLM response, constitutional routing
5. Echo receives the response (sync or via WebSocket stream)
6. Echo formats and sends the response back to the platform

Memory, learning, workflows, proactive — all handled by JARVIS. Echo is stateless.

## Related Repos

| Repo | Purpose |
|------|---------|
| [Banterpacks](https://github.com/Sahil170595/Banterpacks) | Core intelligence (JARVIS, TDD002, Chimera, TDD005) |
| [Chimeradroid](https://github.com/Sahil170595/Chimeradroid) | Mobile companion (Unity, offline-first) |
| [Chimera_Multi_agent](https://github.com/Sahil170595/Chimera_Multi_agent) | Muse Protocol (observability, autonomous agents) |
