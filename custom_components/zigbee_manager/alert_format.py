"""Pure helpers for alert formatting (unit-testable, no HA imports)."""

from __future__ import annotations

from collections import defaultdict

from .const import (
    EVENT_BRIDGE_OFFLINE,
    EVENT_DEVICE_HA_MISMATCH,
    EVENT_DEVICE_JOINED,
    EVENT_DEVICE_NOT_IN_HA,
    EVENT_DEVICE_REMOVED,
    EVENT_DEVICE_SILENT,
    EVENT_DEVICE_UNAVAILABLE,
    EVENT_TITLES_HE,
)

HEADER = "מערכת ניהול זיגבי"

DIGEST_EVENT_ORDER: tuple[str, ...] = (
    EVENT_DEVICE_UNAVAILABLE,
    EVENT_DEVICE_HA_MISMATCH,
    EVENT_DEVICE_NOT_IN_HA,
    EVENT_DEVICE_JOINED,
    EVENT_DEVICE_REMOVED,
    EVENT_DEVICE_SILENT,
)

_MAX_BULLETS_PER_SECTION = 15


def format_status_block(
    z2m_active: int,
    z2m_total: int,
    *,
    bridge_online: bool | None,
    ha_active: int = 0,
    ha_linked: int = 0,
) -> str:
    """Build Z2M + HA status lines for alert messages."""
    lines: list[str] = []
    if bridge_online is False:
        if z2m_total:
            lines.append(
                f"סטטוס Z2M: 0/{z2m_total} מכשירים פעילים (גשר לא זמין)"
            )
        else:
            lines.append("סטטוס Z2M: גשר לא זמין")
    else:
        lines.append(f"סטטוס Z2M: {z2m_active}/{z2m_total} מכשירים פעילים")

    if ha_linked or z2m_total:
        lines.append(f"סטטוס HA: {ha_active}/{ha_linked} מכשירים פעילים ב-MQTT")
        missing = max(z2m_total - ha_linked, 0)
        if missing:
            lines.append(f"({missing} מכשירים ב-Z2M לא נמצאו ב-Home Assistant)")
    return "\n".join(lines)


def format_status_line(
    active: int,
    total: int,
    *,
    bridge_online: bool | None,
    ha_active: int = 0,
    ha_linked: int = 0,
) -> str:
    """Backward-compatible wrapper returning the full status block."""
    return format_status_block(
        active,
        total,
        bridge_online=bridge_online,
        ha_active=ha_active,
        ha_linked=ha_linked,
    )


def format_alert(
    event_type: str,
    description: str,
    active: int,
    total: int,
    *,
    bridge_online: bool | None = None,
    ha_active: int = 0,
    ha_linked: int = 0,
    critical: bool = False,
) -> str:
    """Build the standard Hebrew alert message."""
    title = EVENT_TITLES_HE.get(event_type, event_type)
    if event_type == EVENT_BRIDGE_OFFLINE:
        bridge_online = False
    status = format_status_block(
        active,
        total,
        bridge_online=bridge_online,
        ha_active=ha_active,
        ha_linked=ha_linked,
    )
    lines = [HEADER]
    if critical:
        lines.append("⚠️ אירוע קריטי")
    lines.extend([f"התראה: {title}", f"תיאור: {description}", status])
    return "\n".join(lines)


def format_digest_alert(
    descriptions_by_type: dict[str, list[str]],
    active: int,
    total: int,
    *,
    startup: bool = False,
    bridge_online: bool | None = None,
    ha_active: int = 0,
    ha_linked: int = 0,
) -> str:
    """One Telegram message summarizing alerts from the digest queue."""
    lines = [HEADER]
    lines.append(
        "סיכום הפעלה (דקה ראשונה)" if startup else "סיכום התראות"
    )

    for event_type in DIGEST_EVENT_ORDER:
        descs = descriptions_by_type.get(event_type)
        if not descs:
            continue
        title = EVENT_TITLES_HE.get(event_type, event_type)
        lines.append("")
        if len(descs) == 1:
            lines.append(f"• {title}: {descs[0]}")
            continue
        lines.append(f"• {title} ({len(descs)}):")
        for desc in descs[:_MAX_BULLETS_PER_SECTION]:
            lines.append(f"  - {desc}")
        if len(descs) > _MAX_BULLETS_PER_SECTION:
            lines.append(
                f"  … ועוד {len(descs) - _MAX_BULLETS_PER_SECTION}"
            )

    for event_type, descs in descriptions_by_type.items():
        if event_type in DIGEST_EVENT_ORDER:
            continue
        title = EVENT_TITLES_HE.get(event_type, event_type)
        lines.append("")
        for desc in descs:
            lines.append(f"• {title}: {desc}")

    lines.append("")
    lines.append(
        format_status_block(
            active,
            total,
            bridge_online=bridge_online,
            ha_active=ha_active,
            ha_linked=ha_linked,
        )
    )
    return "\n".join(lines)


def group_descriptions_by_type(
    items: list[tuple[str, str]],
) -> dict[str, list[str]]:
    """Group (event_type, description) pairs preserving order within each type."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for event_type, description in items:
        grouped[event_type].append(description)
    return dict(grouped)
