"""Tests for HA device lookup resolution (pure structures)."""

from __future__ import annotations

from zigbee_manager.device_registry import parse_bridge_devices
from zigbee_manager.ha_status import (
    LINK_FRIENDLY_NAME,
    LINK_IEEE,
    LINK_NONE,
    HaDeviceLookup,
    resolve_ha_device_id,
)

PLUG = {
    "ieee_address": "0x00158d00018255df",
    "type": "Router",
    "supported": True,
    "disabled": False,
    "friendly_name": "kitchen/plug",
    "definition": {"model": "ZNCZ02LM", "vendor": "Xiaomi"},
}


def test_resolve_by_ieee():
    dev = parse_bridge_devices([PLUG])["0x00158d00018255df"]
    lookup = HaDeviceLookup(
        by_ieee={"0x00158d00018255df": "device-abc"},
        by_friendly_name={},
    )
    device_id, method = resolve_ha_device_id(dev, lookup)
    assert device_id == "device-abc"
    assert method == LINK_IEEE


def test_resolve_by_friendly_name_with_slash():
    dev = parse_bridge_devices([PLUG])["0x00158d00018255df"]
    lookup = HaDeviceLookup(
        by_ieee={},
        by_friendly_name={"kitchen_plug": "device-xyz"},
    )
    device_id, method = resolve_ha_device_id(dev, lookup)
    assert device_id == "device-xyz"
    assert method == LINK_FRIENDLY_NAME


def test_resolve_not_found():
    dev = parse_bridge_devices([PLUG])["0x00158d00018255df"]
    lookup = HaDeviceLookup(by_ieee={}, by_friendly_name={})
    device_id, method = resolve_ha_device_id(dev, lookup)
    assert device_id is None
    assert method == LINK_NONE
