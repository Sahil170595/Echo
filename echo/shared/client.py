"""HTTP client for the JARVIS AI gateway.

All Echo adapters use this client to send messages and receive responses.
Authentication is via device key (X-Jarvis-Device-Key header).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class JarvisResponse:
    """Response from JARVIS chat API."""

    session_id: str
    turn_id: str
    text: str | None
    status: str
    stream_url: str | None = None
    still_running: bool = False


class JarvisClient:
    """Async HTTP client for JARVIS v2 API."""

    def __init__(
        self,
        base_url: str | None = None,
        device_key: str | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("JARVIS_URL", "http://localhost:8400")
        ).rstrip("/")
        self.device_key = device_key or os.environ.get("JARVIS_DEVICE_KEY", "")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-Jarvis-Device-Key": self.device_key},
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
        idempotency_key: str | None = None,
        mode: str = "sync",
        wait_ms: int = 15000,
    ) -> JarvisResponse:
        """Send a chat message to JARVIS and return the response.

        Args:
            message: The user message.
            session_id: Optional session for conversation continuity.
            idempotency_key: Optional dedup key.
            mode: "sync" (wait for response) or "async" (return immediately).
            wait_ms: How long to wait for sync response (ms).

        Returns:
            JarvisResponse with the assistant's reply.
        """
        session = await self._get_session()
        payload: dict[str, Any] = {
            "message": message,
            "mode": mode,
            "wait_ms": wait_ms,
        }
        if session_id:
            payload["session_id"] = session_id
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key

        url = f"{self.base_url}/jarvis/v2/chat"
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning("JARVIS chat failed: %s %s", resp.status, body[:200])
                return JarvisResponse(
                    session_id="",
                    turn_id="",
                    text=f"Error: JARVIS returned {resp.status}",
                    status="failed",
                )
            data = await resp.json()

        text = data.get("final_response") or data.get("text")
        still_running = data.get("still_running", False)

        # If async mode and still running, poll for result
        if still_running and not text:
            turn_id = data.get("turn_id", "")
            text = await self._poll_turn(turn_id, timeout_seconds=30)

        return JarvisResponse(
            session_id=data.get("session_id", ""),
            turn_id=data.get("turn_id", ""),
            text=text,
            status=data.get("turn_status", "complete"),
            stream_url=data.get("stream_url"),
            still_running=still_running and not text,
        )

    async def _poll_turn(self, turn_id: str, timeout_seconds: float = 30) -> str | None:
        """Poll a turn until it completes or times out."""
        import asyncio

        session = await self._get_session()
        url = f"{self.base_url}/jarvis/v2/turns/{turn_id}"
        deadline = asyncio.get_event_loop().time() + timeout_seconds

        while asyncio.get_event_loop().time() < deadline:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await asyncio.sleep(0.5)
                    continue
                data = await resp.json()
                text = data.get("final_response")
                status = data.get("status", "")
                if text or status in ("COMPLETE", "FAILED", "CANCELLED"):
                    return text
            await asyncio.sleep(0.5)

        logger.warning("Turn %s poll timed out after %ss", turn_id, timeout_seconds)
        return None

    async def health(self) -> bool:
        """Check if JARVIS is healthy."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/jarvis/v1/health") as resp:
                return resp.status == 200
        except Exception:
            return False
