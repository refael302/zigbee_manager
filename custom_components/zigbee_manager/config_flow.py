"""Config flow for the Zigbee Manager integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    ALERT_TOGGLE_KEYS,
    CONF_ALERT_MAX_PER_DAY,
    CONF_ALERT_MAX_PER_HOUR,
    CONF_BASE_TOPIC,
    CONF_SILENT_THRESHOLD_HOURS,
    CONF_STARTUP_GRACE_MINUTES,
    CONF_TELEGRAM_CHAT_ID,
    CONF_TELEGRAM_COOLDOWN_MINUTES,
    DEFAULT_ALERT_MAX_PER_DAY,
    DEFAULT_ALERT_MAX_PER_HOUR,
    DEFAULT_BASE_TOPIC,
    DEFAULT_SILENT_THRESHOLD_HOURS,
    DEFAULT_STARTUP_GRACE_MINUTES,
    DEFAULT_TELEGRAM_COOLDOWN_MINUTES,
    DOMAIN,
    NAME,
)

_CHAT_ID_RE = re.compile(r"^-?\d+$")


def _valid_chat_id(value: str) -> bool:
    return not value or bool(_CHAT_ID_RE.fullmatch(value))


class ZigbeeManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step setup: Z2M base topic, then Telegram chat ID."""

    VERSION = 1

    def __init__(self) -> None:
        self._base_topic: str = DEFAULT_BASE_TOPIC

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Zigbee2MQTT base topic."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if "mqtt" not in self.hass.config.components:
                errors["base"] = "mqtt_not_configured"
            else:
                base_topic = (
                    user_input[CONF_BASE_TOPIC].strip().rstrip("/")
                    or DEFAULT_BASE_TOPIC
                )
                await self.async_set_unique_id(f"{DOMAIN}_{base_topic}")
                self._abort_if_unique_id_configured()
                self._base_topic = base_topic
                return await self.async_step_telegram()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_telegram(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Telegram chat ID (optional)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            chat_id = str(user_input.get(CONF_TELEGRAM_CHAT_ID) or "").strip()
            if not _valid_chat_id(chat_id):
                errors[CONF_TELEGRAM_CHAT_ID] = "invalid_chat_id"
            else:
                data = {
                    CONF_BASE_TOPIC: self._base_topic,
                    CONF_TELEGRAM_CHAT_ID: chat_id,
                }
                options = {key: True for key in ALERT_TOGGLE_KEYS}
                options[CONF_SILENT_THRESHOLD_HOURS] = DEFAULT_SILENT_THRESHOLD_HOURS
                options[CONF_TELEGRAM_COOLDOWN_MINUTES] = (
                    DEFAULT_TELEGRAM_COOLDOWN_MINUTES
                )
                options[CONF_ALERT_MAX_PER_HOUR] = DEFAULT_ALERT_MAX_PER_HOUR
                options[CONF_ALERT_MAX_PER_DAY] = DEFAULT_ALERT_MAX_PER_DAY
                options[CONF_STARTUP_GRACE_MINUTES] = DEFAULT_STARTUP_GRACE_MINUTES
                return self.async_create_entry(title=NAME, data=data, options=options)

        return self.async_show_form(
            step_id="telegram",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_TELEGRAM_CHAT_ID, default=""): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ZigbeeManagerOptionsFlow:
        return ZigbeeManagerOptionsFlow()


class ZigbeeManagerOptionsFlow(config_entries.OptionsFlow):
    """Edit chat ID, alert toggles and tuning values."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        merged = {**self.config_entry.data, **(self.config_entry.options or {})}

        if user_input is not None:
            chat_id = str(user_input.get(CONF_TELEGRAM_CHAT_ID) or "").strip()
            if not _valid_chat_id(chat_id):
                errors[CONF_TELEGRAM_CHAT_ID] = "invalid_chat_id"
            else:
                user_input[CONF_TELEGRAM_CHAT_ID] = chat_id
                return self.async_create_entry(title="", data=user_input)

        schema_dict: dict[Any, Any] = {
            vol.Optional(
                CONF_TELEGRAM_CHAT_ID,
                default=str(merged.get(CONF_TELEGRAM_CHAT_ID) or ""),
            ): str,
        }
        for key in ALERT_TOGGLE_KEYS:
            schema_dict[vol.Required(key, default=bool(merged.get(key, True)))] = bool
        schema_dict[
            vol.Required(
                CONF_SILENT_THRESHOLD_HOURS,
                default=merged.get(
                    CONF_SILENT_THRESHOLD_HOURS, DEFAULT_SILENT_THRESHOLD_HOURS
                ),
            )
        ] = vol.All(vol.Coerce(float), vol.Range(min=1, max=168))
        schema_dict[
            vol.Required(
                CONF_TELEGRAM_COOLDOWN_MINUTES,
                default=merged.get(
                    CONF_TELEGRAM_COOLDOWN_MINUTES, DEFAULT_TELEGRAM_COOLDOWN_MINUTES
                ),
            )
        ] = vol.All(vol.Coerce(float), vol.Range(min=0, max=1440))
        schema_dict[
            vol.Required(
                CONF_ALERT_MAX_PER_HOUR,
                default=merged.get(
                    CONF_ALERT_MAX_PER_HOUR, DEFAULT_ALERT_MAX_PER_HOUR
                ),
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=10))
        schema_dict[
            vol.Required(
                CONF_ALERT_MAX_PER_DAY,
                default=merged.get(CONF_ALERT_MAX_PER_DAY, DEFAULT_ALERT_MAX_PER_DAY),
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=20))
        schema_dict[
            vol.Required(
                CONF_STARTUP_GRACE_MINUTES,
                default=merged.get(
                    CONF_STARTUP_GRACE_MINUTES, DEFAULT_STARTUP_GRACE_MINUTES
                ),
            )
        ] = vol.All(vol.Coerce(float), vol.Range(min=0, max=60))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )
