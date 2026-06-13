"""Tests for the Telegram anti-spam alert engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from typing import Callable

from zigbee_manager.alert_engine import (
    AlertEngine,
    PendingAlert,
    SuppressReason,
    TelegramAction,
)
from zigbee_manager.const import (
    EVENT_BRIDGE_OFFLINE,
    EVENT_DEVICE_HA_MISMATCH,
    EVENT_DEVICE_JOINED,
    EVENT_DEVICE_UNAVAILABLE,
    EVENT_NETWORK_STALE,
    TELEGRAM_DIGEST_INTERVAL_SECONDS,
)


def _engine(
    minutes_ago: float = 60,
    *,
    clock: Callable[[], float] | None = None,
) -> AlertEngine:
    started = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    clk = clock or (lambda: datetime.now(timezone.utc).timestamp())
    return AlertEngine(started_at=started, clock=clk)


def _plan(engine: AlertEngine, event_type: str, subject: str = "0x1"):
    return engine.plan_telegram(event_type, subject)


def test_bridge_incident_suppresses_per_device():
    engine = _engine(minutes_ago=15)
    engine.set_bridge_incident(True)
    plan = _plan(engine, EVENT_DEVICE_UNAVAILABLE)
    assert plan.action == TelegramAction.SUPPRESS
    assert plan.reason == SuppressReason.BRIDGE_INCIDENT


def test_critical_bypasses_digest():
    engine = _engine(minutes_ago=15)
    plan = _plan(engine, EVENT_BRIDGE_OFFLINE, subject="bridge")
    assert plan.action == TelegramAction.SEND_CRITICAL


def test_network_stale_is_critical():
    engine = _engine(minutes_ago=15)
    engine.record_send()
    plan = _plan(engine, EVENT_NETWORK_STALE, subject="network")
    assert plan.action == TelegramAction.SEND_CRITICAL


def test_non_critical_enqueues():
    engine = _engine(minutes_ago=15)
    plan = _plan(engine, EVENT_DEVICE_UNAVAILABLE)
    assert plan.action == TelegramAction.ENQUEUE


def test_startup_grace_active():
    engine = _engine(minutes_ago=0.5)
    assert engine.in_startup_grace()


def test_end_startup_grace():
    engine = _engine(minutes_ago=0.5)
    assert engine.in_startup_grace()
    engine.end_startup_grace()
    assert not engine.in_startup_grace()


def test_enqueue_dedup_same_subject():
    engine = _engine(minutes_ago=15)
    engine.enqueue(
        PendingAlert(EVENT_DEVICE_UNAVAILABLE, "0x1", "first")
    )
    engine.enqueue(
        PendingAlert(EVENT_DEVICE_UNAVAILABLE, "0x1", "second")
    )
    assert engine.digest_pending() == 1
    items = engine.pop_digest()
    assert len(items) == 1
    assert items[0].description == "second"


def test_global_gate_blocks_until_interval():
    now = [1_000_000.0]
    engine = _engine(minutes_ago=15, clock=lambda: now[0])
    engine.record_send()
    assert not engine.can_flush_digest()
    assert engine.seconds_until_flush() == TELEGRAM_DIGEST_INTERVAL_SECONDS
    now[0] += TELEGRAM_DIGEST_INTERVAL_SECONDS
    engine.enqueue(PendingAlert(EVENT_DEVICE_JOINED, "0x2", "joined"))
    assert engine.can_flush_digest()


def test_digest_not_flushable_during_startup_grace():
    engine = _engine(minutes_ago=0.5)
    engine.enqueue(PendingAlert(EVENT_DEVICE_JOINED, "0x1", "joined"))
    assert engine.digest_pending() == 1
    assert not engine.can_flush_digest()


def test_multiple_event_types_in_digest():
    engine = _engine(minutes_ago=15)
    engine.enqueue(PendingAlert(EVENT_DEVICE_UNAVAILABLE, "0x1", "a"))
    engine.enqueue(PendingAlert(EVENT_DEVICE_HA_MISMATCH, "0x2", "b"))
    assert engine.digest_pending() == 2
