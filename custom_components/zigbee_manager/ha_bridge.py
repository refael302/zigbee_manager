"""Link Z2M devices to Home Assistant MQTT devices via the device registry."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .device_registry import DeviceState
from .ha_status import (
    device_ha_active_from_states,
    ieee_from_identifier_part,
    normalize_ieee,
)

_LOGGER = logging.getLogger(__name__)


def build_ieee_to_ha_device_map(hass: HomeAssistant) -> dict[str, str]:
    """Map normalized IEEE address -> HA device registry id."""
    dev_reg = dr.async_get(hass)
    ieee_map: dict[str, str] = {}
    for device in dev_reg.devices.values():
        ieee: str | None = None
        for id_tuple in device.identifiers:
            for part in id_tuple:
                ieee = ieee_from_identifier_part(part)
                if ieee:
                    break
            if ieee:
                break
        if ieee is None:
            for conn in device.connections:
                if conn[0] == "zigbee":
                    ieee = normalize_ieee(str(conn[1]))
                    break
        if ieee:
            ieee_map.setdefault(ieee, device.id)
    return ieee_map


def _mqtt_entity_states(hass: HomeAssistant, device_id: str) -> list[str | None]:
    """Collect states of non-disabled MQTT entities for a HA device."""
    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_device(
        ent_reg, device_id, include_disabled_entity=False
    )
    states: list[str | None] = []
    for entry in entities:
        if entry.platform != "mqtt":
            continue
        state_obj = hass.states.get(entry.entity_id)
        states.append(state_obj.state if state_obj is not None else None)
    return states


def apply_ha_status_to_device(hass: HomeAssistant, dev: DeviceState) -> None:
    """Refresh ha_linked / ha_active / ha_entity_count on a DeviceState."""
    ieee = normalize_ieee(dev.ieee_address)
    ieee_map = build_ieee_to_ha_device_map(hass)
    device_id = ieee_map.get(ieee)
    if device_id is None:
        dev.ha_linked = False
        dev.ha_active = False
        dev.ha_entity_count = 0
        return
    states = _mqtt_entity_states(hass, device_id)
    dev.ha_linked = True
    dev.ha_entity_count = len(states)
    dev.ha_active = device_ha_active_from_states(states)


def refresh_all_ha_status(hass: HomeAssistant, devices: dict[str, DeviceState]) -> None:
    """Refresh HA link status for every tracked Z2M device."""
    ieee_map = build_ieee_to_ha_device_map(hass)
    ent_reg = er.async_get(hass)
    for dev in devices.values():
        ieee = normalize_ieee(dev.ieee_address)
        device_id = ieee_map.get(ieee)
        if device_id is None:
            dev.ha_linked = False
            dev.ha_active = False
            dev.ha_entity_count = 0
            continue
        entities = er.async_entries_for_device(
            ent_reg, device_id, include_disabled_entity=False
        )
        mqtt_entities = [e for e in entities if e.platform == "mqtt"]
        states: list[str | None] = []
        for entry in mqtt_entities:
            state_obj = hass.states.get(entry.entity_id)
            states.append(state_obj.state if state_obj is not None else None)
        dev.ha_linked = True
        dev.ha_entity_count = len(mqtt_entities)
        dev.ha_active = device_ha_active_from_states(states)


def collect_mqtt_entity_ids(hass: HomeAssistant, devices: dict[str, DeviceState]) -> list[str]:
    """MQTT entity ids linked to the given Z2M devices (for state listeners)."""
    ieee_map = build_ieee_to_ha_device_map(hass)
    ent_reg = er.async_get(hass)
    entity_ids: list[str] = []
    seen: set[str] = set()
    for dev in devices.values():
        device_id = ieee_map.get(normalize_ieee(dev.ieee_address))
        if device_id is None:
            continue
        for entry in er.async_entries_for_device(
            ent_reg, device_id, include_disabled_entity=False
        ):
            if entry.platform != "mqtt" or entry.entity_id in seen:
                continue
            seen.add(entry.entity_id)
            entity_ids.append(entry.entity_id)
    return entity_ids


class HaStateTracker:
    """Tracks MQTT entity state changes and invokes a callback."""

    def __init__(self, hass: HomeAssistant, on_change: Any) -> None:
        self._hass = hass
        self._on_change = on_change
        self._unsub = None
        self._entity_ids: list[str] = []

    def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def async_refresh_listeners(self, entity_ids: list[str]) -> None:
        """Re-subscribe when the linked MQTT entity set changes."""
        if entity_ids == self._entity_ids and self._unsub:
            return
        self.async_stop()
        self._entity_ids = list(entity_ids)
        if not entity_ids:
            return

        @callback
        def _state_changed(_event: Any) -> None:
            self._hass.async_create_task(self._on_change())

        self._unsub = async_track_state_change_event(
            self._hass, entity_ids, _state_changed
        )
        _LOGGER.debug(
            "Zigbee Manager: tracking %d MQTT entities for HA status",
            len(entity_ids),
        )
