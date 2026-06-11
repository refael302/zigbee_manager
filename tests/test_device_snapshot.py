"""Tests for persisted device baseline / vanished detection."""

from __future__ import annotations

from zigbee_manager.device_snapshot import (
    filter_vanished_for_alert,
    find_vanished,
)


def test_find_vanished():
    baseline = {"0x1": "a", "0x2": "b", "0x3": "c"}
    current = {"0x1": "a", "0x3": "c"}
    assert find_vanished(baseline, current) == [("0x2", "b")]


def test_find_vanished_empty_when_all_present():
    baseline = {"0x1": "a"}
    current = {"0x1": "a", "0x2": "b"}
    assert find_vanished(baseline, current) == []


def test_filter_vanished_for_alert_skips_same_day():
    vanished = [("0x1", "a"), ("0x2", "b")]
    alerted = {"0x1": "2026-06-11"}
    result = filter_vanished_for_alert(vanished, alerted, "2026-06-11")
    assert result == [("0x2", "b")]


def test_filter_vanished_for_alert_allows_new_day():
    vanished = [("0x1", "a")]
    alerted = {"0x1": "2026-06-10"}
    result = filter_vanished_for_alert(vanished, alerted, "2026-06-11")
    assert result == [("0x1", "a")]
