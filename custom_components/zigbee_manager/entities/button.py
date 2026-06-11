"""Button entities for Zigbee Manager."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN, NAME
from ..coordinator import ZigbeeManagerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zigbee Manager buttons from a config entry."""
    coordinator: ZigbeeManagerCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities([ResetDeviceSnapshotButton(coordinator, entry)])


class ResetDeviceSnapshotButton(ButtonEntity):
    """Reset the persisted device baseline to the current Z2M registry."""

    _attr_has_entity_name = True
    _attr_name = "Reset device snapshot"
    _attr_translation_key = "reset_device_snapshot"
    _attr_icon = "mdi:backup-restore"

    def __init__(
        self, coordinator: ZigbeeManagerCoordinator, entry: ConfigEntry
    ) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_reset_device_snapshot"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or NAME,
            manufacturer=NAME,
        )

    async def async_press(self) -> None:
        """Align the stored baseline with the current live device list."""
        await self.coordinator.async_reset_device_snapshot()
