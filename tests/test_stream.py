"""Tests for the streaming client and accumulator."""

from __future__ import annotations

import time

import pytest

from echo.shared.stream import StreamAccumulator, StreamEvent


class TestStreamEvent:
    def test_from_wire_delta(self):
        data = {
            "type": "assistant.delta",
            "turn_id": "turn_1",
            "session_id": "sess_1",
            "seq": 5,
            "timestamp": "2026-01-01T00:00:00Z",
            "delta": "Hello ",
            "payload": {"delta": "Hello "},
        }
        event = StreamEvent.from_wire(data)
        assert event.type == "assistant.delta"
        assert event.delta == "Hello "
        assert event.turn_id == "turn_1"
        assert event.seq == 5

    def test_from_wire_final(self):
        data = {
            "type": "assistant.final",
            "turn_id": "turn_1",
            "session_id": "sess_1",
            "seq": 10,
            "timestamp": "2026-01-01T00:00:01Z",
            "final_response": "Hello world!",
            "payload": {},
        }
        event = StreamEvent.from_wire(data)
        assert event.type == "assistant.final"
        assert event.text == "Hello world!"

    def test_from_wire_minimal(self):
        event = StreamEvent.from_wire({})
        assert event.type == ""
        assert event.delta is None
        assert event.text is None
        assert event.seq == 0


class TestStreamAccumulator:
    def test_feed_accumulates(self):
        acc = StreamAccumulator()
        acc.feed("Hello ")
        acc.feed("world!")
        assert acc.full_text == "Hello world!"

    def test_should_flush_respects_throttle(self):
        acc = StreamAccumulator(throttle_seconds=0.1)
        acc.feed("a")
        # First flush is always ready (last_flush is 0)
        assert acc.should_flush()

        acc.flush()
        acc.feed("b")
        # Immediately after flush, should NOT flush
        assert not acc.should_flush()

        # After throttle period
        time.sleep(0.15)
        assert acc.should_flush()

    def test_flush_returns_full_text(self):
        acc = StreamAccumulator()
        acc.feed("Hello ")
        acc.feed("world!")
        result = acc.flush()
        assert result == "Hello world!"

    def test_flush_resets_pending(self):
        acc = StreamAccumulator(throttle_seconds=0)
        acc.feed("a")
        acc.flush()
        assert not acc.has_pending

        acc.feed("b")
        assert acc.has_pending

    def test_empty_no_flush(self):
        acc = StreamAccumulator()
        assert not acc.should_flush()
        assert not acc.has_pending

    def test_full_text_grows_across_flushes(self):
        acc = StreamAccumulator(throttle_seconds=0)
        acc.feed("Hello ")
        first = acc.flush()
        assert first == "Hello "

        acc.feed("world!")
        second = acc.flush()
        assert second == "Hello world!"
