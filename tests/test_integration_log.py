"""Tests for the in-memory log ring buffer."""

from __future__ import annotations

from zigbee_manager.integration_log import IntegrationLog


def test_add_and_latest():
    log = IntegrationLog()
    assert log.latest is None
    log.add("first", level="info", event_type="device_joined")
    log.add("second", level="warning")
    assert log.latest["message"] == "second"
    assert log.latest["level"] == "warning"


def test_entries_newest_first():
    log = IntegrationLog()
    log.add("a")
    log.add("b")
    log.add("c")
    assert [e["message"] for e in log.entries()] == ["c", "b", "a"]


def test_ring_buffer_caps_size():
    log = IntegrationLog(max_entries=3)
    for i in range(10):
        log.add(f"msg{i}")
    entries = log.entries()
    assert len(entries) == 3
    assert entries[0]["message"] == "msg9"


def test_entries_are_integration_only():
    log = IntegrationLog()
    log.add("alert", event_type="device_joined")
    for entry in log.entries():
        assert entry["source"] == "zigbee_manager"
