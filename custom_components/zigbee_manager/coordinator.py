"""Central coordinator: holds Z2M network state and runs the alert engine."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_ALERT_DEVICE_HA_MISMATCH,
    CONF_ALERT_DEVICE_NOT_IN_HA,
    CONF_SILENT_THRESHOLD_HOURS,
    DEFAULT_SILENT_THRESHOLD_HOURS,
    DOMAIN,
    EVENT_BRIDGE_OFFLINE,
    EVENT_BRIDGE_ONLINE,
    EVENT_DEVICE_AVAILABLE,
    EVENT_DEVICE_HA_MISMATCH,
    EVENT_DEVICE_JOINED,
    EVENT_DEVICE_NOT_IN_HA,
    EVENT_DEVICE_REMOVED,
    EVENT_DEVICE_SILENT,
    EVENT_DEVICE_UNAVAILABLE,
    EVENT_TITLES_HE,
    UPDATE_INTERVAL_SECONDS,
)
from .ha_bridge import HaStateTracker, collect_mqtt_entity_ids, refresh_all_ha_status
from .ha_status import (
    MISMATCH_NONE,
    MISMATCH_NOT_IN_HA,
    MISMATCH_Z2M_OFFLINE_HA_ONLINE,
    MISMATCH_Z2M_ONLINE_HA_OFFLINE,
    classify_ha_mismatch,
    count_ha_active,
    mismatch_description,
)
from .device_registry import (
    AVAILABILITY_OFFLINE,
    AVAILABILITY_ONLINE,
    DeviceState,
    count_active_devices,
    diff_devices,
    mark_all_offline,
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
        self._ha_tracker = HaStateTracker(hass, self._async_on_ha_entities_changed)
        self._device_mismatch: dict[str, str] = {}
        self._ha_mismatch_initialized = False

    # ------------------------------------------------------------------ helpers

    @property
    def total_devices(self) -> int:
        return len(self.devices)

    @property
    def active_devices(self) -> int:
        return count_active_devices(self.devices, self.bridge_online)

    @property
    def ha_active_devices(self) -> int:
        active, _linked = count_ha_active(self.devices)
        return active

    @property
    def ha_linked_devices(self) -> int:
        _active, linked = count_ha_active(self.devices)
        return linked

    def _ha_status_counts(self) -> tuple[int, int]:
        return count_ha_active(self.devices)

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
            ha_active, ha_linked = self._ha_status_counts()
            await self.notifier.async_send(
                event_type,
                description,
                self.active_devices,
                self.total_devices,
                bridge_online=self.bridge_online,
                ha_active=ha_active,
                ha_linked=ha_linked,
            )
        self.async_set_updated_data(self._snapshot())

    def _ha_context_suffix(self, dev: DeviceState) -> str:
        if not dev.ha_linked:
            return " [HA: לא נמצא]"
        return f" [HA: {'זמין' if dev.ha_active else 'לא זמין'}]"

    def _snapshot(self) -> dict[str, Any]:
        ha_active, ha_linked = self._ha_status_counts()
        return {
            "total": self.total_devices,
            "active": self.active_devices,
            "ha_active": ha_active,
            "ha_linked": ha_linked,
            "bridge_online": self.bridge_online,
            "last_log": self.log.latest,
        }

    async def _async_refresh_ha_status(self) -> None:
        """Refresh HA link/active flags and re-arm MQTT entity listeners."""
        refresh_all_ha_status(self.hass, self.devices)
        entity_ids = collect_mqtt_entity_ids(self.hass, self.devices)
        self._ha_tracker.async_refresh_listeners(entity_ids)
        await self._async_check_ha_mismatches()

    async def _async_on_ha_entities_changed(self) -> None:
        refresh_all_ha_status(self.hass, self.devices)
        await self._async_check_ha_mismatches()
        self.async_set_updated_data(self._snapshot())

    async def _async_check_ha_mismatches(self) -> None:
        """Emit alerts when Z2M and HA device availability diverge."""
        current: dict[str, str] = {
            ieee: classify_ha_mismatch(dev, self.bridge_online)
            for ieee, dev in self.devices.items()
        }
        if not self._ha_mismatch_initialized:
            self._device_mismatch = current
            self._ha_mismatch_initialized = True
            return

        cfg = {**self.entry.data, **(self.entry.options or {})}
        alert_not_in_ha = bool(cfg.get(CONF_ALERT_DEVICE_NOT_IN_HA, True))
        alert_mismatch = bool(cfg.get(CONF_ALERT_DEVICE_HA_MISMATCH, True))

        for ieee, mismatch in current.items():
            dev = self.devices[ieee]
            previous = self._device_mismatch.get(ieee, MISMATCH_NONE)
            self._device_mismatch[ieee] = mismatch

            if mismatch == previous or mismatch == MISMATCH_NONE:
                continue

            if mismatch == MISMATCH_NOT_IN_HA and alert_not_in_ha:
                await self._emit(
                    EVENT_DEVICE_NOT_IN_HA,
                    mismatch_description(dev, mismatch),
                    subject=ieee,
                    level="warning",
                )
            elif mismatch in (
                MISMATCH_Z2M_ONLINE_HA_OFFLINE,
                MISMATCH_Z2M_OFFLINE_HA_ONLINE,
            ) and alert_mismatch:
                await self._emit(
                    EVENT_DEVICE_HA_MISMATCH,
                    mismatch_description(dev, mismatch),
                    subject=ieee,
                    level="warning",
                )

    def async_shutdown_ha_tracker(self) -> None:
        self._ha_tracker.async_stop()

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
            if not online:
                mark_all_offline(self.devices)
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
            mark_all_offline(self.devices)
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
            self._device_mismatch.pop(dev.ieee_address, None)
            await self._emit(
                EVENT_DEVICE_REMOVED,
                f"מכשיר {dev.friendly_name} ({dev.ieee_address}) נמחק מהרשת",
                subject=dev.ieee_address,
                level="warning",
            )
        await self._async_refresh_ha_status()
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
            self._device_mismatch.pop(ieee, None)
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
                f"מכשיר {dev.friendly_name} ({dev.ieee_address}) התנתק מהרשת"
                f"{self._ha_context_suffix(dev)}",
                subject=dev.ieee_address,
                level="warning",
            )
            await self._async_check_ha_mismatches()
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
                    f"לא תקשר מעל {hours} שעות"
                    f"{self._ha_context_suffix(dev)}",
                    subject=dev.ieee_address,
                    level="warning",
                )
        await self._async_refresh_ha_status()
        return self._snapshot()
