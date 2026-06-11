"""Telegram anti-spam: rate limits, startup grace, bridge-incident suppression, batching."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from typing import Callable

from .alert_format import AlertCooldown
from .const import (
    EVENT_BRIDGE_OFFLINE,
    EVENT_BRIDGE_ONLINE,
    EVENT_DEVICE_HA_MISMATCH,
    EVENT_DEVICE_JOINED,
    EVENT_DEVICE_NOT_IN_HA,
    EVENT_DEVICE_SILENT,
    EVENT_DEVICE_UNAVAILABLE,
)

# Always delivered on Telegram (subject to toggle + chat ID), bypass hourly/daily caps.
CRITICAL_EVENTS: frozenset[str] = frozenset(
    {EVENT_BRIDGE_OFFLINE, EVENT_BRIDGE_ONLINE}
)

# No Telegram during HA/Z2M startup churn — still logged locally.
STARTUP_SUPPRESSED_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_DEVICE_UNAVAILABLE,
        EVENT_DEVICE_JOINED,
        EVENT_DEVICE_NOT_IN_HA,
        EVENT_DEVICE_HA_MISMATCH,
        EVENT_DEVICE_SILENT,
    }
)

# Per-device alerts while the bridge is down (one bridge alert is enough).
BRIDGE_INCIDENT_SUPPRESSED_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_DEVICE_UNAVAILABLE,
        EVENT_DEVICE_NOT_IN_HA,
        EVENT_DEVICE_HA_MISMATCH,
    }
)

# Combine multiple similar alerts into one Telegram message.
BATCHABLE_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_DEVICE_UNAVAILABLE,
        EVENT_DEVICE_NOT_IN_HA,
        EVENT_DEVICE_HA_MISMATCH,
    }
)

BATCH_WINDOW_SECONDS = 120


class TelegramAction(Enum):
    """What the coordinator should do for a Telegram-bound alert."""

    SEND = auto()
    SEND_CRITICAL = auto()
    BATCH = auto()
    SUPPRESS = auto()


class SuppressReason(Enum):
    NONE = auto()
    STARTUP_GRACE = auto()
    BRIDGE_INCIDENT = auto()
    RATE_LIMIT = auto()
    COOLDOWN = auto()


@dataclass
class PendingAlert:
    """One alert waiting in a batch window."""

    event_type: str
    subject: str
    description: str


@dataclass
class TelegramPlan:
    """Decision for whether/how to send a Telegram alert."""

    action: TelegramAction
    reason: SuppressReason = SuppressReason.NONE


@dataclass
class SuppressedRecord:
    event_type: str
    description: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TelegramRateLimiter:
    """Enforce max sends per hour and per day (non-critical only)."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or datetime.now(timezone.utc).timestamp
        self._send_times: list[float] = []

    def _prune(self, now: float) -> None:
        day_ago = now - 86400
        self._send_times = [t for t in self._send_times if t > day_ago]

    def can_send(self, *, max_per_hour: int, max_per_day: int) -> bool:
        now = self._clock()
        self._prune(now)
        hour_ago = now - 3600
        recent_hour = sum(1 for t in self._send_times if t > hour_ago)
        return recent_hour < max_per_hour and len(self._send_times) < max_per_day

    def record_send(self) -> None:
        self._send_times.append(self._clock())


class AlertEngine:
    """Central anti-spam policy for Telegram alerts."""

    def __init__(self, started_at: datetime | None = None) -> None:
        self._started_at = started_at or datetime.now(timezone.utc)
        self._rate = TelegramRateLimiter()
        self._cooldown = AlertCooldown()
        self._bridge_incident = False
        self._startup_grace_override = False
        self._suppressed: list[SuppressedRecord] = []
        self._pending_batches: dict[str, list[PendingAlert]] = {}

    @property
    def bridge_incident(self) -> bool:
        return self._bridge_incident

    @property
    def suppressed_count(self) -> int:
        return len(self._suppressed)

    def set_bridge_incident(self, active: bool) -> None:
        self._bridge_incident = active

    def end_startup_grace(self) -> None:
        """Called after HA/Z2M stabilizes — allow normal Telegram rules."""
        self._startup_grace_override = True

    def in_startup_grace(self, grace_minutes: float) -> bool:
        if self._startup_grace_override:
            return False
        elapsed = datetime.now(timezone.utc) - self._started_at
        return elapsed < timedelta(minutes=grace_minutes)

    def plan_telegram(
        self,
        event_type: str,
        subject: str,
        *,
        startup_grace_minutes: float,
        max_per_hour: int,
        max_per_day: int,
        cooldown_seconds: float,
    ) -> TelegramPlan:
        """Decide how to handle a Telegram alert (does not mutate suppressed list)."""
        is_critical = event_type in CRITICAL_EVENTS

        if not is_critical and self.in_startup_grace(startup_grace_minutes):
            if event_type in STARTUP_SUPPRESSED_EVENTS:
                return TelegramPlan(
                    TelegramAction.SUPPRESS, SuppressReason.STARTUP_GRACE
                )

        if not is_critical and self._bridge_incident:
            if event_type in BRIDGE_INCIDENT_SUPPRESSED_EVENTS:
                return TelegramPlan(
                    TelegramAction.SUPPRESS, SuppressReason.BRIDGE_INCIDENT
                )

        if not is_critical and not self._cooldown.allow(
            event_type, subject, cooldown_seconds
        ):
            return TelegramPlan(TelegramAction.SUPPRESS, SuppressReason.COOLDOWN)

        if is_critical:
            return TelegramPlan(TelegramAction.SEND_CRITICAL)

        if not self._rate.can_send(
            max_per_hour=max_per_hour, max_per_day=max_per_day
        ):
            return TelegramPlan(TelegramAction.SUPPRESS, SuppressReason.RATE_LIMIT)

        if event_type in BATCHABLE_EVENTS:
            return TelegramPlan(TelegramAction.BATCH)

        return TelegramPlan(TelegramAction.SEND)

    def record_suppressed(
        self, event_type: str, description: str, reason: SuppressReason
    ) -> None:
        if reason == SuppressReason.NONE:
            return
        self._suppressed.append(
            SuppressedRecord(event_type=event_type, description=description)
        )

    def take_suppressed_count(self) -> int:
        count = len(self._suppressed)
        self._suppressed.clear()
        return count

    def peek_suppressed_count(self) -> int:
        return len(self._suppressed)

    def record_send(self) -> None:
        self._rate.record_send()

    def can_send_non_critical(self, *, max_per_hour: int, max_per_day: int) -> bool:
        return self._rate.can_send(max_per_hour=max_per_hour, max_per_day=max_per_day)

    def mark_cooldown(
        self, event_type: str, subject: str, cooldown_seconds: float
    ) -> None:
        self._cooldown.allow(event_type, subject, cooldown_seconds)

    def add_to_batch(self, alert: PendingAlert) -> list[PendingAlert] | None:
        """Append to batch; return the full batch when this subject completes a duplicate slot."""
        batch = self._pending_batches.setdefault(alert.event_type, [])
        if any(a.subject == alert.subject for a in batch):
            return None
        batch.append(alert)
        return batch

    def pop_batch(self, event_type: str) -> list[PendingAlert]:
        return self._pending_batches.pop(event_type, [])

    def batch_size(self, event_type: str) -> int:
        return len(self._pending_batches.get(event_type, []))
