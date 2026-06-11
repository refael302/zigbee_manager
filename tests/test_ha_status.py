"""Tests for Z2M vs Home Assistant cross-check logic."""

from __future__ import annotations

from zigbee_manager.device_registry import (
    AVAILABILITY_OFFLINE,
    AVAILABILITY_ONLINE,
    DeviceState,
    parse_bridge_devices,
)
from zigbee_manager.ha_status import (
    MISMATCH_NONE,
    MISMATCH_NOT_IN_HA,
    MISMATCH_Z2M_OFFLINE_HA_ONLINE,
    MISMATCH_Z2M_ONLINE_HA_OFFLINE,
    classify_ha_mismatch,
    count_ha_active,
    device_ha_active_from_states,
    ieee_from_identifier_part,
    mismatch_description,
    normalize_ieee,
)

PLUG = {
    "ieee_address": "0x00158d00018255df",
    "type": "Router",
    "supported": True,
    "disabled": False,
    "friendly_name": "my_plug",
    "definition": {"model": "ZNCZ02LM", "vendor": "Xiaomi"},
}


def _plug() -> DeviceState:
    return parse_bridge_devices([PLUG])["0x00158d00018255df"]


def test_normalize_ieee():
    assert normalize_ieee("0xABCDEF") == "0xabcdef"
    assert normalize_ieee("zigbee2mqtt_0x00158d00018255df") == "0x00158d00018255df"


def test_ieee_from_identifier_part():
    assert ieee_from_identifier_part("0x00158d00018255df") == "0x00158d00018255df"
    assert ieee_from_identifier_part("zigbee2mqtt_0x00158d00018255df") == "0x00158d00018255df"


def test_device_ha_active_from_states():
    assert device_ha_active_from_states(["23.5", "unavailable"])
    assert not device_ha_active_from_states(["unavailable", "unknown"])
    assert not device_ha_active_from_states([])


def test_classify_mismatch_not_in_ha():
    dev = _plug()
    assert classify_ha_mismatch(dev, True) == MISMATCH_NOT_IN_HA


def test_classify_mismatch_z2m_online_ha_offline():
    dev = _plug()
    dev.ha_linked = True
    dev.ha_active = False
    dev.availability = AVAILABILITY_ONLINE
    assert classify_ha_mismatch(dev, True) == MISMATCH_Z2M_ONLINE_HA_OFFLINE


def test_classify_mismatch_z2m_offline_ha_online():
    dev = _plug()
    dev.ha_linked = True
    dev.ha_active = True
    dev.availability = AVAILABILITY_OFFLINE
    assert classify_ha_mismatch(dev, True) == MISMATCH_Z2M_OFFLINE_HA_ONLINE


def test_classify_no_mismatch_when_aligned():
    dev = _plug()
    dev.ha_linked = True
    dev.ha_active = True
    dev.availability = AVAILABILITY_ONLINE
    assert classify_ha_mismatch(dev, True) == MISMATCH_NONE


def test_bridge_offline_forces_z2m_inactive_for_mismatch():
    dev = _plug()
    dev.ha_linked = True
    dev.ha_active = True
    dev.availability = AVAILABILITY_ONLINE
    assert classify_ha_mismatch(dev, False) == MISMATCH_Z2M_OFFLINE_HA_ONLINE


def test_count_ha_active():
    devices = parse_bridge_devices([PLUG])
    d = devices["0x00158d00018255df"]
    d.ha_linked = True
    d.ha_active = True
    assert count_ha_active(devices) == (1, 1)


def test_mismatch_description_hebrew():
    dev = _plug()
    text = mismatch_description(dev, MISMATCH_Z2M_ONLINE_HA_OFFLINE)
    assert "חוסר התאמה" in text
    assert "my_plug" in text
