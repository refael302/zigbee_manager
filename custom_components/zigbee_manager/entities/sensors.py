"""Zigbee Manager sensors: device counts, registry and system log."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN, LOG_STATE_MAX_LEN, NAME, REGISTRY_ATTR_DEVICE_LIMIT
from ..coordinator import ZigbeeManagerCoordinator
from ..ha_status import MISMATCH_NONE, classify_ha_mismatch


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zigbee Manager sensors from a config entry."""
    coordinator: ZigbeeManagerCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities(
        [
            TotalDevicesSensor(coordinator, entry),
            SystemStatusSensor(coordinator, entry),
            ActiveDevicesSensor(coordinator, entry),
            ActiveDevicesHaSensor(coordinator, entry),
            DeviceRegistrySensor(coordinator, entry),
            SystemLogSensor(coordinator, entry),
        ]
    )


class ZigbeeManagerSensorBase(
    CoordinatorEntity[ZigbeeManagerCoordinator], SensorEntity
):
    """Base class for Zigbee Manager sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZigbeeManagerCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or NAME,
            manufacturer=NAME,
        )


class TotalDevicesSensor(ZigbeeManagerSensorBase):
    """Total number of devices in the Zigbee network (excluding the coordinator)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: ZigbeeManagerCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(
            coordinator, entry, "total_devices", "Total devices", "mdi:zigbee"
        )

    @property
    def native_value(self) -> int:
        return self.coordinator.total_devices

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "bridge_online": self.coordinator.bridge_online,
            "z2m_version": self.coordinator.bridge_info.get("version"),
        }


class SystemStatusSensor(ZigbeeManagerSensorBase):
    """Overall Zigbee network health (bridge + device MQTT activity)."""

    def __init__(
        self, coordinator: ZigbeeManagerCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            "system_status",
            "System status",
            "mdi:heart-pulse",
        )
        self._attr_translation_key = "system_status"

    @property
    def native_value(self) -> str:
        return str(
            self.coordinator.data.get("system_status_label") or "ממתין"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "status": data.get("system_status"),
            "bridge_online": data.get("bridge_online"),
            "startup_grace_active": data.get("startup_grace_active"),
            "last_device_activity_at": data.get("last_device_activity_at"),
            "seconds_since_device_activity": data.get(
                "seconds_since_device_activity"
            ),
            "network_stale_minutes": 10,
        }


class ActiveDevicesSensor(ZigbeeManagerSensorBase):
    """Number of devices currently active (not offline / disabled)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: ZigbeeManagerCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            "active_devices",
            "Active devices (Z2M)",
            "mdi:access-point",
        )

    @property
    def native_value(self) -> int:
        return self.coordinator.active_devices

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        total = self.coordinator.total_devices
        active = self.coordinator.active_devices
        offline = [
            dev.friendly_name
            for dev in self.coordinator.devices.values()
            if not dev.is_active
        ]
        ha_active = self.coordinator.ha_active_devices
        ha_linked = self.coordinator.ha_linked_devices
        return {
            "total": total,
            "offline_devices": offline,
            "ratio": round(active / total, 3) if total else None,
            "bridge_online": self.coordinator.bridge_online,
            "ha_active": ha_active,
            "ha_linked": ha_linked,
        }


class ActiveDevicesHaSensor(ZigbeeManagerSensorBase):
    """Devices with at least one available MQTT entity in Home Assistant."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: ZigbeeManagerCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            "active_devices_ha",
            "Active devices (HA)",
            "mdi:home-assistant",
        )

    @property
    def native_value(self) -> int:
        return self.coordinator.ha_active_devices

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        total = self.coordinator.total_devices
        linked = self.coordinator.ha_linked_devices
        not_linked = [
            dev.friendly_name
            for dev in self.coordinator.devices.values()
            if not dev.ha_linked and not dev.disabled
        ]
        ha_inactive = [
            dev.friendly_name
            for dev in self.coordinator.devices.values()
            if dev.ha_linked and not dev.ha_active
        ]
        mismatch = [
            dev.friendly_name
            for dev in self.coordinator.devices.values()
            if classify_ha_mismatch(dev, self.coordinator.bridge_online)
            != MISMATCH_NONE
        ]
        return {
            "z2m_total": total,
            "ha_linked": linked,
            "not_linked_in_ha": not_linked,
            "ha_inactive_devices": ha_inactive,
            "mismatch_devices": mismatch,
            "ratio": round(self.coordinator.ha_active_devices / linked, 3)
            if linked
            else None,
        }


class DeviceRegistrySensor(ZigbeeManagerSensorBase):
    """Full device list exposed as attributes, keyed by friendly name."""

    def __init__(
        self, coordinator: ZigbeeManagerCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            "device_registry",
            "Device registry",
            "mdi:format-list-bulleted",
        )

    @property
    def native_value(self) -> int:
        return self.coordinator.total_devices

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        devices = list(self.coordinator.devices.values())[:REGISTRY_ATTR_DEVICE_LIMIT]
        return {
            "devices": {dev.friendly_name: dev.as_attribute() for dev in devices},
            "truncated": len(self.coordinator.devices) > REGISTRY_ATTR_DEVICE_LIMIT,
        }


class SystemLogSensor(ZigbeeManagerSensorBase):
    """Latest integration alert line, with recent history in attributes."""

    def __init__(
        self, coordinator: ZigbeeManagerCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(
            coordinator, entry, "system_log", "System log", "mdi:text-box-outline"
        )

    @property
    def native_value(self) -> str | None:
        latest = self.coordinator.log.latest
        if latest is None:
            return None
        return str(latest["message"])[:LOG_STATE_MAX_LEN]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        latest = self.coordinator.log.latest or {}
        return {
            "level": latest.get("level"),
            "timestamp": latest.get("timestamp"),
            "event_type": latest.get("event_type"),
            "telegram_digest_pending": self.coordinator.data.get(
                "telegram_digest_pending", 0
            ),
            "startup_grace_active": self.coordinator.data.get(
                "startup_grace_active", False
            ),
            "device_snapshot_baseline": self.coordinator.data.get(
                "device_snapshot_baseline", 0
            ),
            "alerts": self.coordinator.log.entries(),
        }
