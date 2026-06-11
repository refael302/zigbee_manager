"""Tests for bridge/devices parsing and snapshot diffing."""

from __future__ import annotations

from datetime import datetime, timezone

from zigbee_manager.device_registry import (
    AVAILABILITY_OFFLINE,
    AVAILABILITY_ONLINE,
    count_active_devices,
    diff_devices,
    mark_all_offline,
    merge_runtime_state,
    parse_bridge_devices,
)

PLUG = {
    "ieee_address": "0x00158d00018255df",
    "type": "Router",
    "supported": True,
    "disabled": False,
    "friendly_name": "my_plug",
    "definition": {"model": "ZNCZ02LM", "vendor": "Xiaomi"},
    "power_source": "Mains (single phase)",
    "interview_state": "SUCCESSFUL",
}

SENSOR = {
    "ieee_address": "0x00169a00022256da",
    "type": "EndDevice",
    "supported": False,
    "disabled": False,
    "friendly_name": "my_sensor",
    "definition": None,
    "power_source": "Battery",
    "interview_completed": True,
}

COORDINATOR = {
    "ieee_address": "0x00124b00120144ae",
    "type": "Coordinator",
    "friendly_name": "Coordinator",
    "definition": None,
}


def test_parse_excludes_coordinator():
    devices = parse_bridge_devices([PLUG, SENSOR, COORDINATOR])
    assert len(devices) == 2
    assert "0x00124b00120144ae" not in devices


def test_parse_device_fields():
    devices = parse_bridge_devices([PLUG, SENSOR])
    plug = devices["0x00158d00018255df"]
    assert plug.friendly_name == "my_plug"
    assert plug.vendor == "Xiaomi"
    assert plug.model == "ZNCZ02LM"
    assert plug.device_type == "Router"
    assert plug.supported is True
    sensor = devices["0x00169a00022256da"]
    assert sensor.vendor is None
    assert sensor.interview_state == "SUCCESSFUL"  # via interview_completed fallback


def test_diff_join_and_remove():
    old = parse_bridge_devices([PLUG])
    new = parse_bridge_devices([SENSOR])
    joined, removed = diff_devices(old, new)
    assert [d.ieee_address for d in joined] == ["0x00169a00022256da"]
    assert [d.ieee_address for d in removed] == ["0x00158d00018255df"]


def test_diff_no_changes():
    old = parse_bridge_devices([PLUG, SENSOR])
    new = parse_bridge_devices([PLUG, SENSOR])
    joined, removed = diff_devices(old, new)
    assert joined == [] and removed == []


def test_merge_runtime_state_preserves_availability_and_last_seen():
    old = parse_bridge_devices([PLUG])
    seen = datetime(2026, 6, 1, tzinfo=timezone.utc)
    old["0x00158d00018255df"].availability = AVAILABILITY_OFFLINE
    old["0x00158d00018255df"].last_seen = seen
    old["0x00158d00018255df"].silent_alerted = True

    new = parse_bridge_devices([PLUG, SENSOR])
    merge_runtime_state(old, new)
    carried = new["0x00158d00018255df"]
    assert carried.availability == AVAILABILITY_OFFLINE
    assert carried.last_seen == seen
    assert carried.silent_alerted is True
    # New device keeps defaults
    assert new["0x00169a00022256da"].availability == "unknown"


def test_is_active():
    devices = parse_bridge_devices([PLUG])
    dev = devices["0x00158d00018255df"]
    assert dev.is_active  # unknown availability counts as active
    dev.availability = AVAILABILITY_OFFLINE
    assert not dev.is_active
    dev.availability = AVAILABILITY_ONLINE
    assert dev.is_active
    dev.disabled = True
    assert not dev.is_active


def test_mark_all_offline():
    devices = parse_bridge_devices([PLUG, SENSOR])
    devices["0x00158d00018255df"].availability = AVAILABILITY_ONLINE
    mark_all_offline(devices)
    assert devices["0x00158d00018255df"].availability == AVAILABILITY_OFFLINE
    assert devices["0x00169a00022256da"].availability == AVAILABILITY_OFFLINE


def test_count_active_devices_zero_when_bridge_offline():
    devices = parse_bridge_devices([PLUG, SENSOR])
    for dev in devices.values():
        dev.availability = AVAILABILITY_ONLINE
    assert count_active_devices(devices, bridge_online=True) == 2
    assert count_active_devices(devices, bridge_online=False) == 0
    assert count_active_devices(devices, bridge_online=None) == 2
