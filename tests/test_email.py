"""Tests for the Email adapter."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from echo.email.app import _get_config, _send_reply, _process_email


def test_get_config_missing_vars():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="Missing required env vars"):
            _get_config()


def test_get_config_valid():
    env = {
        "ECHO_EMAIL_IMAP_HOST": "imap.test.com",
        "ECHO_EMAIL_SMTP_HOST": "smtp.test.com",
        "ECHO_EMAIL_ADDRESS": "bot@test.com",
        "ECHO_EMAIL_PASSWORD": "secret",
        "ECHO_EMAIL_ALLOWED_SENDERS": "alice@test.com, bob@test.com",
        "ECHO_EMAIL_POLL_INTERVAL": "60",
    }
    with patch.dict(os.environ, env, clear=True):
        config = _get_config()
        assert config["imap_host"] == "imap.test.com"
        assert config["allowed_senders"] == {"alice@test.com", "bob@test.com"}
        assert config["poll_interval"] == 60


def test_get_config_no_allowed_senders():
    env = {
        "ECHO_EMAIL_IMAP_HOST": "imap.test.com",
        "ECHO_EMAIL_SMTP_HOST": "smtp.test.com",
        "ECHO_EMAIL_ADDRESS": "bot@test.com",
        "ECHO_EMAIL_PASSWORD": "secret",
    }
    with patch.dict(os.environ, env, clear=True):
        config = _get_config()
        assert config["allowed_senders"] is None


@pytest.mark.asyncio
async def test_process_email_access_control():
    from echo.shared.client import JarvisClient

    mock_jarvis = AsyncMock(spec=JarvisClient)

    config = {
        "allowed_senders": {"allowed@test.com"},
        "smtp_host": "smtp.test.com",
        "smtp_port": 587,
        "address": "bot@test.com",
        "password": "secret",
    }

    msg = {
        "from": "unauthorized@test.com",
        "subject": "Hello",
        "body": "Test message",
        "message_id": "<msg1@test.com>",
    }

    await _process_email(mock_jarvis, config, msg)
    mock_jarvis.chat.assert_not_called()


@pytest.mark.asyncio
async def test_process_email_forwards_to_jarvis():
    from echo.shared.client import JarvisClient, JarvisResponse

    mock_jarvis = AsyncMock(spec=JarvisClient)
    mock_jarvis.chat = AsyncMock(return_value=JarvisResponse(
        session_id="sess_1",
        turn_id="turn_1",
        text="Hello from JARVIS!",
        status="COMPLETE",
    ))

    config = {
        "allowed_senders": None,
        "smtp_host": "smtp.test.com",
        "smtp_port": 587,
        "address": "bot@test.com",
        "password": "secret",
    }

    msg = {
        "from": "user@test.com",
        "subject": "Hello",
        "body": "What's the weather?",
        "message_id": "<msg2@test.com>",
    }

    with patch("echo.email.app._send_reply") as mock_send:
        await _process_email(mock_jarvis, config, msg)

    mock_jarvis.chat.assert_called_once()
    call_kwargs = mock_jarvis.chat.call_args
    assert call_kwargs.kwargs["message"] == "What's the weather?"


def test_send_reply_constructs_email():
    config = {
        "smtp_host": "smtp.test.com",
        "smtp_port": 587,
        "address": "bot@test.com",
        "password": "secret",
    }

    with patch("echo.email.app.smtplib.SMTP") as mock_smtp_class:
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        _send_reply(config, "user@test.com", "Hello", "Reply body", "<msg@test.com>")

        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("bot@test.com", "secret")
        mock_smtp.send_message.assert_called_once()

        sent_msg = mock_smtp.send_message.call_args[0][0]
        assert sent_msg["To"] == "user@test.com"
        assert sent_msg["Subject"] == "Re: Hello"
        assert sent_msg["In-Reply-To"] == "<msg@test.com>"
