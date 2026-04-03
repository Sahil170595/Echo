"""Tests for the WhatsApp adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from echo.whatsapp.app import WhatsAppAdapter, _split_message


def test_split_message_short():
    assert _split_message("hello") == ["hello"]


def test_split_message_long():
    text = "line\n" * 1500
    chunks = _split_message(text, 4096)
    assert all(len(c) <= 4096 for c in chunks)


def test_extract_messages_valid():
    adapter = WhatsAppAdapter(
        access_token="test",
        phone_number_id="123",
        verify_token="verify",
        jarvis=AsyncMock(),
    )

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [
                        {
                            "from": "15551234567",
                            "id": "msg_1",
                            "type": "text",
                            "text": {"body": "Hello JARVIS"},
                        },
                        {
                            "from": "15559876543",
                            "id": "msg_2",
                            "type": "image",
                            "image": {"id": "img_1"},
                        },
                    ]
                }
            }]
        }]
    }

    messages = adapter._extract_messages(payload)
    assert len(messages) == 1
    assert messages[0]["from"] == "15551234567"
    assert messages[0]["text"] == "Hello JARVIS"


def test_extract_messages_empty():
    adapter = WhatsAppAdapter(
        access_token="test",
        phone_number_id="123",
        verify_token="verify",
        jarvis=AsyncMock(),
    )
    assert adapter._extract_messages({}) == []
    assert adapter._extract_messages({"entry": []}) == []


@pytest.mark.asyncio
async def test_webhook_verify_success():
    from aiohttp.test_utils import make_mocked_request

    adapter = WhatsAppAdapter(
        access_token="test",
        phone_number_id="123",
        verify_token="my-secret",
        jarvis=AsyncMock(),
    )

    request = make_mocked_request(
        "GET",
        "/webhook?hub.mode=subscribe&hub.verify_token=my-secret&hub.challenge=challenge_123",
    )

    response = await adapter.handle_verify(request)
    assert response.status == 200
    assert response.text == "challenge_123"


@pytest.mark.asyncio
async def test_webhook_verify_failure():
    from aiohttp.test_utils import make_mocked_request

    adapter = WhatsAppAdapter(
        access_token="test",
        phone_number_id="123",
        verify_token="my-secret",
        jarvis=AsyncMock(),
    )

    request = make_mocked_request(
        "GET",
        "/webhook?hub.mode=subscribe&hub.verify_token=wrong-token&hub.challenge=challenge_123",
    )

    response = await adapter.handle_verify(request)
    assert response.status == 403


@pytest.mark.asyncio
async def test_process_message_access_control():
    from echo.shared.client import JarvisClient

    mock_jarvis = AsyncMock(spec=JarvisClient)

    adapter = WhatsAppAdapter(
        access_token="test",
        phone_number_id="123",
        verify_token="verify",
        jarvis=mock_jarvis,
        allowed_numbers={"15551111111"},
    )

    msg = {"from": "15559999999", "text": "hello", "id": "msg_1"}
    await adapter._process_message(msg)

    mock_jarvis.chat.assert_not_called()


@pytest.mark.asyncio
async def test_health_endpoint():
    from aiohttp.test_utils import make_mocked_request

    mock_jarvis = AsyncMock()
    mock_jarvis.health = AsyncMock(return_value=True)

    adapter = WhatsAppAdapter(
        access_token="test",
        phone_number_id="123",
        verify_token="verify",
        jarvis=mock_jarvis,
    )

    request = make_mocked_request("GET", "/health")
    response = await adapter.handle_health(request)
    assert response.status == 200
