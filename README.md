# Zigbee Manager

A Home Assistant custom integration that monitors your **Zigbee2MQTT** network and sends Hebrew **Telegram alerts** when something changes — devices joining, dropping off, going silent, or the whole bridge going down.

This integration is a monitoring and alerting layer. It does not create device entities (lights, switches, etc.) — that remains the job of the regular Zigbee2MQTT/MQTT integration.

## Sensors

| Entity | State | Notable attributes |
|--------|-------|--------------------|
| `sensor.zigbee_manager_total_devices` | Number of devices in the network (excluding the coordinator) | `bridge_online`, `z2m_version` |
| `sensor.zigbee_manager_active_devices` | Devices currently online | `total`, `offline_devices`, `ratio` |
| `sensor.zigbee_manager_device_registry` | Device count | `devices` — per-device dict: IEEE, vendor, model, type, availability, `last_seen`, interview state |
| `sensor.zigbee_manager_bridge_uptime` | Seconds since the Z2M bridge last started | `started_at`, `estimated`, `coordinator_type`, `network_channel` |
| `sensor.zigbee_manager_system_log` | Latest alert / bridge log line | `alerts` — recent history (up to 50 records) |

## Telegram alerts

Alerts are sent through the Home Assistant [Telegram Bot](https://www.home-assistant.io/integrations/telegram_bot/) integration, which must be configured first. You only provide the destination chat ID.

Message format:

```
מערכת ניהול זיגבי
התראה: מכשיר התנתק מהרשת
תיאור: מכשיר my_plug (0x00158d00018255df) התנתק מהרשת
סטטוס נוכחי: 18/22 מכשירים פעילים
```

Alert types (each can be toggled in the integration options):

- Device joined the network
- Device became unavailable
- Device silent for more than 24 hours (threshold configurable)
- Device removed from the network
- Zigbee network went down (bridge offline)
- Zigbee network recovered (bridge online)

A per-device cooldown (default 5 minutes) prevents alert spam.

## Requirements

1. Home Assistant 2024.1 or newer with the **MQTT** integration connected to the same broker as Zigbee2MQTT.
2. The **Telegram Bot** integration configured (for alerts; optional).
3. Zigbee2MQTT with availability and last-seen reporting enabled in its `configuration.yaml`:

```yaml
availability:
  enabled: true

advanced:
  last_seen: ISO_8601
```

`last_seen` is required for the "device silent" detection. Without it, the integration falls back to the time it last received any MQTT message from the device.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/refael302/zigbee_manager` as an Integration.
3. Install **Zigbee Manager** and restart Home Assistant.

### Manual

Copy `custom_components/zigbee_manager/` into your Home Assistant `config/custom_components/` folder and restart.

## Configuration

Settings → Devices & Services → Add Integration → **Zigbee Manager**:

1. **Zigbee2MQTT base topic** — default `zigbee2mqtt`; change it only if you changed `base_topic` in Z2M.
2. **Telegram chat ID** — the chat that receives alerts (e.g. `-1001234567890`). Leave empty to disable Telegram alerts.

All alert toggles, the silent-hours threshold, and the cooldown can be changed later via the integration's **Configure** dialog.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

On Windows, `push_to_github.bat` stages, commits (interactive message prompt) and pushes to `main`; `pull_from_github.bat` pulls the latest `main`.
