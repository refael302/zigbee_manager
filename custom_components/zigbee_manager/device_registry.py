"""Pure-Python model of the Zigbee2MQTT device registry.

Parses `{base}/bridge/devices` payloads and computes diffs between snapshots.
No Home Assistant imports so it is directly unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

AVAILABILITY_ONLINE = "online"
AVAILABILITY_OFFLINE = "offline"
AVAILABILITY_UNKNOWN = "unknown"


@dataclass
class DeviceState:
    """State of a single Zigbee device (excluding the coordinator)."""

    ieee_address: str
    friendly_name: str
    vendor: str | None = None
    model: str | None = None
    device_type: str = "Unknown"  # Router / EndDevice / GreenPower
    supported: bool = True
    disabled: bool = False
    power_source: str | None = None
    interview_state: str = "SUCCESSFUL"
    availability: str = AVAILABILITY_UNKNOWN
    last_seen: datetime | None = None
    silent_alerted: bool = field(default=False, compare=False)

    @property
    def is_active(self) -> bool:
        """A device counts as active unless it is known to be offline or disabled."""
        return not self.disabled and self.availability != AVAILABILITY_OFFLINE

    def as_attribute(self) -> dict[str, Any]:
        """Compact dict for the registry sensor attributes."""
        return {
            "ieee_address": self.ieee_address,
            "vendor": self.vendor,
            "model": self.model,
            "type": self.device_type,
            "supported": self.supported,
            "disabled": self.disabled,
            "power_source": self.power_source,
            "interview_state": self.interview_state,
            "availability": self.availability,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }


def parse_last_seen(value: Any) -> datetime | None:
    """Parse a Z2M last_seen value (ISO_8601, ISO_8601_local or epoch ms)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def parse_bridge_devices(payload: list[dict[str, Any]]) -> dict[str, DeviceState]:
    """Parse a `bridge/devices` payload into DeviceState objects keyed by IEEE address.

    The Zigbee coordinator itself is excluded from the registry.
    """
    devices: dict[str, DeviceState] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        if raw.get("type") == "Coordinator":
            continue
        ieee = raw.get("ieee_address")
        if not ieee:
            continue
        definition = raw.get("definition") or {}
        devices[ieee] = DeviceState(
            ieee_address=ieee,
            friendly_name=raw.get("friendly_name") or ieee,
            vendor=definition.get("vendor"),
            model=definition.get("model"),
            device_type=raw.get("type") or "Unknown",
            supported=bool(raw.get("supported", True)),
            disabled=bool(raw.get("disabled", False)),
            power_source=raw.get("power_source"),
            interview_state=raw.get("interview_state")
            or ("SUCCESSFUL" if raw.get("interview_completed") else "PENDING"),
        )
    return devices


def diff_devices(
    old: dict[str, DeviceState], new: dict[str, DeviceState]
) -> tuple[list[DeviceState], list[DeviceState]]:
    """Return (joined, removed) devices between two registry snapshots."""
    joined = [dev for ieee, dev in new.items() if ieee not in old]
    removed = [dev for ieee, dev in old.items() if ieee not in new]
    return joined, removed


def merge_runtime_state(
    old: dict[str, DeviceState], new: dict[str, DeviceState]
) -> None:
    """Carry availability / last_seen / silent flags from the old snapshot into the new one."""
    for ieee, dev in new.items():
        prev = old.get(ieee)
        if prev is None:
            continue
        dev.availability = prev.availability
        dev.last_seen = prev.last_seen
        dev.silent_alerted = prev.silent_alerted
