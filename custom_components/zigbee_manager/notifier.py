"""Telegram alert delivery via the HA telegram_bot integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .alert_format import format_alert, format_digest_alert, group_descriptions_by_type
from .alert_engine import PendingAlert
from .const import CONF_TELEGRAM_CHAT_ID, EVENT_TOGGLE_MAP

_LOGGER = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends formatted alerts, honoring per-event toggles."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id

    def _config(self) -> dict:
        entry = self._hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return {}
        return {**entry.data, **(entry.options or {})}

    def is_enabled(self, event_type: str) -> bool:
        """Return True when Telegram is configured and the event toggle is on."""
        cfg = self._config()
        chat_id = str(cfg.get(CONF_TELEGRAM_CHAT_ID) or "").strip()
        if not chat_id:
            return False
        toggle_key = EVENT_TOGGLE_MAP.get(event_type)
        if toggle_key is not None and not cfg.get(toggle_key, True):
            return False
        return True

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
        critical: bool = False,
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
            critical=critical,
        )
        await self._async_deliver(chat_id, message)

    async def async_send_digest(
        self,
        items: list[PendingAlert],
        active: int,
        total: int,
        *,
        startup: bool = False,
        bridge_online: bool | None = None,
        ha_active: int = 0,
        ha_linked: int = 0,
    ) -> None:
        """Send one digest message covering several queued alerts."""
        cfg = self._config()
        chat_id = str(cfg.get(CONF_TELEGRAM_CHAT_ID) or "").strip()
        if not chat_id or not items:
            return
        grouped = group_descriptions_by_type(
            [(item.event_type, item.description) for item in items]
        )
        message = format_digest_alert(
            grouped,
            active,
            total,
            startup=startup,
            bridge_online=bridge_online,
            ha_active=ha_active,
            ha_linked=ha_linked,
        )
        await self._async_deliver(chat_id, message)

    async def _async_deliver(self, chat_id: str, message: str) -> None:
        try:
            await self._hass.services.async_call(
                "telegram_bot",
                "send_message",
                {"message": message, "target": int(chat_id)},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - never break state updates on notify failure
            _LOGGER.warning("Zigbee Manager: failed to send Telegram alert: %s", err)
