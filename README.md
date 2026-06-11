# Zigbee Manager

A Home Assistant custom integration that monitors your **Zigbee2MQTT** network and sends Hebrew **Telegram alerts** when something changes — devices joining, dropping off, going silent, or the whole bridge going down.

This integration is a monitoring and alerting layer. It does not create device entities (lights, switches, etc.) — that remains the job of the regular Zigbee2MQTT/MQTT integration.

## Sensors

| Entity | State | Notable attributes |
|--------|-------|--------------------|
| `sensor.zigbee_manager_total_devices` | Number of devices in the network (excluding the coordinator) | `bridge_online`, `z2m_version` |
| `sensor.zigbee_manager_active_devices` | Devices active per Z2M (MQTT availability) | `total`, `offline_devices`, `ha_active`, `ha_linked` |
| `sensor.zigbee_manager_active_devices_ha` | Devices with available MQTT entities in HA | `not_linked_in_ha`, `ha_inactive_devices`, `mismatch_devices` |
| `sensor.zigbee_manager_device_registry` | Device count | `devices` — per-device dict: IEEE, vendor, model, type, availability, `last_seen`, interview state |
| `sensor.zigbee_manager_system_log` | Latest alert / bridge log line | `alerts` — recent history (up to 50 records) |

## Button

| Entity | Action |
|--------|--------|
| `button.zigbee_manager_reset_device_snapshot` | Save the **current** Z2M device list as the persisted baseline (clears “vanished” tracking). Use after you accept that missing devices are gone for good. |

## Vanished devices (persisted baseline)

The integration stores the last known device list on disk. After a Home Assistant restart, if devices that were in the baseline are missing from Z2M’s `bridge/devices` list, you get a **startup-only** Telegram alert (same toggle as “device removed”). Each missing device is alerted **at most once per calendar day** until you press **Reset device snapshot**.

- Live join/remove while HA is running updates the baseline automatically.
- First install seeds the baseline from the current list (no alert flood).

## Telegram alerts

Alerts are sent through the Home Assistant [Telegram Bot](https://www.home-assistant.io/integrations/telegram_bot/) integration, which must be configured first. You only provide the destination chat ID.

Message format:

```
מערכת ניהול זיגבי
התראה: מכשיר התנתק מהרשת
תיאור: מכשיר my_plug (0x00158d00018255df) התנתק מהרשת
סטטוס Z2M: 18/22 מכשירים פעילים
סטטוס HA: 17/22 מכשירים פעילים ב-MQTT
```

Devices are matched to Home Assistant via the **MQTT device registry** using IEEE address, friendly name (`zigbee2mqtt` identifiers), device name, and MQTT entity `unique_id` fallbacks. Disabled MQTT entities are detected; disabling a device in HA triggers a Z2M/HA mismatch alert when the toggle is enabled.

Alert types (each can be toggled in the integration options):

- Device joined the network
- Device became unavailable
- Device silent for more than 24 hours (threshold configurable)
- Device removed from the network
- Zigbee network went down (bridge offline)
- Zigbee network recovered (bridge online)
- Device not found in Home Assistant (MQTT)
- Z2M / Home Assistant status mismatch

Anti-spam (fixed, not configurable in the UI):

- **1-minute startup grace** — events are collected, then one startup summary is sent.
- **5-minute digest gate** — at most one combined Telegram message every 5 minutes; events are grouped, not dropped.
- **Bridge offline/online** — sent immediately (critical).
- **Bridge incident** — while the bridge is down, per-device unavailable/mismatch alerts are logged only.

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

All alert toggles and the silent-hours threshold can be changed later via the integration's **Configure** dialog.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

On Windows, `push_to_github.bat` stages, commits (interactive message prompt) and pushes to `main`; `pull_from_github.bat` pulls the latest `main`.
