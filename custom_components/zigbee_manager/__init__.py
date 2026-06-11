"""Zigbee Manager: monitoring and alerting layer for a Zigbee2MQTT network."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC, DOMAIN, PLATFORMS
from .coordinator import ZigbeeManagerCoordinator
from .mqtt_bridge import async_subscribe_z2m

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Zigbee Manager from a config entry."""
    coordinator = ZigbeeManagerCoordinator(hass, entry)

    base_topic = entry.data.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC)
    unsubs = await async_subscribe_z2m(hass, coordinator, base_topic)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "unsubs": unsubs,
    }

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data:
            for unsub in data["unsubs"]:
                unsub()
    return unload_ok
