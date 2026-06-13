"""Tests for system-wide status computation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from zigbee_manager.system_status import (
    SYSTEM_STATUS_BRIDGE_OFFLINE,
    SYSTEM_STATUS_NETWORK_STALE,
    SYSTEM_STATUS_OK,
    SYSTEM_STATUS_STARTUP_GRACE,
    compute_system_status,
    system_status_label,
)


def _now() -> datetime:
    return datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


def test_ok_when_recent_activity():
    now = _now()
    status, _details = compute_system_status(
        bridge_online=True,
        startup_grace=False,
        devices_received=True,
        last_device_activity_at=now - timedelta(minutes=5),
        stale_after=timedelta(minutes=10),
        now=now,
    )
    assert status == SYSTEM_STATUS_OK


def test_network_stale():
    now = _now()
    status, details = compute_system_status(
        bridge_online=True,
        startup_grace=False,
        devices_received=True,
        last_device_activity_at=now - timedelta(minutes=15),
        stale_after=timedelta(minutes=10),
        now=now,
    )
    assert status == SYSTEM_STATUS_NETWORK_STALE
    assert details["stale_minutes"] == 10


def test_startup_grace_takes_priority():
    now = _now()
    status, _ = compute_system_status(
        bridge_online=True,
        startup_grace=True,
        devices_received=False,
        last_device_activity_at=None,
        stale_after=timedelta(minutes=10),
        now=now,
    )
    assert status == SYSTEM_STATUS_STARTUP_GRACE


def test_bridge_offline():
    now = _now()
    status, _ = compute_system_status(
        bridge_online=False,
        startup_grace=False,
        devices_received=True,
        last_device_activity_at=now - timedelta(minutes=15),
        stale_after=timedelta(minutes=10),
        now=now,
    )
    assert status == SYSTEM_STATUS_BRIDGE_OFFLINE


def test_status_label_stale():
    label = system_status_label(
        SYSTEM_STATUS_NETWORK_STALE, {"stale_minutes": 10}
    )
    assert "10 דק" in label
