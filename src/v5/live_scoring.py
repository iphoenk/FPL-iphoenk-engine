from __future__ import annotations

from typing import Any

from src.utils import iso_now
from src.v5.config_cache import load_json_config
from src.v5.identity import ElementIndex, resolve_element

REGISTRY_CONFIG = "config/v5_live_scoring_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(REGISTRY_CONFIG)
    if not isinstance(data.get("score"), dict):
        raise RuntimeError("invalid V5 live scoring registry")
    return data


def _live_by_element(event_live: dict | None) -> dict[int, dict]:
    return {
        int(row["id"]): row
        for row in (event_live or {}).get("elements", []) or []
        if isinstance(row, dict) and row.get("id") is not None
    }


def expanded_stats(live_row: dict | None) -> dict[str, Any]:
    row = live_row or {}
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    allowed = tuple(str(x) for x in _cfg()["stat_fields"])
    out = {field: stats.get(field) for field in allowed if field in stats}
    out["explain"] = row.get("explain")
    return out


def personalized_live_score(
    *,
    picks: dict | None,
    event_live: dict | None,
    identity: ElementIndex,
    scoring_gw: int | None,
    is_live_event: bool,
) -> dict[str, Any]:
    statuses = _cfg()["statuses"]
    if not picks or not event_live:
        return {
            "generated_at": iso_now(),
            "status": statuses["no_data"],
            "scoring_gw": scoring_gw,
            "gross_points": None,
            "hit": None,
            "net_points": None,
            "players": [],
        }

    live = _live_by_element(event_live)
    details = []
    gross = 0
    for pick in picks.get("picks", []) or []:
        eid = int(pick["element"])
        resolved = resolve_element(eid, identity) or {}
        stats = expanded_stats(live.get(eid))
        raw_points = int(stats.get("total_points") or 0)
        multiplier = int(pick.get("multiplier") or 0)
        counted = raw_points * multiplier if multiplier > 0 else 0
        gross += counted
        details.append(
            {
                **resolved,
                "pick_position": pick.get("position"),
                "multiplier": multiplier,
                "captain": bool(pick.get("is_captain")),
                "vice_captain": bool(pick.get("is_vice_captain")),
                "counted_points": counted,
                **stats,
            }
        )

    history = picks.get("entry_history") if isinstance(picks.get("entry_history"), dict) else {}
    hit = int(history.get("event_transfers_cost") or 0) if _cfg()["score"].get("subtract_entry_transfer_cost", True) else 0
    return {
        "generated_at": iso_now(),
        "status": statuses["live"] if is_live_event else statuses["not_live"],
        "scoring_gw": scoring_gw,
        "gross_points": gross,
        "hit": hit,
        "net_points": gross - hit,
        "players": details,
    }
