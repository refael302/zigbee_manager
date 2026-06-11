"""Constants for the Zigbee Manager integration."""

from __future__ import annotations

DOMAIN = "zigbee_manager"
NAME = "Zigbee Manager"

# Config entry data
CONF_BASE_TOPIC = "base_topic"
CONF_TELEGRAM_CHAT_ID = "telegram_chat_id"

DEFAULT_BASE_TOPIC = "zigbee2mqtt"

# Options: alert toggles
CONF_ALERT_DEVICE_JOINED = "alert_device_joined"
CONF_ALERT_DEVICE_UNAVAILABLE = "alert_device_unavailable"
CONF_ALERT_DEVICE_SILENT = "alert_device_silent_24h"
CONF_ALERT_DEVICE_REMOVED = "alert_device_removed"
CONF_ALERT_BRIDGE_OFFLINE = "alert_bridge_offline"
CONF_ALERT_BRIDGE_ONLINE = "alert_bridge_online"
CONF_ALERT_DEVICE_NOT_IN_HA = "alert_device_not_in_ha"
CONF_ALERT_DEVICE_HA_MISMATCH = "alert_device_ha_mismatch"

ALERT_TOGGLE_KEYS: tuple[str, ...] = (
    CONF_ALERT_DEVICE_JOINED,
    CONF_ALERT_DEVICE_UNAVAILABLE,
    CONF_ALERT_DEVICE_SILENT,
    CONF_ALERT_DEVICE_REMOVED,
    CONF_ALERT_BRIDGE_OFFLINE,
    CONF_ALERT_BRIDGE_ONLINE,
    CONF_ALERT_DEVICE_NOT_IN_HA,
    CONF_ALERT_DEVICE_HA_MISMATCH,
)

# Options: tuning
CONF_SILENT_THRESHOLD_HOURS = "silent_threshold_hours"
CONF_TELEGRAM_COOLDOWN_MINUTES = "telegram_cooldown_minutes"
CONF_ALERT_MAX_PER_HOUR = "alert_max_per_hour"
CONF_ALERT_MAX_PER_DAY = "alert_max_per_day"
CONF_STARTUP_GRACE_MINUTES = "startup_grace_minutes"

DEFAULT_SILENT_THRESHOLD_HOURS = 24
DEFAULT_TELEGRAM_COOLDOWN_MINUTES = 5
DEFAULT_ALERT_MAX_PER_HOUR = 1
DEFAULT_ALERT_MAX_PER_DAY = 4
DEFAULT_STARTUP_GRACE_MINUTES = 10

# Event types (internal)
EVENT_DEVICE_JOINED = "device_joined"
EVENT_DEVICE_UNAVAILABLE = "device_unavailable"
EVENT_DEVICE_AVAILABLE = "device_available"
EVENT_DEVICE_SILENT = "device_silent"
EVENT_DEVICE_REMOVED = "device_removed"
EVENT_BRIDGE_OFFLINE = "bridge_offline"
EVENT_BRIDGE_ONLINE = "bridge_online"
EVENT_DEVICE_NOT_IN_HA = "device_not_in_ha"
EVENT_DEVICE_HA_MISMATCH = "device_ha_mismatch"

# Map event type -> options toggle key that controls its Telegram alert
EVENT_TOGGLE_MAP: dict[str, str] = {
    EVENT_DEVICE_JOINED: CONF_ALERT_DEVICE_JOINED,
    EVENT_DEVICE_UNAVAILABLE: CONF_ALERT_DEVICE_UNAVAILABLE,
    EVENT_DEVICE_SILENT: CONF_ALERT_DEVICE_SILENT,
    EVENT_DEVICE_REMOVED: CONF_ALERT_DEVICE_REMOVED,
    EVENT_BRIDGE_OFFLINE: CONF_ALERT_BRIDGE_OFFLINE,
    EVENT_BRIDGE_ONLINE: CONF_ALERT_BRIDGE_ONLINE,
    EVENT_DEVICE_NOT_IN_HA: CONF_ALERT_DEVICE_NOT_IN_HA,
    EVENT_DEVICE_HA_MISMATCH: CONF_ALERT_DEVICE_HA_MISMATCH,
}

# Hebrew alert titles per event type
EVENT_TITLES_HE: dict[str, str] = {
    EVENT_DEVICE_JOINED: "מכשיר הצטרף לרשת",
    EVENT_DEVICE_UNAVAILABLE: "מכשיר התנתק מהרשת",
    EVENT_DEVICE_AVAILABLE: "מכשיר חזר לרשת",
    EVENT_DEVICE_SILENT: "מכשיר לא תקשר מעל 24 שעות",
    EVENT_DEVICE_REMOVED: "מכשיר נמחק מהרשת",
    EVENT_BRIDGE_OFFLINE: "רשת זיגבי נפלה",
    EVENT_BRIDGE_ONLINE: "רשת זיגבי חזרה לפעילות",
    EVENT_DEVICE_NOT_IN_HA: "מכשיר לא נמצא ב-Home Assistant",
    EVENT_DEVICE_HA_MISMATCH: "חוסר התאמה Z2M / Home Assistant",
}

# System log ring buffer
LOG_BUFFER_MAX = 50
LOG_STATE_MAX_LEN = 255

# Periodic tick interval (seconds) for silent-device checks and uptime refresh
UPDATE_INTERVAL_SECONDS = 60

# Devices above this count get a trimmed registry attribute payload (HA ~16KB limit)
REGISTRY_ATTR_DEVICE_LIMIT = 200

PLATFORMS: list[str] = ["sensor"]
