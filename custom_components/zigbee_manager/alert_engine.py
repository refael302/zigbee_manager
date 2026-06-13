"""Telegram anti-spam: startup grace, global digest gate, bridge-incident suppression."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from typing import Callable

from .const import (
    EVENT_BRIDGE_OFFLINE,
    EVENT_BRIDGE_ONLINE,
    EVENT_DEVICE_HA_MISMATCH,
    EVENT_DEVICE_NOT_IN_HA,
    EVENT_DEVICE_UNAVAILABLE,
    EVENT_NETWORK_STALE,
    STARTUP_GRACE_MINUTES,
    TELEGRAM_DIGEST_INTERVAL_SECONDS,
)

# Always delivered immediately (subject to toggle + chat ID).
CRITICAL_EVENTS: frozenset[str] = frozenset(
    {EVENT_BRIDGE_OFFLINE, EVENT_BRIDGE_ONLINE, EVENT_NETWORK_STALE}
)

# Per-device alerts while the bridge is down (one bridge alert is enough).
BRIDGE_INCIDENT_SUPPRESSED_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_DEVICE_UNAVAILABLE,
        EVENT_DEVICE_NOT_IN_HA,
        EVENT_DEVICE_HA_MISMATCH,
    }
)


class TelegramAction(Enum):
    """What the coordinator should do for a Telegram-bound alert."""

    SEND_CRITICAL = auto()
    ENQUEUE = auto()
    SUPPRESS = auto()


class SuppressReason(Enum):
    NONE = auto()
    BRIDGE_INCIDENT = auto()


@dataclass
class PendingAlert:
    """One alert waiting in the global digest queue."""

    event_type: str
    subject: str
    description: str


@dataclass
class TelegramPlan:
    """Decision for whether/how to send a Telegram alert."""

    action: TelegramAction
    reason: SuppressReason = SuppressReason.NONE


class GlobalSendGate:
    """At most one non-critical Telegram message every N seconds."""

    def __init__(
        self,
        interval_seconds: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._interval = interval_seconds
        self._clock = clock or datetime.now(timezone.utc).timestamp
        self._last_send: float | None = None

    def can_send_now(self) -> bool:
        if self._last_send is None:
            return True
        return (self._clock() - self._last_send) >= self._interval

    def seconds_until_send(self) -> float:
        if self._last_send is None:
            return 0.0
        elapsed = self._clock() - self._last_send
        return max(0.0, self._interval - elapsed)

    def record_send(self) -> None:
        self._last_send = self._clock()


class AlertEngine:
    """Central anti-spam policy: digest queue + 5-minute global gate."""

    def __init__(
        self,
        started_at: datetime | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._started_at = started_at or datetime.now(timezone.utc)
        self._clock = clock or datetime.now(timezone.utc).timestamp
        self._gate = GlobalSendGate(
            TELEGRAM_DIGEST_INTERVAL_SECONDS, clock=self._clock
        )
        self._bridge_incident = False
        self._startup_grace_override = False
        self._digest: dict[tuple[str, str], PendingAlert] = {}

    @property
    def bridge_incident(self) -> bool:
        return self._bridge_incident

    def set_bridge_incident(self, active: bool) -> None:
        self._bridge_incident = active

    def end_startup_grace(self) -> None:
        """Called after HA/Z2M stabilizes — allow digest flushes."""
        self._startup_grace_override = True

    def in_startup_grace(self) -> bool:
        if self._startup_grace_override:
            return False
        elapsed = datetime.now(timezone.utc) - self._started_at
        return elapsed < timedelta(minutes=STARTUP_GRACE_MINUTES)

    def plan_telegram(self, event_type: str, subject: str) -> TelegramPlan:
        """Decide how to handle a Telegram alert."""
        if event_type in CRITICAL_EVENTS:
            return TelegramPlan(TelegramAction.SEND_CRITICAL)

        if self._bridge_incident and event_type in BRIDGE_INCIDENT_SUPPRESSED_EVENTS:
            return TelegramPlan(
                TelegramAction.SUPPRESS, SuppressReason.BRIDGE_INCIDENT
            )

        return TelegramPlan(TelegramAction.ENQUEUE)

    def enqueue(self, alert: PendingAlert) -> None:
        """Add to digest; same event_type+subject keeps only the latest description."""
        key = (alert.event_type, alert.subject)
        self._digest[key] = alert

    def pop_digest(self) -> list[PendingAlert]:
        items = list(self._digest.values())
        self._digest.clear()
        return items

    def digest_pending(self) -> int:
        return len(self._digest)

    def can_flush_digest(self) -> bool:
        return (
            len(self._digest) > 0
            and not self.in_startup_grace()
            and self._gate.can_send_now()
        )

    def seconds_until_flush(self) -> float:
        return self._gate.seconds_until_send()

    def record_send(self) -> None:
        self._gate.record_send()
