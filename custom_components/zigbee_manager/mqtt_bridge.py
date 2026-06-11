"""MQTT subscriptions: routes Zigbee2MQTT topics to the coordinator."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

from .coordinator import ZigbeeManagerCoordinator

_LOGGER = logging.getLogger(__name__)


def _decode(payload: str | bytes) -> Any:
    """Decode an MQTT payload: JSON when possible, otherwise the raw string."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    text = payload.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


async def async_subscribe_z2m(
    hass: HomeAssistant,
    coordinator: ZigbeeManagerCoordinator,
    base_topic: str,
) -> list[Callable[[], None]]:
    """Subscribe to all required Z2M topics; returns unsubscribe callbacks."""
    base = base_topic.rstrip("/")
    unsubs: list[Callable[[], None]] = []

    def _task(coro: Any) -> None:
        hass.async_create_task(coro)

    @callback
    def on_bridge_state(msg: mqtt.ReceiveMessage) -> None:
        _task(coordinator.async_handle_bridge_state(_decode(msg.payload)))

    @callback
    def on_bridge_devices(msg: mqtt.ReceiveMessage) -> None:
        _task(coordinator.async_handle_bridge_devices(_decode(msg.payload)))

    @callback
    def on_bridge_event(msg: mqtt.ReceiveMessage) -> None:
        _task(coordinator.async_handle_bridge_event(_decode(msg.payload)))

    @callback
    def on_bridge_info(msg: mqtt.ReceiveMessage) -> None:
        _task(coordinator.async_handle_bridge_info(_decode(msg.payload)))

    @callback
    def on_bridge_logging(msg: mqtt.ReceiveMessage) -> None:
        _task(coordinator.async_handle_bridge_logging(_decode(msg.payload)))

    @callback
    def on_availability(msg: mqtt.ReceiveMessage) -> None:
        # topic: {base}/FRIENDLY_NAME/availability — friendly names may contain '/'
        topic = msg.topic
        name = topic[len(base) + 1 : -len("/availability")]
        if not name or name == "bridge" or name.startswith("bridge/"):
            return
        _task(coordinator.async_handle_availability(name, _decode(msg.payload)))

    @callback
    def on_device_message(msg: mqtt.ReceiveMessage) -> None:
        # topic: {base}/FRIENDLY_NAME — used only to refresh last_seen
        name = msg.topic[len(base) + 1 :]
        if not name or name == "bridge" or "/" in name:
            return
        _task(coordinator.async_handle_device_message(name, _decode(msg.payload)))

    subscriptions: list[tuple[str, Callable[[mqtt.ReceiveMessage], None]]] = [
        (f"{base}/bridge/state", on_bridge_state),
        (f"{base}/bridge/devices", on_bridge_devices),
        (f"{base}/bridge/event", on_bridge_event),
        (f"{base}/bridge/info", on_bridge_info),
        (f"{base}/bridge/logging", on_bridge_logging),
        (f"{base}/+/availability", on_availability),
        (f"{base}/+", on_device_message),
    ]
    for topic, handler in subscriptions:
        unsubs.append(await mqtt.async_subscribe(hass, topic, handler))
    _LOGGER.debug("Zigbee Manager subscribed to %d topics under '%s'", len(unsubs), base)
    return unsubs
