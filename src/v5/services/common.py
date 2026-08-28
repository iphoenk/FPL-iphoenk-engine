from __future__ import annotations

from datetime import datetime
from typing import Any

from src.rules import RULESET_ID
from src.v5.config_cache import load_json_config
from src.v5.time_utils import parse_iso_datetime


def parse_datetime(value: Any) -> datetime | None:
    parsed = parse_iso_datetime(value)
    if value is not None and parsed is None:
        raise ValueError(f"invalid datetime value: {value!r}")
    return parsed


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
        "ruleset_id": RULESET_ID,
    }


def locked_squad() -> dict:
    cfg = load_json_config("config/v5_squad_registry.json")
    return load_json_config(str(cfg["locked_squad_config"]))
