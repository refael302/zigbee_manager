"""System-wide health status (pure logic, unit-testable)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

SYSTEM_STATUS_OK = "ok"
SYSTEM_STATUS_STARTUP_GRACE = "startup_grace"
SYSTEM_STATUS_BRIDGE_OFFLINE = "bridge_offline"
SYSTEM_STATUS_BRIDGE_UNKNOWN = "bridge_unknown"
SYSTEM_STATUS_WAITING_DEVICES = "waiting_devices"
SYSTEM_STATUS_NETWORK_STALE = "network_stale"

SYSTEM_STATUS_LABELS_HE: dict[str, str] = {
    SYSTEM_STATUS_OK: "תקין",
    SYSTEM_STATUS_STARTUP_GRACE: "חסד הפעלה",
    SYSTEM_STATUS_BRIDGE_OFFLINE: "גשר לא זמין",
    SYSTEM_STATUS_BRIDGE_UNKNOWN: "ממתין לגשר",
    SYSTEM_STATUS_WAITING_DEVICES: "ממתין למכשירים",
    SYSTEM_STATUS_NETWORK_STALE: "אין תקשורת ממכשירים",
}


def compute_system_status(
    *,
    bridge_online: bool | None,
    startup_grace: bool,
    devices_received: bool,
    last_device_activity_at: datetime | None,
    stale_after: timedelta,
    now: datetime,
) -> tuple[str, dict[str, Any]]:
    """Return (status_key, detail dict) for the system status sensor."""
    details: dict[str, Any] = {
        "bridge_online": bridge_online,
        "startup_grace_active": startup_grace,
    }

    if startup_grace:
        return SYSTEM_STATUS_STARTUP_GRACE, details

    if bridge_online is None:
        return SYSTEM_STATUS_BRIDGE_UNKNOWN, details

    if bridge_online is False:
        return SYSTEM_STATUS_BRIDGE_OFFLINE, details

    if not devices_received:
        return SYSTEM_STATUS_WAITING_DEVICES, details

    if last_device_activity_at is None:
        return SYSTEM_STATUS_WAITING_DEVICES, details

    idle = now - last_device_activity_at
    details["last_device_activity_at"] = last_device_activity_at.isoformat()
    details["seconds_since_device_activity"] = int(idle.total_seconds())

    if idle > stale_after:
        details["stale_minutes"] = int(stale_after.total_seconds() // 60)
        return SYSTEM_STATUS_NETWORK_STALE, details

    return SYSTEM_STATUS_OK, details


def system_status_label(status_key: str, details: dict[str, Any]) -> str:
    """Human-readable Hebrew label for the sensor state."""
    base = SYSTEM_STATUS_LABELS_HE.get(status_key, status_key)
    if status_key == SYSTEM_STATUS_NETWORK_STALE:
        minutes = details.get("stale_minutes", 10)
        return f"{base} (>{minutes} דק')"
    return base
