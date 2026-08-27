from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.sources.official_fpl import get_json
from src.utils import DATA, ROOT, atomic_json, iso_now

CONFIG_PATH = ROOT / "config" / "intelligence" / "prediction_evaluation.json"


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _compact_picks(payload: dict[str, Any]) -> dict[str, Any]:
    entry_history = payload.get("entry_history") or {}
    return {
        "active_chip": payload.get("active_chip"),
        "entry_history": {
            key: entry_history.get(key)
            for key in (
                "event",
                "points",
                "total_points",
                "rank",
                "rank_sort",
                "overall_rank",
                "bank",
                "value",
                "event_transfers",
                "event_transfers_cost",
                "points_on_bench",
            )
            if key in entry_history
        },
        "picks": [
            {
                "element": row.get("element"),
                "position": row.get("position"),
                "multiplier": row.get("multiplier"),
                "is_captain": bool(row.get("is_captain")),
                "is_vice_captain": bool(row.get("is_vice_captain")),
            }
            for row in (payload.get("picks") or [])
            if isinstance(row, dict)
        ],
        "automatic_subs": payload.get("automatic_subs") or [],
    }


def run() -> dict[str, Any]:
    cfg = _load(CONFIG_PATH, {})
    proxy_cfg = cfg.get("retrospective_proxy_baseline") or {}
    detail = _load(DATA / "official_detail.json", {})
    latest = _load(DATA / "latest.json", {})
    team = _load(DATA / "team.json", {})
    team_id = _i(team.get("team_id"), 0)
    if team_id <= 0:
        raise RuntimeError("Official historical reconciliation requires authoritative team_id")

    history_payload, history_health = get_json(f"entry/{team_id}/history/", retries=1)
    current_rows = (history_payload or {}).get("current") or []
    finished_gws = sorted({_i(row.get("event")) for row in current_rows if _i(row.get("event")) > 0})
    limit = max(1, _i(proxy_cfg.get("max_historical_gameweeks"), 5))
    wanted = finished_gws[-limit:]

    rows: dict[str, Any] = {}
    health: dict[str, Any] = {"entry_history": history_health}
    for gw in wanted:
        picks, picks_health = get_json(f"entry/{team_id}/event/{gw}/picks/", retries=1)
        health[f"picks_gw_{gw}"] = picks_health
        history_row = next((row for row in current_rows if _i(row.get("event")) == gw), {})
        if not picks:
            rows[str(gw)] = {
                "gw": gw,
                "status": "OFFICIAL_PICKS_UNAVAILABLE",
                "history": history_row,
            }
            continue
        rows[str(gw)] = {
            "gw": gw,
            "status": "PUBLIC_OFFICIAL_SUBMITTED_TEAM",
            "authority": "PUBLIC_OFFICIAL_POST_DEADLINE",
            "history": history_row,
            "submitted": _compact_picks(picks),
        }

    proxy_gws = sorted({_i(x) for x in (proxy_cfg.get("gameweeks") or []) if _i(x) > 0})
    available_proxy = [gw for gw in proxy_gws if (rows.get(str(gw)) or {}).get("status") == "PUBLIC_OFFICIAL_SUBMITTED_TEAM"]
    historical = {
        "generated_at": iso_now(),
        "team_id": team_id,
        "status": "READY" if rows else "NO_FINISHED_GAMEWEEK_HISTORY",
        "authority": "PUBLIC_OFFICIAL_POST_DEADLINE",
        "gameweeks": rows,
        "retrospective_proxy_baseline": {
            "label": proxy_cfg.get("label", "RETROSPECTIVE_PROXY_BASELINE"),
            "gameweeks": available_proxy,
            "forecast_capture": "NOT_VERIFIED_PRE_DEADLINE",
            "use_for_predictive_accuracy": False,
            "use_for_dynamic_weight": False,
            "purpose": "historical submitted-team and actual-outcome reconciliation only",
        },
        "authority_split": {
            "historical_submitted_team": "GREEN_PUBLIC_OFFICIAL",
            "current_private_pre_deadline_draft": "OPTIONAL_AUTHENTICATED_MONITOR",
        },
        "source_health": health,
    }
    detail["historical_entry"] = historical
    atomic_json(DATA / "official_detail.json", detail)

    summary = latest.setdefault("official_detail_summary", {})
    summary.update({
        "historical_submitted_team_authority": "GREEN_PUBLIC_OFFICIAL",
        "historical_gameweeks_available": len(rows),
        "retrospective_proxy_gameweeks": available_proxy,
        "private_pre_deadline_draft_authority": "OPTIONAL_AUTHENTICATED_MONITOR",
    })
    latest["official_historical_authority"] = historical["authority_split"]
    atomic_json(DATA / "latest.json", latest)
    return historical


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
