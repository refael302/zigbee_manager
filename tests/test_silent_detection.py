"""Tests for last_seen parsing used by the silent-device detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from zigbee_manager.device_registry import parse_last_seen


def test_parse_iso_8601_utc():
    parsed = parse_last_seen("2026-06-11T10:00:00Z")
    assert parsed == datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc)


def test_parse_iso_8601_with_offset():
    parsed = parse_last_seen("2026-06-11T13:00:00+03:00")
    assert parsed == datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc)


def test_parse_iso_8601_naive_assumed_utc():
    parsed = parse_last_seen("2026-06-11T10:00:00")
    assert parsed is not None
    assert parsed.tzinfo is not None


def test_parse_epoch_milliseconds():
    epoch_ms = 1_780_000_000_000
    parsed = parse_last_seen(epoch_ms)
    assert parsed == datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)


def test_parse_invalid_values():
    assert parse_last_seen(None) is None
    assert parse_last_seen("not-a-date") is None
    assert parse_last_seen({"nested": 1}) is None


def test_silent_threshold_comparison():
    """A device whose last_seen is older than the threshold is considered silent."""
    threshold = timedelta(hours=24)
    now = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
    fresh = parse_last_seen("2026-06-11T10:00:00Z")
    stale = parse_last_seen("2026-06-09T10:00:00Z")
    assert now - fresh <= threshold
    assert now - stale > threshold
