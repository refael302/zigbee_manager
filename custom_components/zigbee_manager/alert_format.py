"""Pure helpers for alert formatting and anti-spam cooldown (unit-testable, no HA imports)."""

from __future__ import annotations

import time

from .const import EVENT_BRIDGE_OFFLINE, EVENT_TITLES_HE

HEADER = "מערכת ניהול זיגבי"


def format_status_line(active: int, total: int, *, bridge_online: bool | None) -> str:
    """Build the status line for alert messages."""
    if bridge_online is False:
        if total:
            return f"סטטוס נוכחי: 0/{total} מכשירים פעילים (גשר לא זמין)"
        return "סטטוס נוכחי: גשר לא זמין — אין מידע על מכשירים"
    return f"סטטוס נוכחי: {active}/{total} מכשירים פעילים"


def format_alert(
    event_type: str,
    description: str,
    active: int,
    total: int,
    *,
    bridge_online: bool | None = None,
) -> str:
    """Build the standard Hebrew alert message.

    מערכת ניהול זיגבי
    התראה: <title>
    תיאור: <description>
    סטטוס נוכחי: X/Y מכשירים פעילים
    """
    title = EVENT_TITLES_HE.get(event_type, event_type)
    if event_type == EVENT_BRIDGE_OFFLINE:
        bridge_online = False
    return (
        f"{HEADER}\n"
        f"התראה: {title}\n"
        f"תיאור: {description}\n"
        f"{format_status_line(active, total, bridge_online=bridge_online)}"
    )


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
