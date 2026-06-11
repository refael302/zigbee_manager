"""Central coordinator: holds Z2M network state and runs the alert engine."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_SILENT_THRESHOLD_HOURS,
    DEFAULT_SILENT_THRESHOLD_HOURS,
    DOMAIN,
    EVENT_BRIDGE_OFFLINE,
    EVENT_BRIDGE_ONLINE,
    EVENT_DEVICE_AVAILABLE,
    EVENT_DEVICE_JOINED,
    EVENT_DEVICE_REMOVED,
    EVENT_DEVICE_SILENT,
    EVENT_DEVICE_UNAVAILABLE,
    EVENT_TITLES_HE,
    UPDATE_INTERVAL_SECONDS,
)
from .device_registry import (
    AVAILABILITY_OFFLINE,
    AVAILABILITY_ONLINE,
    DeviceState,
    diff_devices,
    merge_runtime_state,
    parse_bridge_devices,
    parse_last_seen,
)
from .integration_log import IntegrationLog
from .notifier import TelegramNotifier

_LOGGER = logging.getLogger(__name__)


class ZigbeeManagerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Tracks devices, bridge state and uptime; emits alerts on changes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.entry = entry
        self.devices: dict[str, DeviceState] = {}
        self.bridge_online: bool | None = None
        self.bridge_started_at: datetime | None = None
        self.bridge_start_estimated: bool = True
        self.bridge_info: dict[str, Any] = {}
        self.log = IntegrationLog()
        self.notifier = TelegramNotifier(hass, entry.entry_id)
        self._devices_received = False

    # ------------------------------------------------------------------ helpers

    @property
    def total_devices(self) -> int:
        return len(self.devices)

    @property
    def active_devices(self) -> int:
        return sum(1 for dev in self.devices.values() if dev.is_active)

    def _device_by_name(self, friendly_name: str) -> DeviceState | None:
        for dev in self.devices.values():
            if dev.friendly_name == friendly_name:
                return dev
        return None

    def _silent_threshold(self) -> timedelta:
        cfg = {**self.entry.data, **(self.entry.options or {})}
        try:
            hours = float(
                cfg.get(CONF_SILENT_THRESHOLD_HOURS, DEFAULT_SILENT_THRESHOLD_HOURS)
            )
        except (TypeError, ValueError):
            hours = DEFAULT_SILENT_THRESHOLD_HOURS
        return timedelta(hours=hours)

    async def _emit(
        self,
        event_type: str,
        description: str,
        *,
        subject: str = "",
        level: str = "info",
        notify: bool = True,
    ) -> None:
        """Record an alert in the log and (optionally) send it to Telegram."""
        title = EVENT_TITLES_HE.get(event_type, event_type)
        self.log.add(f"{title} — {description}", level=level, event_type=event_type)
        if notify and self.notifier.should_send(event_type, subject):
            await self.notifier.async_send(
                event_type, description, self.active_devices, self.total_devices
            )
        self.async_set_updated_data(self._snapshot())

    def _snapshot(self) -> dict[str, Any]:
        return {
            "total": self.total_devices,
            "active": self.active_devices,
            "bridge_online": self.bridge_online,
            "last_log": self.log.latest,
        }

    # ------------------------------------------------------------- MQTT handlers

    async def async_handle_bridge_state(self, payload: Any) -> None:
        """`{base}/bridge/state` — {"state": "online"|"offline"} (retained)."""
        state = payload.get("state") if isinstance(payload, dict) else payload
        online = state == "online"
        previous = self.bridge_online
        self.bridge_online = online

        if previous is None:
            # First (retained) message after HA start: approximate uptime start.
            if online and self.bridge_started_at is None:
                self.bridge_started_at = datetime.now(timezone.utc)
                self.bridge_start_estimated = True
            self.async_set_updated_data(self._snapshot())
            return

        if online and not previous:
            self.bridge_started_at = datetime.now(timezone.utc)
            self.bridge_start_estimated = False
            await self._emit(
                EVENT_BRIDGE_ONLINE,
                "גשר ה-Zigbee2MQTT חזר לפעילות",
                subject="bridge",
            )
        elif not online and previous:
            await self._emit(
                EVENT_BRIDGE_OFFLINE,
                "גשר ה-Zigbee2MQTT הפסיק להגיב — רשת הזיגבי אינה זמינה",
                subject="bridge",
                level="error",
            )

    async def async_handle_bridge_devices(self, payload: Any) -> None:
        """`{base}/bridge/devices` — full device list (retained)."""
        if not isinstance(payload, list):
            return
        new_devices = parse_bridge_devices(payload)
        merge_runtime_state(self.devices, new_devices)

        if self._devices_received:
            joined, removed = diff_devices(self.devices, new_devices)
        else:
            joined, removed = [], []
        self.devices = new_devices
        self._devices_received = True

        for dev in joined:
            await self._emit(
                EVENT_DEVICE_JOINED,
                f"מכשיר {dev.friendly_name} ({dev.ieee_address}) הצטרף לרשת",
                subject=dev.ieee_address,
            )
        for dev in removed:
            await self._emit(
                EVENT_DEVICE_REMOVED,
                f"מכשיר {dev.friendly_name} ({dev.ieee_address}) נמחק מהרשת",
                subject=dev.ieee_address,
                level="warning",
            )
        self.async_set_updated_data(self._snapshot())

    async def async_handle_bridge_event(self, payload: Any) -> None:
        """`{base}/bridge/event` — device_joined / device_leave / device_announce."""
        if not isinstance(payload, dict):
            return
        event_type = payload.get("type")
        data = payload.get("data") or {}
        name = data.get("friendly_name") or data.get("ieee_address") or "?"
        ieee = data.get("ieee_address") or name

        if event_type == "device_joined":
            await self._emit(
                EVENT_DEVICE_JOINED,
                f"מכשיר {name} ({ieee}) הצטרף לרשת",
                subject=ieee,
            )
        elif event_type == "device_leave":
            self.devices.pop(ieee, None)
            await self._emit(
                EVENT_DEVICE_REMOVED,
                f"מכשיר {name} ({ieee}) נמחק מהרשת",
                subject=ieee,
                level="warning",
            )

    async def async_handle_bridge_info(self, payload: Any) -> None:
        """`{base}/bridge/info` — version, coordinator type, network settings (retained)."""
        if not isinstance(payload, dict):
            return
        coordinator = payload.get("coordinator") or {}
        network = payload.get("network") or {}
        self.bridge_info = {
            "version": payload.get("version"),
            "coordinator_type": coordinator.get("type"),
            "network_channel": network.get("channel"),
            "permit_join": payload.get("permit_join"),
        }
        self.async_set_updated_data(self._snapshot())

    async def async_handle_bridge_logging(self, payload: Any) -> None:
        """`{base}/bridge/logging` — {"level", "message", "namespace"}."""
        if not isinstance(payload, dict):
            return
        if str(payload.get("level")) == "debug":
            return
        if self.log.add_bridge_log(payload):
            self.async_set_updated_data(self._snapshot())

    async def async_handle_availability(self, friendly_name: str, payload: Any) -> None:
        """`{base}/FRIENDLY_NAME/availability` — {"state": "online"|"offline"} or plain text."""
        state = payload.get("state") if isinstance(payload, dict) else payload
        if state not in (AVAILABILITY_ONLINE, AVAILABILITY_OFFLINE):
            return
        dev = self._device_by_name(friendly_name)
        if dev is None:
            return
        previous = dev.availability
        dev.availability = state

        if state == AVAILABILITY_OFFLINE and previous == AVAILABILITY_ONLINE:
            await self._emit(
                EVENT_DEVICE_UNAVAILABLE,
                f"מכשיר {dev.friendly_name} ({dev.ieee_address}) התנתק מהרשת",
                subject=dev.ieee_address,
                level="warning",
            )
        elif state == AVAILABILITY_ONLINE and previous == AVAILABILITY_OFFLINE:
            # Recovery is recorded in the log but is not one of the Telegram alert types.
            await self._emit(
                EVENT_DEVICE_AVAILABLE,
                f"מכשיר {dev.friendly_name} ({dev.ieee_address}) חזר לרשת",
                subject=dev.ieee_address,
                notify=False,
            )
        else:
            self.async_set_updated_data(self._snapshot())

    async def async_handle_device_message(
        self, friendly_name: str, payload: Any
    ) -> None:
        """Any device state message — refresh last_seen (explicit attribute or receive time)."""
        dev = self._device_by_name(friendly_name)
        if dev is None:
            return
        last_seen = None
        if isinstance(payload, dict):
            last_seen = parse_last_seen(payload.get("last_seen"))
        dev.last_seen = last_seen or datetime.now(timezone.utc)
        dev.silent_alerted = False

    # ----------------------------------------------------------- periodic update

    async def _async_update_data(self) -> dict[str, Any]:
        """Periodic tick: detect devices silent beyond the configured threshold."""
        threshold = self._silent_threshold()
        now = datetime.now(timezone.utc)
        hours = int(threshold.total_seconds() // 3600)
        for dev in self.devices.values():
            if dev.disabled or dev.silent_alerted or dev.last_seen is None:
                continue
            if now - dev.last_seen > threshold:
                dev.silent_alerted = True
                await self._emit(
                    EVENT_DEVICE_SILENT,
                    f"מכשיר {dev.friendly_name} ({dev.ieee_address}) "
                    f"לא תקשר מעל {hours} שעות",
                    subject=dev.ieee_address,
                    level="warning",
                )
        return self._snapshot()
