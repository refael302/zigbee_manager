"""Telegram alert delivery via the HA telegram_bot integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .alert_format import AlertCooldown, format_alert
from .const import (
    CONF_TELEGRAM_CHAT_ID,
    CONF_TELEGRAM_COOLDOWN_MINUTES,
    DEFAULT_TELEGRAM_COOLDOWN_MINUTES,
    EVENT_TOGGLE_MAP,
)

_LOGGER = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends formatted alerts, honoring per-event toggles and an anti-spam cooldown."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._cooldown = AlertCooldown()

    def _config(self) -> dict:
        entry = self._hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return {}
        return {**entry.data, **(entry.options or {})}

    def should_send(self, event_type: str, subject: str = "") -> bool:
        """Check toggle + cooldown without sending. Updates the cooldown clock when True."""
        cfg = self._config()
        chat_id = str(cfg.get(CONF_TELEGRAM_CHAT_ID) or "").strip()
        if not chat_id:
            return False
        toggle_key = EVENT_TOGGLE_MAP.get(event_type)
        if toggle_key is not None and not cfg.get(toggle_key, True):
            return False

        try:
            cooldown_min = float(
                cfg.get(
                    CONF_TELEGRAM_COOLDOWN_MINUTES, DEFAULT_TELEGRAM_COOLDOWN_MINUTES
                )
            )
        except (TypeError, ValueError):
            cooldown_min = DEFAULT_TELEGRAM_COOLDOWN_MINUTES
        return self._cooldown.allow(event_type, subject, cooldown_min * 60)

    async def async_send(
        self,
        event_type: str,
        description: str,
        active: int,
        total: int,
        *,
        bridge_online: bool | None = None,
        ha_active: int = 0,
        ha_linked: int = 0,
    ) -> None:
        """Send a formatted alert message to the configured chat."""
        cfg = self._config()
        chat_id = str(cfg.get(CONF_TELEGRAM_CHAT_ID) or "").strip()
        if not chat_id:
            return
        message = format_alert(
            event_type,
            description,
            active,
            total,
            bridge_online=bridge_online,
            ha_active=ha_active,
            ha_linked=ha_linked,
        )
        try:
            await self._hass.services.async_call(
                "telegram_bot",
                "send_message",
                {"message": message, "target": int(chat_id)},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - never break state updates on notify failure
            _LOGGER.warning("Zigbee Manager: failed to send Telegram alert: %s", err)
