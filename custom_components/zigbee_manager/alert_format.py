"""Pure helpers for alert formatting and anti-spam cooldown (unit-testable, no HA imports)."""

from __future__ import annotations

import time

from .const import EVENT_BRIDGE_OFFLINE, EVENT_TITLES_HE

HEADER = "מערכת ניהול זיגבי"


def format_status_block(
    z2m_active: int,
    z2m_total: int,
    *,
    bridge_online: bool | None,
    ha_active: int = 0,
    ha_linked: int = 0,
) -> str:
    """Build Z2M + HA status lines for alert messages."""
    lines: list[str] = []
    if bridge_online is False:
        if z2m_total:
            lines.append(
                f"סטטוס Z2M: 0/{z2m_total} מכשירים פעילים (גשר לא זמין)"
            )
        else:
            lines.append("סטטוס Z2M: גשר לא זמין")
    else:
        lines.append(f"סטטוס Z2M: {z2m_active}/{z2m_total} מכשירים פעילים")

    if ha_linked or z2m_total:
        lines.append(f"סטטוס HA: {ha_active}/{ha_linked} מכשירים פעילים ב-MQTT")
        missing = max(z2m_total - ha_linked, 0)
        if missing:
            lines.append(f"({missing} מכשירים ב-Z2M לא נמצאו ב-Home Assistant)")
    return "\n".join(lines)


def format_status_line(
    active: int,
    total: int,
    *,
    bridge_online: bool | None,
    ha_active: int = 0,
    ha_linked: int = 0,
) -> str:
    """Backward-compatible wrapper returning the full status block."""
    return format_status_block(
        active,
        total,
        bridge_online=bridge_online,
        ha_active=ha_active,
        ha_linked=ha_linked,
    )


def format_alert(
    event_type: str,
    description: str,
    active: int,
    total: int,
    *,
    bridge_online: bool | None = None,
    ha_active: int = 0,
    ha_linked: int = 0,
) -> str:
    """Build the standard Hebrew alert message."""
    title = EVENT_TITLES_HE.get(event_type, event_type)
    if event_type == EVENT_BRIDGE_OFFLINE:
        bridge_online = False
    status = format_status_block(
        active,
        total,
        bridge_online=bridge_online,
        ha_active=ha_active,
        ha_linked=ha_linked,
    )
    return f"{HEADER}\nהתראה: {title}\nתיאור: {description}\n{status}"


class AlertCooldown:
    """Tracks last-sent time per (event_type, subject) to suppress repeats."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._last_sent: dict[tuple[str, str], float] = {}

    def allow(self, event_type: str, subject: str, cooldown_seconds: float) -> bool:
        """Return True (and start a new window) if enough time passed since the last send."""
        key = (event_type, subject)
        now = self._clock()
        last = self._last_sent.get(key)
        if last is not None and (now - last) < cooldown_seconds:
            return False
        self._last_sent[key] = now
        return True
