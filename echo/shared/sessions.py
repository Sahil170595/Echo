"""Persistent session store backed by SQLite.

Survives container restarts. Each adapter maps its platform-specific
channel/chat/sender ID to a JARVIS session_id so conversation context
is preserved across deploys.

Storage location: ECHO_SESSIONS_DB env var, default ./echo_sessions.db
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

_DB_PATH = os.environ.get("ECHO_SESSIONS_DB", "echo_sessions.db")

# Module-level connection (one per thread via threading.local)
_local = threading.local()

# Sessions older than this are considered stale (7 days)
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


def _get_conn() -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(_DB_PATH)
        _local.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                platform TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (platform, channel_id)
            )
        """)
        _local.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_updated
            ON sessions(updated_at)
        """)
        _local.conn.commit()
    return _local.conn


def get_session(platform: str, channel_id: str) -> str | None:
    """Look up JARVIS session_id for a platform channel.

    Returns None if no session exists or it's expired.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT session_id, updated_at FROM sessions WHERE platform = ? AND channel_id = ?",
        (platform, str(channel_id)),
    ).fetchone()

    if row is None:
        return None

    session_id, updated_at = row
    if (time.time() - updated_at) > SESSION_TTL_SECONDS:
        # Expired — clean it up
        conn.execute(
            "DELETE FROM sessions WHERE platform = ? AND channel_id = ?",
            (platform, str(channel_id)),
        )
        conn.commit()
        return None

    return session_id


def set_session(platform: str, channel_id: str, session_id: str) -> None:
    """Store or update a JARVIS session_id for a platform channel."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO sessions (platform, channel_id, session_id, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(platform, channel_id)
           DO UPDATE SET session_id = excluded.session_id, updated_at = excluded.updated_at""",
        (platform, str(channel_id), session_id, time.time()),
    )
    conn.commit()


def cleanup_expired() -> int:
    """Delete sessions older than SESSION_TTL_SECONDS. Returns count deleted."""
    conn = _get_conn()
    cutoff = time.time() - SESSION_TTL_SECONDS
    cursor = conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
    conn.commit()
    count = cursor.rowcount
    if count:
        logger.info("Cleaned up %d expired sessions", count)
    return count
