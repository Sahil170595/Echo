"""Tests for the shared JARVIS client."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from echo.shared.client import JarvisClient, JarvisResponse


@pytest.mark.asyncio
async def test_chat_sync_success():
    """Sync chat returns response directly."""
    client = JarvisClient(base_url="http://test:8400", device_key="test-key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "session_id": "sess_1",
        "turn_id": "turn_1",
        "final_response": "Hello from JARVIS!",
        "turn_status": "COMPLETE",
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.closed = False

    client._session = mock_session

    response = await client.chat("hello")
    assert response.text == "Hello from JARVIS!"
    assert response.session_id == "sess_1"
    assert response.turn_id == "turn_1"

    await client.close()


@pytest.mark.asyncio
async def test_chat_error_returns_error_response():
    """Non-200 response returns error JarvisResponse."""
    client = JarvisClient(base_url="http://test:8400", device_key="test-key")

    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="Internal Server Error")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.closed = False

    client._session = mock_session

    response = await client.chat("hello")
    assert "Error" in response.text
    assert response.status == "failed"

    await client.close()


@pytest.mark.asyncio
async def test_health_check():
    """Health check returns True on 200."""
    client = JarvisClient(base_url="http://test:8400", device_key="test-key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.closed = False

    client._session = mock_session

    assert await client.health() is True

    await client.close()


@pytest.mark.asyncio
async def test_health_check_failure():
    """Health check returns False on connection error."""
    client = JarvisClient(base_url="http://unreachable:9999", device_key="test-key")

    mock_session = AsyncMock()
    mock_session.get = MagicMock(side_effect=Exception("Connection refused"))
    mock_session.closed = False

    client._session = mock_session

    assert await client.health() is False

    await client.close()


def test_default_config():
    """Client uses default URL and empty device key."""
    client = JarvisClient()
    assert "localhost" in client.base_url or "8400" in client.base_url


def test_message_split():
    """Discord message splitting works correctly."""
    from echo.discord.app import _split_message

    # Short message — no split
    assert _split_message("hello", 2000) == ["hello"]

    # Long message — splits at newline
    text = "line1\n" * 500  # ~3000 chars
    chunks = _split_message(text, 2000)
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
