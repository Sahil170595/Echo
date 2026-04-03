"""Tests for the Telegram adapter."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from echo.telegram.app import _split_message, _parse_allowed_chats, handle_message


def test_split_message_short():
    assert _split_message("hello", 4096) == ["hello"]


def test_split_message_long():
    text = "line\n" * 1500
    chunks = _split_message(text, 4096)
    assert all(len(c) <= 4096 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_split_message_no_newlines():
    text = "x" * 8000
    chunks = _split_message(text, 4096)
    assert len(chunks) == 2
    assert chunks[0] == "x" * 4096
    assert chunks[1] == "x" * 3904


def test_parse_allowed_chats_empty():
    with patch.dict(os.environ, {}, clear=True):
        assert _parse_allowed_chats() is None


def test_parse_allowed_chats_valid():
    with patch.dict(os.environ, {"ECHO_TELEGRAM_ALLOWED_CHATS": "123, 456, 789"}):
        result = _parse_allowed_chats()
        assert result == {123, 456, 789}


def test_parse_allowed_chats_invalid():
    with patch.dict(os.environ, {"ECHO_TELEGRAM_ALLOWED_CHATS": "abc,def"}):
        result = _parse_allowed_chats()
        assert result is None


@pytest.mark.asyncio
async def test_handle_message_unauthorized_chat():
    """Messages from unauthorized chats are silently ignored."""
    from echo.shared.client import JarvisClient

    mock_jarvis = AsyncMock(spec=JarvisClient)

    mock_message = AsyncMock()
    mock_message.text = "hello"
    mock_message.chat_id = 99999
    mock_message.message_id = 1
    mock_message.from_user = MagicMock()
    mock_message.from_user.username = "testuser"
    mock_message.chat = AsyncMock()
    mock_message.reply_text = AsyncMock()

    mock_update = MagicMock()
    mock_update.message = mock_message

    mock_context = MagicMock()
    mock_context.bot_data = {
        "jarvis": mock_jarvis,
        "stream_client": AsyncMock(),
        "allowed_chats": {12345},  # Only this chat allowed
    }

    await handle_message(mock_update, mock_context)

    # JARVIS should NOT have been called
    mock_jarvis.chat.assert_not_called()
    mock_jarvis.chat_async.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_empty_text():
    """Empty messages are ignored."""
    mock_message = AsyncMock()
    mock_message.text = "   "
    mock_message.chat_id = 12345
    mock_message.from_user = MagicMock()

    mock_update = MagicMock()
    mock_update.message = mock_message

    mock_context = MagicMock()
    mock_context.bot_data = {
        "jarvis": AsyncMock(),
        "stream_client": AsyncMock(),
        "allowed_chats": None,
    }

    await handle_message(mock_update, mock_context)

    # No reply should be sent
    mock_message.reply_text.assert_not_called()
