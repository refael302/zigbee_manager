"""In-memory ring buffer of alerts and Z2M bridge log lines for the system log sensor."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from .const import LOG_BUFFER_MAX


class IntegrationLog:
    """Keeps the most recent alerts/log lines, newest first in `entries()`."""

    def __init__(self, max_entries: int = LOG_BUFFER_MAX) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_entries)

    def add(
        self,
        message: str,
        *,
        level: str = "info",
        event_type: str | None = None,
        source: str = "zigbee_manager",
    ) -> dict[str, Any]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event_type": event_type,
            "source": source,
            "message": message,
        }
        self._buffer.append(record)
        return record

    def add_bridge_log(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Record a `{base}/bridge/logging` message ({level, message, namespace})."""
        message = payload.get("message")
        if not message:
            return None
        return self.add(
            str(message),
            level=str(payload.get("level") or "info"),
            source=str(payload.get("namespace") or "z2m"),
        )

    @property
    def latest(self) -> dict[str, Any] | None:
        return self._buffer[-1] if self._buffer else None

    def entries(self) -> list[dict[str, Any]]:
        """All records, newest first."""
        return list(reversed(self._buffer))
