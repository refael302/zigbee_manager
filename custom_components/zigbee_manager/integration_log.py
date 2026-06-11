"""In-memory ring buffer of integration alerts for the system log sensor."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from .const import LOG_BUFFER_MAX

INTEGRATION_SOURCE = "zigbee_manager"


class IntegrationLog:
    """Keeps the most recent integration alerts, newest first in `entries()`."""

    def __init__(self, max_entries: int = LOG_BUFFER_MAX) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_entries)

    def add(
        self,
        message: str,
        *,
        level: str = "info",
        event_type: str | None = None,
        source: str = INTEGRATION_SOURCE,
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

    @property
    def latest(self) -> dict[str, Any] | None:
        return self._buffer[-1] if self._buffer else None

    def entries(self) -> list[dict[str, Any]]:
        """All integration records, newest first."""
        return list(reversed(self._buffer))
