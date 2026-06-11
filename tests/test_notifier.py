"""Tests for the Hebrew alert format and digest messages."""

from __future__ import annotations

from zigbee_manager.alert_format import (
    format_alert,
    format_digest_alert,
    format_status_line,
    group_descriptions_by_type,
)
from zigbee_manager.const import (
    EVENT_BRIDGE_OFFLINE,
    EVENT_DEVICE_HA_MISMATCH,
    EVENT_DEVICE_UNAVAILABLE,
)


def test_format_alert_structure():
    msg = format_alert(
        EVENT_DEVICE_UNAVAILABLE,
        "מכשיר my_plug (0x1) התנתק מהרשת",
        18,
        22,
        ha_active=17,
        ha_linked=22,
    )
    lines = msg.split("\n")
    assert lines[0] == "מערכת ניהול זיגבי"
    assert lines[1] == "התראה: מכשיר התנתק מהרשת"
    assert lines[2] == "תיאור: מכשיר my_plug (0x1) התנתק מהרשת"
    assert lines[3] == "סטטוס Z2M: 18/22 מכשירים פעילים"


def test_format_alert_unknown_event_uses_raw_type():
    msg = format_alert("custom_event", "desc", 1, 1)
    assert "התראה: custom_event" in msg


def test_format_alert_bridge_offline_shows_zero_active():
    msg = format_alert(
        EVENT_BRIDGE_OFFLINE,
        "גשר ה-Zigbee2MQTT הפסיק להגיב",
        0,
        56,
        ha_active=52,
        ha_linked=56,
    )
    assert "סטטוס Z2M: 0/56 מכשירים פעילים (גשר לא זמין)" in msg
    assert "סטטוס HA: 52/56 מכשירים פעילים ב-MQTT" in msg


def test_format_alert_dual_status():
    msg = format_alert(
        EVENT_DEVICE_UNAVAILABLE,
        "desc",
        50,
        56,
        ha_active=48,
        ha_linked=55,
    )
    assert "סטטוס Z2M: 50/56" in msg
    assert "סטטוס HA: 48/55" in msg
    assert "(1 מכשירים ב-Z2M לא נמצאו ב-Home Assistant)" in msg


def test_format_alert_critical():
    msg = format_alert(
        EVENT_BRIDGE_OFFLINE,
        "גשר לא זמין",
        0,
        56,
        critical=True,
    )
    assert "⚠️ אירוע קריטי" in msg


def test_format_digest_alert_multiple_sections():
    grouped = group_descriptions_by_type(
        [
            (EVENT_DEVICE_UNAVAILABLE, "מכשיר a"),
            (EVENT_DEVICE_UNAVAILABLE, "מכשיר b"),
            (EVENT_DEVICE_HA_MISMATCH, "מכשיר c"),
        ]
    )
    msg = format_digest_alert(grouped, 10, 12)
    assert "סיכום התראות" in msg
    assert "מכשיר התנתק מהרשת (2)" in msg
    assert "מכשיר a" in msg
    assert "חוסר התאמה" in msg


def test_format_digest_startup_title():
    grouped = group_descriptions_by_type(
        [(EVENT_DEVICE_UNAVAILABLE, "מכשיר a")]
    )
    msg = format_digest_alert(grouped, 10, 12, startup=True)
    assert "סיכום הפעלה (דקה ראשונה)" in msg


def test_format_status_line_bridge_offline_no_devices():
    assert (
        format_status_line(0, 0, bridge_online=False)
        == "סטטוס Z2M: גשר לא זמין"
    )
