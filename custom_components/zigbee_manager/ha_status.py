"""HA / Z2M cross-check helpers (pure logic, unit-testable)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .device_registry import DeviceState

IEEE_RE = re.compile(r"0x[0-9a-f]+", re.I)

MISMATCH_NONE = "none"
MISMATCH_NOT_IN_HA = "not_in_ha"
MISMATCH_Z2M_ONLINE_HA_OFFLINE = "z2m_online_ha_offline"
MISMATCH_Z2M_OFFLINE_HA_ONLINE = "z2m_offline_ha_online"

LINK_NONE = "none"
LINK_IEEE = "ieee"
LINK_FRIENDLY_NAME = "friendly_name"


@dataclass
class HaDeviceLookup:
    """Indexes HA device ids by IEEE and by Z2M-friendly name."""

    by_ieee: dict[str, str]
    by_friendly_name: dict[str, str]


def resolve_ha_device_id(
    dev: DeviceState, lookup: HaDeviceLookup
) -> tuple[str | None, str]:
    """Resolve a Z2M device to a HA device id and the method used."""
    ieee = normalize_ieee(dev.ieee_address)
    device_id = lookup.by_ieee.get(ieee)
    if device_id:
        return device_id, LINK_IEEE

    for key in friendly_name_lookup_keys(dev.friendly_name):
        device_id = lookup.by_friendly_name.get(key)
        if device_id:
            return device_id, LINK_FRIENDLY_NAME

    return None, LINK_NONE


def normalize_ieee(value: str) -> str:
    """Lower-case IEEE address with 0x prefix."""
    text = str(value).strip().lower()
    match = IEEE_RE.search(text)
    if match:
        return match.group(0)
    return text


def normalize_friendly_name(value: str) -> str:
    """Normalize a Z2M / HA device name for lookup (case-insensitive)."""
    return str(value).strip().lower()


def friendly_name_lookup_keys(name: str) -> set[str]:
    """Generate lookup keys for a Z2M friendly name (slashes vs underscores)."""
    base = normalize_friendly_name(name)
    keys = {base}
    keys.add(base.replace("/", "_"))
    keys.add(base.replace("_", "/"))
    return keys


def ieee_from_identifier_part(part: str) -> str | None:
    """Extract an IEEE address from a device identifier or connection fragment."""
    match = IEEE_RE.search(str(part))
    return match.group(0).lower() if match else None


def ieee_from_unique_id(unique_id: str | None) -> str | None:
    """Extract IEEE from a typical MQTT entity unique_id (prefix before first _)."""
    if not unique_id:
        return None
    head = str(unique_id).split("_", 1)[0]
    return ieee_from_identifier_part(head)


def entity_state_is_available(state: str | None) -> bool:
    """True when an entity state is considered available in Home Assistant."""
    return state not in (None, "unavailable", "unknown")


@dataclass(frozen=True)
class MqttEntityStatus:
    """Snapshot of one MQTT entity relevant to HA availability."""

    disabled: bool
    state: str | None


def device_ha_active_from_mqtt_entities(entities: list[MqttEntityStatus]) -> bool:
    """Device is HA-active when it has an enabled entity with an available state."""
    if not entities:
        return False
    enabled = [e for e in entities if not e.disabled]
    if not enabled:
        return False
    return any(entity_state_is_available(e.state) for e in enabled)


def device_ha_active_from_states(states: list[str | None]) -> bool:
    """Backward-compatible helper for tests without disabled metadata."""
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
        if dev.ha_entity_count and dev.ha_disabled_count >= dev.ha_entity_count:
            return (
                f"חוסר התאמה: מכשיר {name} פעיל ב-Z2M "
                f"אך כל ה-entities שלו מושבתים ב-Home Assistant"
            )
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
