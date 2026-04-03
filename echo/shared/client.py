"""HTTP client for the JARVIS AI gateway.

All Echo adapters use this client to send messages and receive responses.
Authentication is via device key (X-Jarvis-Device-Key header).

Includes retry with exponential backoff for transient failures.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Retry config
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.5  # seconds, doubles each retry
RETRIABLE_STATUS_CODES = {502, 503, 504, 429}


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
    """Async HTTP client for JARVIS v2 API with retry."""

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

        Retries on 502/503/504/429 with exponential backoff.

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
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._parse_response(data)

                    body = await resp.text()

                    if resp.status in RETRIABLE_STATUS_CODES and attempt < MAX_RETRIES - 1:
                        delay = RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            "JARVIS returned %d, retrying in %.1fs (attempt %d/%d): %s",
                            resp.status, delay, attempt + 1, MAX_RETRIES, body[:200],
                        )
                        await asyncio.sleep(delay)
                        continue

                    logger.warning("JARVIS chat failed: %s %s", resp.status, body[:200])
                    return JarvisResponse(
                        session_id="",
                        turn_id="",
                        text=f"Error: JARVIS returned {resp.status}",
                        status="failed",
                    )

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "JARVIS connection failed, retrying in %.1fs (attempt %d/%d): %s",
                        delay, attempt + 1, MAX_RETRIES, exc,
                    )
                    await asyncio.sleep(delay)
                    continue

        logger.error("JARVIS chat failed after %d attempts: %s", MAX_RETRIES, last_error)
        return JarvisResponse(
            session_id="",
            turn_id="",
            text="Error: could not reach JARVIS",
            status="failed",
        )

    async def chat_async(
        self,
        message: str,
        *,
        session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> JarvisResponse:
        """Send a chat message in async mode (returns immediately with turn_id).

        Use this with JarvisStreamClient to get streamed responses.
        """
        return await self.chat(
            message,
            session_id=session_id,
            idempotency_key=idempotency_key,
            mode="async",
            wait_ms=0,
        )

    def _parse_response(self, data: dict) -> JarvisResponse:
        """Parse JARVIS JSON response into JarvisResponse."""
        text = data.get("final_response") or data.get("text")
        return JarvisResponse(
            session_id=data.get("session_id", ""),
            turn_id=data.get("turn_id", ""),
            text=text,
            status=data.get("turn_status", "complete"),
            stream_url=data.get("stream_url"),
            still_running=data.get("still_running", False),
        )

    async def poll_turn(self, turn_id: str, timeout_seconds: float = 30) -> str | None:
        """Poll a turn until it completes or times out."""
        session = await self._get_session()
        url = f"{self.base_url}/jarvis/v2/turns/{turn_id}"
        deadline = asyncio.get_event_loop().time() + timeout_seconds

        while asyncio.get_event_loop().time() < deadline:
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await asyncio.sleep(0.5)
                        continue
                    data = await resp.json()
                    text = data.get("final_response")
                    status = data.get("status", "")
                    if text or status in ("COMPLETE", "FAILED", "CANCELLED"):
                        return text
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
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
