"""Central coordinator: holds Z2M network state and runs the alert engine."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

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
    EVENT_DEVICE_VANISHED,
    EVENT_DEVICE_SILENT,
    EVENT_DEVICE_UNAVAILABLE,
    EVENT_NETWORK_STALE,
    EVENT_TITLES_HE,
    NETWORK_ACTIVITY_TIMEOUT_MINUTES,
    STARTUP_GRACE_MINUTES,
    UPDATE_INTERVAL_SECONDS,
)
from .system_status import compute_system_status, system_status_label
from .alert_engine import (
    PendingAlert,
    SuppressReason,
    TelegramAction,
    AlertEngine,
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
from .device_snapshot import (
    filter_vanished_for_alert,
    find_vanished,
    snapshot_from_devices,
)
from .device_snapshot_store import DeviceSnapshotStore
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
        self._alert_engine = AlertEngine()
        self._digest_flush_unsub: Any | None = None
        self._devices_received = False
        self._ha_tracker = HaStateTracker(hass, self._async_on_ha_entities_changed)
        self._device_mismatch: dict[str, str] = {}
        self._ha_mismatch_initialized = False
        self._device_snapshot = DeviceSnapshotStore(hass, entry.entry_id)
        self._vanished_startup_check_done = False
        self._last_device_activity_at: datetime | None = None
        self._network_stale_alerted = False
        self._digest_flush_lock = asyncio.Lock()

    def _network_activity_timeout(self) -> timedelta:
        return timedelta(minutes=NETWORK_ACTIVITY_TIMEOUT_MINUTES)

    def _touch_device_activity(self) -> None:
        """Record MQTT traffic from a Zigbee device (state or availability)."""
        now = datetime.now(timezone.utc)
        was_stale = self._network_stale_alerted
        self._last_device_activity_at = now
        if was_stale:
            self._network_stale_alerted = False
            self.log.add("תקשורת MQTT ממכשירים חזרה", level="info")

    def _system_status_fields(self) -> tuple[str, str, dict[str, Any]]:
        now = datetime.now(timezone.utc)
        status_key, details = compute_system_status(
            bridge_online=self.bridge_online,
            startup_grace=self._alert_engine.in_startup_grace(),
            devices_received=self._devices_received,
            last_device_activity_at=self._last_device_activity_at,
            stale_after=self._network_activity_timeout(),
            now=now,
        )
        return status_key, system_status_label(status_key, details), details

    async def _async_check_network_stale(self) -> None:
        """Alert when the bridge looks online but no device MQTT arrived recently."""
        if self._alert_engine.in_startup_grace():
            return
        if self.bridge_online is not True:
            return
        if not self._devices_received:
            return
        if self._last_device_activity_at is None:
            return
        if self._network_stale_alerted:
            return

        idle = datetime.now(timezone.utc) - self._last_device_activity_at
        if idle <= self._network_activity_timeout():
            return

        minutes = NETWORK_ACTIVITY_TIMEOUT_MINUTES
        self._network_stale_alerted = True
        await self._emit(
            EVENT_NETWORK_STALE,
            f"לא התקבלה הודעת MQTT מאף מכשיר ב-{minutes} דקות האחרונות "
            f"(גשר מדווח online — ייתכן קיפאון Z2M)",
            subject="network",
            level="error",
        )

    async def async_load_device_snapshot(self) -> None:
        """Load persisted device baseline from disk."""
        await self._device_snapshot.async_load()

    async def async_reset_device_snapshot(self) -> None:
        """Set the stored baseline to the current Z2M device list."""
        self._device_snapshot.set_baseline(snapshot_from_devices(self.devices))
        self._device_snapshot.clear_vanished_alerted()
        await self._device_snapshot.async_save()
        self.log.add(
            f"רשימת בסיס מכשירים אופסה — {self._device_snapshot.baseline_count} מכשירים",
            level="info",
        )
        self.async_set_updated_data(self._snapshot())

    def _current_device_snapshot(self) -> dict[str, str]:
        return snapshot_from_devices(self.devices)

    async def _async_persist_snapshot_add(self, ieee: str, friendly_name: str) -> None:
        self._device_snapshot.add_device(ieee, friendly_name)
        await self._device_snapshot.async_save()

    async def _async_persist_snapshot_remove(self, ieee: str) -> None:
        self._device_snapshot.remove_device(ieee)
        await self._device_snapshot.async_save()

    async def _async_maybe_check_vanished_on_startup(self) -> None:
        """Compare persisted baseline to Z2M once per HA start (after grace + devices)."""
        if self._vanished_startup_check_done:
            return
        if not self._devices_received:
            return
        if self._alert_engine.in_startup_grace():
            return

        self._vanished_startup_check_done = True
        baseline = self._device_snapshot.baseline
        current = self._current_device_snapshot()

        if not baseline:
            self._device_snapshot.set_baseline(current)
            await self._device_snapshot.async_save()
            self.log.add(
                f"רשימת בסיס מכשירים נוצרה — {len(current)} מכשירים",
                level="info",
            )
            return

        today = dt_util.now().date().isoformat()
        vanished = find_vanished(baseline, current)
        to_alert = filter_vanished_for_alert(
            vanished, self._device_snapshot.vanished_alerted, today
        )

        for ieee, name in to_alert:
            await self._emit(
                EVENT_DEVICE_VANISHED,
                f"מכשיר {name} ({ieee}) נעלם מ-Z2M (היה ברשימת הבסיס, לא נמצא בהפעלה)",
                subject=ieee,
                level="warning",
            )
            self._device_snapshot.mark_vanished_alerted(ieee, today)

        if to_alert:
            await self._device_snapshot.async_save()

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

    def _cancel_digest_flush_timer(self) -> None:
        if self._digest_flush_unsub is not None:
            self._digest_flush_unsub()
            self._digest_flush_unsub = None

    def _schedule_async(self, coro_factory) -> None:
        """Schedule coroutine work on the HA event loop (safe from timer threads)."""

        def _start() -> None:
            self.hass.async_create_task(coro_factory())

        self.hass.loop.call_soon_threadsafe(_start)

    def async_schedule_startup_finalizer(self) -> None:
        """After startup grace, sync HA baseline and flush any queued startup digest."""

        def _on_grace_end(_now: datetime) -> None:
            self._schedule_async(self._async_on_startup_grace_end)

        async_track_point_in_time(
            self.hass,
            _on_grace_end,
            datetime.now(timezone.utc) + timedelta(minutes=STARTUP_GRACE_MINUTES),
        )

    async def _async_on_startup_grace_end(self) -> None:
        self._alert_engine.end_startup_grace()
        self._device_mismatch = {
            ieee: classify_ha_mismatch(dev, self.bridge_online)
            for ieee, dev in self.devices.items()
        }
        self.log.add(
            "תקופת חסד בהפעלה הסתיימה — סנכרון בסיס חוסר התאמה HA",
            level="info",
        )
        await self._async_maybe_check_vanished_on_startup()
        if self._alert_engine.digest_pending():
            await self._async_flush_digest(startup=True, force=True)
        self.async_set_updated_data(self._snapshot())

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
        if notify:
            await self._maybe_send_telegram(event_type, description, subject=subject)
        self.async_set_updated_data(self._snapshot())

    async def _maybe_send_telegram(
        self, event_type: str, description: str, *, subject: str
    ) -> None:
        if not self.notifier.is_enabled(event_type):
            return

        plan = self._alert_engine.plan_telegram(event_type, subject)

        if plan.action == TelegramAction.SUPPRESS:
            self._log_suppressed(event_type, description, plan.reason)
            return

        if plan.action == TelegramAction.SEND_CRITICAL:
            await self._deliver_telegram(
                event_type, description, critical=True
            )
            return

        self._alert_engine.enqueue(
            PendingAlert(event_type, subject, description)
        )
        if self._alert_engine.in_startup_grace():
            return
        await self._schedule_digest_flush()

    def _log_suppressed(
        self, event_type: str, description: str, reason: SuppressReason
    ) -> None:
        reason_he = {
            SuppressReason.BRIDGE_INCIDENT: "גשר לא זמין",
        }.get(reason, "סינון")
        self.log.add(
            f"Telegram נדחה ({reason_he}): {description}",
            level="debug",
            event_type=event_type,
        )

    async def _schedule_digest_flush(self) -> None:
        if self._alert_engine.digest_pending() == 0:
            return
        if self._alert_engine.in_startup_grace():
            return
        if self._alert_engine.can_flush_digest():
            await self._async_flush_digest()
            return
        if self._digest_flush_unsub is not None:
            return

        delay = self._alert_engine.seconds_until_flush()

        def _flush(_now: datetime) -> None:
            self._digest_flush_unsub = None
            self._schedule_async(self._async_flush_digest)

        self._digest_flush_unsub = async_track_point_in_time(
            self.hass,
            _flush,
            datetime.now(timezone.utc) + timedelta(seconds=max(delay, 1)),
        )

    async def _async_flush_digest(
        self, *, startup: bool = False, force: bool = False
    ) -> None:
        async with self._digest_flush_lock:
            self._cancel_digest_flush_timer()
            if not force and not self._alert_engine.can_flush_digest():
                await self._schedule_digest_flush()
                return

            items = self._alert_engine.pop_digest()
            if not items:
                return

            self._alert_engine.record_send()
            ha_active, ha_linked = self._ha_status_counts()
            await self.notifier.async_send_digest(
                items,
                self.active_devices,
                self.total_devices,
                startup=startup,
                bridge_online=self.bridge_online,
                ha_active=ha_active,
                ha_linked=ha_linked,
            )

    async def _deliver_telegram(
        self,
        event_type: str,
        description: str,
        *,
        critical: bool = False,
    ) -> None:
        self._cancel_digest_flush_timer()
        ha_active, ha_linked = self._ha_status_counts()
        await self.notifier.async_send(
            event_type,
            description,
            self.active_devices,
            self.total_devices,
            bridge_online=self.bridge_online,
            ha_active=ha_active,
            ha_linked=ha_linked,
            critical=critical,
        )
        self._alert_engine.record_send()
        if self._alert_engine.digest_pending():
            await self._schedule_digest_flush()

    def _ha_context_suffix(self, dev: DeviceState) -> str:
        if not dev.ha_linked:
            return " [HA: לא נמצא]"
        if dev.ha_entity_count and dev.ha_disabled_count >= dev.ha_entity_count:
            return " [HA: מושבת]"
        return f" [HA: {'זמין' if dev.ha_active else 'לא זמין'}]"

    def _snapshot(self) -> dict[str, Any]:
        ha_active, ha_linked = self._ha_status_counts()
        status_key, status_label, status_details = self._system_status_fields()
        return {
            "total": self.total_devices,
            "active": self.active_devices,
            "ha_active": ha_active,
            "ha_linked": ha_linked,
            "bridge_online": self.bridge_online,
            "last_log": self.log.latest,
            "telegram_digest_pending": self._alert_engine.digest_pending(),
            "startup_grace_active": self._alert_engine.in_startup_grace(),
            "device_snapshot_baseline": self._device_snapshot.baseline_count,
            "system_status": status_key,
            "system_status_label": status_label,
            **status_details,
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

        if self._alert_engine.in_startup_grace():
            self._device_mismatch = current
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
                self._alert_engine.set_bridge_incident(True)
            self.async_set_updated_data(self._snapshot())
            return

        if online and not previous:
            self.bridge_started_at = datetime.now(timezone.utc)
            self.bridge_start_estimated = False
            self._alert_engine.set_bridge_incident(False)
            self._network_stale_alerted = False
            await self._emit(
                EVENT_BRIDGE_ONLINE,
                "גשר ה-Zigbee2MQTT חזר לפעילות",
                subject="bridge",
            )
        elif not online and previous:
            mark_all_offline(self.devices)
            self._alert_engine.set_bridge_incident(True)
            self._network_stale_alerted = False
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
            await self._async_persist_snapshot_add(
                dev.ieee_address, dev.friendly_name
            )
        for dev in removed:
            self._device_mismatch.pop(dev.ieee_address, None)
            await self._emit(
                EVENT_DEVICE_REMOVED,
                f"מכשיר {dev.friendly_name} ({dev.ieee_address}) נמחק מהרשת",
                subject=dev.ieee_address,
                level="warning",
            )
            await self._async_persist_snapshot_remove(dev.ieee_address)
        await self._async_refresh_ha_status()
        await self._async_maybe_check_vanished_on_startup()
        self.async_set_updated_data(self._snapshot())

    async def async_handle_bridge_event(self, payload: Any) -> None:
        """`{base}/bridge/event` — device_joined / device_leave / device_announce."""
        if not isinstance(payload, dict):
            return
        # Join/leave alerts and registry updates are handled via bridge/devices
        # to avoid duplicate Telegram digests (Z2M publishes both topics).
        if payload.get("type") in ("device_joined", "device_leave"):
            return

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

    async def async_handle_availability(self, friendly_name: str, payload: Any) -> None:
        """`{base}/FRIENDLY_NAME/availability` — {"state": "online"|"offline"} or plain text."""
        state = payload.get("state") if isinstance(payload, dict) else payload
        if state not in (AVAILABILITY_ONLINE, AVAILABILITY_OFFLINE):
            return
        dev = self._device_by_name(friendly_name)
        if dev is None:
            return
        self._touch_device_activity()
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
        self._touch_device_activity()
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
        if hours < 1:
            hours = round(threshold.total_seconds() / 3600, 1)
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
        await self._async_check_network_stale()
        await self._async_refresh_ha_status()
        return self._snapshot()
