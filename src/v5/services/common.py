from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def context_dict(context) -> dict[str, Any]:
    return {
        "current_gw": context.current_gw,
        "next_gw": context.next_gw,
        "last_finished_gw": context.last_finished_gw,
        "planning_gw": context.planning_gw,
        "submitted_gw": context.submitted_gw,
        "scoring_gw": context.scoring_gw,
        "deadline_time": context.deadline_time,
        "is_live_event": context.is_live_event,
        "phase": context.phase.value,
    }


def locked_squad() -> dict:
    cfg = load_json_config("config/v5_squad_registry.json")
    return load_json_config(str(cfg["locked_squad_config"]))
