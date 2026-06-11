"""HA / Z2M cross-check helpers (pure logic, unit-testable)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .device_registry import DeviceState

IEEE_RE = re.compile(r"0x[0-9a-f]+", re.I)

MISMATCH_NONE = "none"
MISMATCH_NOT_IN_HA = "not_in_ha"
MISMATCH_Z2M_ONLINE_HA_OFFLINE = "z2m_online_ha_offline"
MISMATCH_Z2M_OFFLINE_HA_ONLINE = "z2m_offline_ha_online"


def normalize_ieee(value: str) -> str:
    """Lower-case IEEE address with 0x prefix."""
    text = str(value).strip().lower()
    match = IEEE_RE.search(text)
    if match:
        return match.group(0)
    return text


def ieee_from_identifier_part(part: str) -> str | None:
    """Extract an IEEE address from a device identifier or connection fragment."""
    match = IEEE_RE.search(str(part))
    return match.group(0).lower() if match else None


def entity_state_is_available(state: str | None) -> bool:
    """True when an entity state is considered available in Home Assistant."""
    return state not in (None, "unavailable", "unknown")


def device_ha_active_from_states(states: list[str | None]) -> bool:
    """Device is HA-active when it has at least one available MQTT entity state."""
    if not states:
        return False
    return any(entity_state_is_available(s) for s in states)


def z2m_device_is_active(dev: DeviceState, bridge_online: bool | None) -> bool:
    """Whether the device counts as Z2M-active (respects bridge-down semantics)."""
    if bridge_online is False:
        return False
    return dev.is_active


def classify_ha_mismatch(dev: DeviceState, bridge_online: bool | None) -> str:
    """Classify Z2M vs HA availability mismatch for a single device."""
    if dev.disabled:
        return MISMATCH_NONE
    if not dev.ha_linked:
        return MISMATCH_NOT_IN_HA
    z2m_active = z2m_device_is_active(dev, bridge_online)
    if z2m_active and not dev.ha_active:
        return MISMATCH_Z2M_ONLINE_HA_OFFLINE
    if not z2m_active and dev.ha_active:
        return MISMATCH_Z2M_OFFLINE_HA_ONLINE
    return MISMATCH_NONE


def mismatch_description(dev: DeviceState, mismatch: str) -> str:
    """Hebrew description for a mismatch alert."""
    name = f"{dev.friendly_name} ({dev.ieee_address})"
    if mismatch == MISMATCH_NOT_IN_HA:
        return f"מכשיר {name} קיים ב-Z2M אך לא נמצא ב-Home Assistant (MQTT)"
    if mismatch == MISMATCH_Z2M_ONLINE_HA_OFFLINE:
        return (
            f"חוסר התאמה: מכשיר {name} פעיל ב-Z2M "
            f"אך לא זמין ב-Home Assistant"
        )
    if mismatch == MISMATCH_Z2M_OFFLINE_HA_ONLINE:
        return (
            f"חוסר התאמה: מכשיר {name} לא פעיל ב-Z2M "
            f"אך עדיין זמין ב-Home Assistant"
        )
    return name


def count_ha_active(devices: dict[str, DeviceState]) -> tuple[int, int]:
    """Return (ha_active_count, ha_linked_count)."""
    linked = [d for d in devices.values() if d.ha_linked]
    active = sum(1 for d in linked if d.ha_active)
    return active, len(linked)
