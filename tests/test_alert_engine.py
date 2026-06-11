"""Tests for the Telegram anti-spam alert engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from zigbee_manager.alert_engine import (
    AlertEngine,
    SuppressReason,
    TelegramAction,
)
from zigbee_manager.const import (
    EVENT_BRIDGE_OFFLINE,
    EVENT_DEVICE_HA_MISMATCH,
    EVENT_DEVICE_UNAVAILABLE,
)


def _engine(minutes_ago: float = 60) -> AlertEngine:
    started = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return AlertEngine(started_at=started)


def _plan(engine: AlertEngine, event_type: str, subject: str = "0x1"):
    return engine.plan_telegram(
        event_type,
        subject,
        startup_grace_minutes=10,
        max_per_hour=1,
        max_per_day=4,
        cooldown_seconds=300,
    )


def test_startup_grace_suppresses_ha_mismatch():
    engine = _engine(minutes_ago=2)
    plan = _plan(engine, EVENT_DEVICE_HA_MISMATCH)
    assert plan.action == TelegramAction.SUPPRESS
    assert plan.reason == SuppressReason.STARTUP_GRACE


def test_after_grace_allows_batch_for_unavailable():
    engine = _engine(minutes_ago=15)
    plan = _plan(engine, EVENT_DEVICE_UNAVAILABLE)
    assert plan.action == TelegramAction.BATCH


def test_bridge_incident_suppresses_per_device():
    engine = _engine(minutes_ago=15)
    engine.set_bridge_incident(True)
    plan = _plan(engine, EVENT_DEVICE_UNAVAILABLE)
    assert plan.action == TelegramAction.SUPPRESS
    assert plan.reason == SuppressReason.BRIDGE_INCIDENT


def test_critical_bypasses_rate_limit():
    engine = _engine(minutes_ago=15)
    engine.record_send()
    plan = _plan(engine, EVENT_BRIDGE_OFFLINE, subject="bridge")
    assert plan.action == TelegramAction.SEND_CRITICAL


def test_rate_limit_after_one_send():
    engine = _engine(minutes_ago=15)
    engine.record_send()
    plan = _plan(engine, EVENT_DEVICE_UNAVAILABLE)
    assert plan.action == TelegramAction.SUPPRESS
    assert plan.reason == SuppressReason.RATE_LIMIT


def test_daily_limit():
    engine = _engine(minutes_ago=15)
    now = datetime.now(timezone.utc).timestamp()
    engine._rate._send_times = [
        now - 3600 * 2,
        now - 3600 * 4,
        now - 3600 * 6,
        now - 3600 * 8,
    ]
    plan = _plan(engine, EVENT_DEVICE_UNAVAILABLE)
    assert plan.action == TelegramAction.SUPPRESS
    assert plan.reason == SuppressReason.RATE_LIMIT


def test_end_startup_grace():
    engine = _engine(minutes_ago=2)
    assert engine.in_startup_grace(10)
    engine.end_startup_grace()
    assert not engine.in_startup_grace(10)


def test_suppressed_count_and_take():
    engine = _engine(minutes_ago=15)
    engine.record_suppressed(EVENT_DEVICE_UNAVAILABLE, "desc", SuppressReason.RATE_LIMIT)
    assert engine.peek_suppressed_count() == 1
    assert engine.take_suppressed_count() == 1
    assert engine.peek_suppressed_count() == 0
