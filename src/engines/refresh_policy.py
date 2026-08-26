from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.utils import ROOT

CONFIG_PATH = ROOT / "config" / "intelligence" / "refresh_policy.json"


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("policy_id"):
        raise RuntimeError("refresh policy config is invalid")
    return payload


def refresh_interval_minutes(deadline: str | None, is_live: bool = False) -> int:
    policy = load_policy()
    if is_live:
        return int(policy["live_interval_minutes"])
    default = int(policy["default_interval_minutes"])
    if not deadline:
        return default
    try:
        target = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        hours = (target - datetime.now(timezone.utc)).total_seconds() / 3600
    except (TypeError, ValueError):
        return default
    for window in sorted(policy.get("deadline_windows") or [], key=lambda row: float(row["max_hours"])):
        if hours <= float(window["max_hours"]):
            return int(window["interval_minutes"])
    return default


def mode(deadline: str | None, is_live: bool = False) -> dict[str, Any]:
    policy = load_policy()
    minutes = refresh_interval_minutes(deadline, is_live)
    threshold = int(policy["always_on_interval_below_minutes"])
    return {
        "mode": "MATCHDAY_LIVE" if is_live else "DEADLINE_AWARE",
        "recommended_interval_minutes": minutes,
        "requires_always_on_host": minutes < threshold or is_live,
        "policy_id": policy.get("policy_id"),
    }
