from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def event_schedule_expression(explicit: str | None = None) -> str | None:
    """Compatibility-only reader for retired GitHub schedule events."""
    if explicit is not None:
        value = str(explicit).strip()
        return value or None
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = str(event.get("schedule") or "").strip()
    return value or None


def simple_hourly_cron_minute(expression: str | None) -> int | None:
    if not expression:
        return None
    parts = str(expression).split()
    if len(parts) != 5 or parts[1:] != ["*", "*", "*", "*"]:
        return None
    try:
        minute = int(parts[0])
    except ValueError:
        return None
    return minute if 0 <= minute <= 59 else None


def nominal_schedule_time(value: datetime, schedule_expression: str | None) -> datetime | None:
    """Resolve legacy nominal cron time for historical compatibility only."""
    minute = simple_hourly_cron_minute(schedule_expression)
    if minute is None:
        return None
    current = _utc(value)
    nominal = current.replace(minute=minute, second=0, microsecond=0)
    if nominal > current:
        nominal -= timedelta(hours=1)
    return nominal


def scheduled_invocation_slot(
    value: datetime,
    scheduler_interval_minutes: int,
    schedule_expression: str | None,
) -> datetime:
    from .runtime_control import scheduler_slot_start

    nominal = nominal_schedule_time(value, schedule_expression)
    anchor = nominal if nominal is not None else _utc(value)
    return scheduler_slot_start(anchor, scheduler_interval_minutes)
