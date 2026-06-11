"""Tests for the Hebrew alert format and the anti-spam cooldown."""

from __future__ import annotations

from zigbee_manager.alert_format import (
    AlertCooldown,
    format_alert,
    format_status_line,
)
from zigbee_manager.const import (
    EVENT_BRIDGE_OFFLINE,
    EVENT_DEVICE_UNAVAILABLE,
)


def test_format_alert_structure():
    msg = format_alert(
        EVENT_DEVICE_UNAVAILABLE, "מכשיר my_plug (0x1) התנתק מהרשת", 18, 22
    )
    lines = msg.split("\n")
    assert lines[0] == "מערכת ניהול זיגבי"
    assert lines[1] == "התראה: מכשיר התנתק מהרשת"
    assert lines[2] == "תיאור: מכשיר my_plug (0x1) התנתק מהרשת"
    assert lines[3] == "סטטוס נוכחי: 18/22 מכשירים פעילים"


def test_format_alert_unknown_event_uses_raw_type():
    msg = format_alert("custom_event", "desc", 1, 1)
    assert "התראה: custom_event" in msg


def test_cooldown_blocks_repeats():
    now = [0.0]
    cd = AlertCooldown(clock=lambda: now[0])
    assert cd.allow(EVENT_DEVICE_UNAVAILABLE, "0x1", 300)
    assert not cd.allow(EVENT_DEVICE_UNAVAILABLE, "0x1", 300)
    now[0] = 299.0
    assert not cd.allow(EVENT_DEVICE_UNAVAILABLE, "0x1", 300)
    now[0] = 301.0
    assert cd.allow(EVENT_DEVICE_UNAVAILABLE, "0x1", 300)


def test_cooldown_is_per_event_and_subject():
    now = [0.0]
    cd = AlertCooldown(clock=lambda: now[0])
    assert cd.allow(EVENT_DEVICE_UNAVAILABLE, "0x1", 300)
    # Different subject and different event are independent
    assert cd.allow(EVENT_DEVICE_UNAVAILABLE, "0x2", 300)
    assert cd.allow(EVENT_BRIDGE_OFFLINE, "bridge", 300)


def test_cooldown_zero_always_allows():
    now = [0.0]
    cd = AlertCooldown(clock=lambda: now[0])
    assert cd.allow(EVENT_DEVICE_UNAVAILABLE, "0x1", 0)
    assert cd.allow(EVENT_DEVICE_UNAVAILABLE, "0x1", 0)


def test_format_alert_bridge_offline_shows_zero_active():
    msg = format_alert(
        EVENT_BRIDGE_OFFLINE,
        "גשר ה-Zigbee2MQTT הפסיק להגיב",
        0,
        56,
    )
    assert "סטטוס נוכחי: 0/56 מכשירים פעילים (גשר לא זמין)" in msg


def test_format_status_line_bridge_offline_no_devices():
    assert (
        format_status_line(0, 0, bridge_online=False)
        == "סטטוס נוכחי: גשר לא זמין — אין מידע על מכשירים"
    )
