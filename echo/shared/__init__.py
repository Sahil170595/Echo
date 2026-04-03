"""Shared JARVIS client and utilities for all Echo adapters."""

from echo.shared.client import JarvisClient, JarvisResponse
from echo.shared.stream import JarvisStreamClient, StreamAccumulator, StreamEvent
from echo.shared.format import to_slack, to_discord, to_telegram, to_whatsapp, to_plain
from echo.shared.sessions import get_session, set_session

__all__ = [
    "JarvisClient",
    "JarvisResponse",
    "JarvisStreamClient",
    "StreamAccumulator",
    "StreamEvent",
    "to_slack",
    "to_discord",
    "to_telegram",
    "to_whatsapp",
    "to_plain",
    "get_session",
    "set_session",
]
