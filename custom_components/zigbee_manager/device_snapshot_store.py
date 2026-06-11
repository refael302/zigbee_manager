"""HA Store wrapper for the persisted device baseline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.storage import Store

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1
STORAGE_KEY = "device_snapshot"


class DeviceSnapshotStore:
    """HA-backed store of the last known device list and vanished-alert dates."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.{STORAGE_KEY}",
        )
        self._devices: dict[str, str] = {}
        self._vanished_alerted: dict[str, str] = {}

    @property
    def baseline(self) -> dict[str, str]:
        return dict(self._devices)

    @property
    def baseline_count(self) -> int:
        return len(self._devices)

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if not isinstance(data, dict):
            return
        devices = data.get("devices")
        if isinstance(devices, dict):
            self._devices = {str(k): str(v) for k, v in devices.items()}
        alerted = data.get("vanished_alerted")
        if isinstance(alerted, dict):
            self._vanished_alerted = {str(k): str(v) for k, v in alerted.items()}

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "devices": self._devices,
                "vanished_alerted": self._vanished_alerted,
            }
        )

    def set_baseline(self, devices: dict[str, str]) -> None:
        self._devices = dict(devices)

    def add_device(self, ieee: str, friendly_name: str) -> None:
        self._devices[ieee] = friendly_name

    def remove_device(self, ieee: str) -> None:
        self._devices.pop(ieee, None)
        self._vanished_alerted.pop(ieee, None)

    def clear_vanished_alerted(self) -> None:
        self._vanished_alerted.clear()

    def mark_vanished_alerted(self, ieee: str, day: str) -> None:
        self._vanished_alerted[ieee] = day

    @property
    def vanished_alerted(self) -> dict[str, str]:
        return dict(self._vanished_alerted)

    def prune_vanished_alerted(self) -> None:
        """Drop alert dates for devices no longer in the baseline."""
        for ieee in list(self._vanished_alerted):
            if ieee not in self._devices:
                del self._vanished_alerted[ieee]
