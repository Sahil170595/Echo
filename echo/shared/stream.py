"""WebSocket streaming client for JARVIS.

Connects to the JARVIS streaming endpoint, authenticates via client.hello,
and yields assistant.delta tokens as they arrive. Handles reconnection,
ping/pong keepalive, and graceful shutdown.

Usage:
    async for event in stream_client.stream(session_id, turn_id):
        if event.type == "assistant.delta":
            print(event.delta, end="", flush=True)
        elif event.type == "assistant.final":
            break
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

import aiohttp

logger = logging.getLogger(__name__)

# Events that carry streamed text
DELTA_EVENTS = {"assistant.delta"}
TERMINAL_EVENTS = {"assistant.final", "turn.failed", "turn.cancelled"}
ALL_STREAM_EVENTS = DELTA_EVENTS | TERMINAL_EVENTS | {
    "turn.started",
    "tool.proposed",
    "tool.result",
}

# Throttle: minimum seconds between message edits (platform rate limits)
DEFAULT_EDIT_THROTTLE = 1.0

# Reconnect backoff
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_BASE_DELAY = 0.5


@dataclass
class StreamEvent:
    """A single event from the JARVIS WebSocket stream."""

    type: str
    turn_id: str | None
    session_id: str
    seq: int
    timestamp: str
    delta: str | None = None
    text: str | None = None
    payload: dict = field(default_factory=dict)

    @classmethod
    def from_wire(cls, data: dict) -> StreamEvent:
        """Parse a wire-format event dict into a StreamEvent."""
        return cls(
            type=data.get("type", ""),
            turn_id=data.get("turn_id"),
            session_id=data.get("session_id", ""),
            seq=data.get("seq", 0),
            timestamp=data.get("timestamp", ""),
            delta=data.get("delta"),
            text=data.get("text") or data.get("final_response"),
            payload=data.get("payload", {}),
        )


@dataclass
class StreamAccumulator:
    """Accumulates deltas and tracks edit throttling.

    Call `feed(delta)` with each token. Call `should_flush()` to check
    if enough time has passed for a platform edit. Call `flush()` to get
    the accumulated text and reset the pending buffer.
    """

    full_text: str = ""
    _pending: str = ""
    _last_flush: float = 0.0
    throttle_seconds: float = DEFAULT_EDIT_THROTTLE

    def feed(self, delta: str) -> None:
        self.full_text += delta
        self._pending += delta

    def should_flush(self) -> bool:
        if not self._pending:
            return False
        now = time.monotonic()
        return (now - self._last_flush) >= self.throttle_seconds

    def flush(self) -> str:
        """Return full accumulated text and mark flushed."""
        self._pending = ""
        self._last_flush = time.monotonic()
        return self.full_text

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)


class JarvisStreamClient:
    """WebSocket client for JARVIS streaming endpoint.

    Connects to /jarvis/stream, authenticates, and yields StreamEvents
    for a specific turn. Used by adapters to stream responses progressively.
    """

    def __init__(
        self,
        base_url: str | None = None,
        device_key: str | None = None,
    ) -> None:
        raw_url = (
            base_url or os.environ.get("JARVIS_URL", "http://localhost:8400")
        ).rstrip("/")
        # Convert http(s) to ws(s)
        self.ws_url = raw_url.replace("https://", "wss://").replace("http://", "ws://")
        self.device_key = device_key or os.environ.get("JARVIS_DEVICE_KEY", "")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def stream(
        self,
        session_id: str,
        turn_id: str,
        timeout: float = 60.0,
    ) -> AsyncIterator[StreamEvent]:
        """Connect to JARVIS WebSocket and yield events for a specific turn.

        Args:
            session_id: The JARVIS session to connect to.
            turn_id: The specific turn to filter events for.
            timeout: Maximum seconds to wait for the stream to complete.

        Yields:
            StreamEvent objects as they arrive from the WebSocket.
        """
        url = f"{self.ws_url}/jarvis/stream?session_id={session_id}"
        session = await self._get_session()
        deadline = asyncio.get_event_loop().time() + timeout

        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            last_seq = 0
            try:
                async with session.ws_connect(url, timeout=10) as ws:
                    # Authenticate
                    hello = {
                        "type": "client.hello",
                        "token": self.device_key,
                        "session_id": session_id,
                    }
                    await ws.send_json(hello)

                    # Wait for server.hello
                    server_hello = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    if server_hello.get("type") == "server.error":
                        logger.error("Stream auth failed: %s", server_hello.get("error"))
                        return
                    if not server_hello.get("ok"):
                        logger.error("Stream handshake failed: %s", server_hello)
                        return

                    # If reconnecting, resume from last sequence
                    if attempt > 0 and last_seq > 0:
                        await ws.send_json({
                            "type": "client.resume",
                            "last_seq": last_seq,
                        })

                    # Read events until terminal or timeout
                    while asyncio.get_event_loop().time() < deadline:
                        remaining = deadline - asyncio.get_event_loop().time()
                        if remaining <= 0:
                            return

                        try:
                            msg = await asyncio.wait_for(
                                ws.receive(), timeout=min(remaining, 30)
                            )
                        except asyncio.TimeoutError:
                            # Send ping to keep alive
                            await ws.send_json({"type": "client.ping"})
                            continue

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            evt_type = data.get("type", "")

                            # Skip protocol messages
                            if evt_type in ("server.pong", "server.ping"):
                                if evt_type == "server.ping":
                                    await ws.send_json({"type": "client.pong"})
                                continue

                            # Filter to our turn
                            evt_turn = data.get("turn_id")
                            if evt_turn and evt_turn != turn_id:
                                continue

                            last_seq = data.get("seq", last_seq)
                            event = StreamEvent.from_wire(data)
                            yield event

                            if event.type in TERMINAL_EVENTS:
                                return

                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            logger.warning("WebSocket closed/error, attempt %d", attempt + 1)
                            break

                # If we exited the loop cleanly (timeout), don't retry
                return

            except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as exc:
                delay = RECONNECT_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Stream connection failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1,
                    MAX_RECONNECT_ATTEMPTS,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error("Stream failed after %d attempts", MAX_RECONNECT_ATTEMPTS)
