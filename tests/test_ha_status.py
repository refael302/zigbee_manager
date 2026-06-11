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
    MqttEntityStatus,
    classify_ha_mismatch,
    count_ha_active,
    device_ha_active_from_mqtt_entities,
    device_ha_active_from_states,
    friendly_name_lookup_keys,
    ieee_from_identifier_part,
    ieee_from_unique_id,
    mismatch_description,
    normalize_friendly_name,
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


def test_friendly_name_lookup_keys():
    keys = friendly_name_lookup_keys("Kitchen/Motion")
    assert "kitchen/motion" in keys
    assert "kitchen_motion" in keys


def test_ieee_from_unique_id():
    assert ieee_from_unique_id("0x00158d00018255df_temperature") == "0x00158d00018255df"
    assert ieee_from_unique_id("my_plug_battery") is None


def test_device_ha_active_from_mqtt_entities():
    assert device_ha_active_from_mqtt_entities(
        [MqttEntityStatus(disabled=False, state="23.5")]
    )
    assert not device_ha_active_from_mqtt_entities(
        [MqttEntityStatus(disabled=True, state="23.5")]
    )
    assert not device_ha_active_from_mqtt_entities(
        [
            MqttEntityStatus(disabled=False, state="unavailable"),
            MqttEntityStatus(disabled=True, state="100"),
        ]
    )
    assert device_ha_active_from_mqtt_entities(
        [
            MqttEntityStatus(disabled=False, state="unavailable"),
            MqttEntityStatus(disabled=False, state="on"),
        ]
    )


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


def test_mismatch_description_disabled_in_ha():
    dev = _plug()
    dev.ha_entity_count = 3
    dev.ha_disabled_count = 3
    text = mismatch_description(dev, MISMATCH_Z2M_ONLINE_HA_OFFLINE)
    assert "מושבתים" in text


def test_device_ha_active_from_states():
    assert device_ha_active_from_states(["23.5", "unavailable"])
    assert not device_ha_active_from_states(["unavailable", "unknown"])
