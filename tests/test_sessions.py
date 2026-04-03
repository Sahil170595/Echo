"""Tests for persistent session store."""

from __future__ import annotations

import os
import tempfile
import time
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Use a temp database for each test."""
    db_path = str(tmp_path / "test_sessions.db")
    with patch.dict(os.environ, {"ECHO_SESSIONS_DB": db_path}):
        # Force re-creation of thread-local connection
        import echo.shared.sessions as mod
        if hasattr(mod._local, "conn"):
            del mod._local.conn
        yield db_path
        if hasattr(mod._local, "conn") and mod._local.conn:
            mod._local.conn.close()
            del mod._local.conn


def test_get_set_session():
    from echo.shared.sessions import get_session, set_session
    assert get_session("slack", "C123") is None

    set_session("slack", "C123", "sess_abc")
    assert get_session("slack", "C123") == "sess_abc"


def test_update_session():
    from echo.shared.sessions import get_session, set_session
    set_session("slack", "C123", "sess_1")
    set_session("slack", "C123", "sess_2")
    assert get_session("slack", "C123") == "sess_2"


def test_platform_isolation():
    from echo.shared.sessions import get_session, set_session
    set_session("slack", "C123", "slack_sess")
    set_session("discord", "C123", "discord_sess")

    assert get_session("slack", "C123") == "slack_sess"
    assert get_session("discord", "C123") == "discord_sess"


def test_expired_session_returns_none():
    from echo.shared.sessions import get_session, set_session, _get_conn, SESSION_TTL_SECONDS

    set_session("slack", "C123", "old_sess")

    # Manually backdate the updated_at
    conn = _get_conn()
    old_time = time.time() - SESSION_TTL_SECONDS - 1
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE platform = ? AND channel_id = ?",
        (old_time, "slack", "C123"),
    )
    conn.commit()

    assert get_session("slack", "C123") is None


def test_cleanup_expired():
    from echo.shared.sessions import set_session, cleanup_expired, _get_conn, SESSION_TTL_SECONDS

    set_session("slack", "old", "sess_old")
    set_session("slack", "new", "sess_new")

    # Backdate one
    conn = _get_conn()
    old_time = time.time() - SESSION_TTL_SECONDS - 1
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE channel_id = ?",
        (old_time, "old"),
    )
    conn.commit()

    count = cleanup_expired()
    assert count == 1

    from echo.shared.sessions import get_session
    assert get_session("slack", "old") is None
    assert get_session("slack", "new") == "sess_new"
