"""Pure helpers for persisted device baseline / vanished detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .device_registry import DeviceState


def snapshot_from_devices(devices: dict[str, DeviceState]) -> dict[str, str]:
    """Build ieee -> friendly_name map from the live registry."""
    return {ieee: dev.friendly_name for ieee, dev in devices.items()}


def find_vanished(
    baseline: dict[str, str], current: dict[str, str]
) -> list[tuple[str, str]]:
    """Devices present in baseline but missing from the current Z2M list."""
    return [(ieee, baseline[ieee]) for ieee in baseline if ieee not in current]


def filter_vanished_for_alert(
    vanished: list[tuple[str, str]],
    alerted: dict[str, str],
    today: str,
) -> list[tuple[str, str]]:
    """Skip devices already alerted about vanishing on the same calendar day."""
    return [(ieee, name) for ieee, name in vanished if alerted.get(ieee) != today]
