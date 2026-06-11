"""Link Z2M devices to Home Assistant MQTT devices via the device registry."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_entity_registry_updated_event,
    async_track_state_change_event,
)

from .device_registry import DeviceState
from .ha_status import (
    HaDeviceLookup,
    MqttEntityStatus,
    device_ha_active_from_mqtt_entities,
    friendly_name_lookup_keys,
    ieee_from_identifier_part,
    ieee_from_unique_id,
    normalize_ieee,
    resolve_ha_device_id,
)

_LOGGER = logging.getLogger(__name__)

MQTT_PLATFORMS = frozenset({"mqtt"})


def build_ha_device_lookup(hass: HomeAssistant) -> HaDeviceLookup:
    """Build lookup tables from the HA device and entity registries."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    by_ieee: dict[str, str] = {}
    by_friendly_name: dict[str, str] = {}

    for device in dev_reg.devices.values():
        ieee: str | None = None
        for id_tuple in device.identifiers:
            for part in id_tuple:
                found = ieee_from_identifier_part(part)
                if found:
                    ieee = found
                    break
            if ieee:
                break
            if len(id_tuple) == 2 and id_tuple[0] in ("zigbee2mqtt", "mqtt"):
                name_part = str(id_tuple[1])
                if not ieee_from_identifier_part(name_part):
                    for key in friendly_name_lookup_keys(name_part):
                        by_friendly_name.setdefault(key, device.id)

        if ieee is None:
            for conn in device.connections:
                if conn[0] == "zigbee":
                    ieee = normalize_ieee(str(conn[1]))
                    break

        if ieee:
            by_ieee.setdefault(ieee, device.id)

        for name in (device.name_by_user, device.name):
            if name:
                for key in friendly_name_lookup_keys(name):
                    by_friendly_name.setdefault(key, device.id)

    for entry in ent_reg.entities.values():
        if entry.platform not in MQTT_PLATFORMS or not entry.device_id:
            continue
        ieee = ieee_from_unique_id(entry.unique_id)
        if ieee:
            by_ieee.setdefault(ieee, entry.device_id)

    return HaDeviceLookup(by_ieee=by_ieee, by_friendly_name=by_friendly_name)


def _mqtt_entity_statuses(
    hass: HomeAssistant, device_id: str
) -> list[MqttEntityStatus]:
    """Collect MQTT entity disabled/state info (includes disabled entities)."""
    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_device(
        ent_reg, device_id, include_disabled_entity=True
    )
    statuses: list[MqttEntityStatus] = []
    for entry in entities:
        if entry.platform not in MQTT_PLATFORMS:
            continue
        state_obj = hass.states.get(entry.entity_id)
        statuses.append(
            MqttEntityStatus(
                disabled=entry.disabled_by is not None,
                state=state_obj.state if state_obj is not None else None,
            )
        )
    return statuses


def apply_ha_status_to_device(
    hass: HomeAssistant, dev: DeviceState, lookup: HaDeviceLookup | None = None
) -> None:
    """Refresh HA link/active fields on a DeviceState."""
    lookup = lookup or build_ha_device_lookup(hass)
    device_id, link_method = resolve_ha_device_id(dev, lookup)
    dev.ha_link_method = link_method
    if device_id is None:
        dev.ha_linked = False
        dev.ha_active = False
        dev.ha_entity_count = 0
        dev.ha_disabled_count = 0
        return

    statuses = _mqtt_entity_statuses(hass, device_id)
    dev.ha_linked = True
    dev.ha_entity_count = len(statuses)
    dev.ha_disabled_count = sum(1 for s in statuses if s.disabled)
    dev.ha_active = device_ha_active_from_mqtt_entities(statuses)


def refresh_all_ha_status(hass: HomeAssistant, devices: dict[str, DeviceState]) -> None:
    """Refresh HA link status for every tracked Z2M device."""
    lookup = build_ha_device_lookup(hass)
    for dev in devices.values():
        apply_ha_status_to_device(hass, dev, lookup)


def collect_mqtt_entity_ids(
    hass: HomeAssistant, devices: dict[str, DeviceState]
) -> list[str]:
    """MQTT entity ids linked to Z2M devices (includes disabled, for registry events)."""
    lookup = build_ha_device_lookup(hass)
    ent_reg = er.async_get(hass)
    entity_ids: list[str] = []
    seen: set[str] = set()
    for dev in devices.values():
        device_id, _method = resolve_ha_device_id(dev, lookup)
        if device_id is None:
            continue
        for entry in er.async_entries_for_device(
            ent_reg, device_id, include_disabled_entity=True
        ):
            if entry.platform not in MQTT_PLATFORMS or entry.entity_id in seen:
                continue
            seen.add(entry.entity_id)
            entity_ids.append(entry.entity_id)
    return entity_ids


class HaStateTracker:
    """Tracks MQTT entity state + registry changes and invokes a callback."""

    def __init__(self, hass: HomeAssistant, on_change: Any) -> None:
        self._hass = hass
        self._on_change = on_change
        self._unsub_state = None
        self._unsub_registry = None
        self._entity_ids: list[str] = []

    def async_stop(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_registry:
            self._unsub_registry()
            self._unsub_registry = None

    def async_refresh_listeners(self, entity_ids: list[str]) -> None:
        """Re-subscribe when the linked MQTT entity set changes."""
        if entity_ids == self._entity_ids and self._unsub_state:
            return
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

        self._entity_ids = list(entity_ids)

        if entity_ids:

            @callback
            def _state_changed(_event: Any) -> None:
                self._hass.async_create_task(self._on_change())

            self._unsub_state = async_track_state_change_event(
                self._hass, entity_ids, _state_changed
            )
            _LOGGER.debug(
                "Zigbee Manager: tracking %d MQTT entity states",
                len(entity_ids),
            )

        if self._unsub_registry is None:

            @callback
            def _registry_updated(_event: Any) -> None:
                self._hass.async_create_task(self._on_change())

            self._unsub_registry = async_track_entity_registry_updated_event(
                self._hass, _registry_updated
            )
