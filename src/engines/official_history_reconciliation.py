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


def _snapshot_picks_for_gw(snapshot: dict[str, Any], gw: int) -> tuple[dict[str, Any] | None, str | None]:
    phase = snapshot.get("phase") or {}
    submitted_gw = _i(phase.get("submitted_gw"), -1)
    if submitted_gw == gw and isinstance(snapshot.get("picks"), dict):
        return snapshot.get("picks"), "submitted_snapshot"
    baseline = snapshot.get("purchase_baseline") or {}
    if _i(baseline.get("gw"), -1) == gw and isinstance(baseline.get("picks"), dict):
        return baseline.get("picks"), "purchase_baseline_snapshot"
    return None, None


def run() -> dict[str, Any]:
    cfg = _load(CONFIG_PATH, {})
    proxy_cfg = cfg.get("retrospective_proxy_baseline") or {}
    detail = _load(DATA / "official_detail.json", {})
    latest = _load(DATA / "latest.json", {})
    team = _load(DATA / "team.json", {})
    snapshot = _load(DATA / "official_snapshot.json", {})
    team_id = _i(team.get("team_id"), 0)
    if team_id <= 0:
        raise RuntimeError("Official historical reconciliation requires authoritative team_id")
    if _i(snapshot.get("team_id"), team_id) != team_id:
        raise RuntimeError("Official historical reconciliation snapshot team_id mismatch")

    history_payload = snapshot.get("history") or {}
    endpoint_health = snapshot.get("endpoint_health") or {}
    current_rows = history_payload.get("current") or []
    finished_gws = sorted({_i(row.get("event")) for row in current_rows if _i(row.get("event")) > 0})
    limit = max(1, _i(proxy_cfg.get("max_historical_gameweeks"), 5))
    wanted = finished_gws[-limit:]

    rows: dict[str, Any] = {}
    health: dict[str, Any] = {
        "entry_history": endpoint_health.get("history") or {"status": "SNAPSHOT"},
    }
    network_pick_fetches = 0
    snapshot_pick_reuses = 0
    for gw in wanted:
        picks, snapshot_source = _snapshot_picks_for_gw(snapshot, gw)
        if picks:
            snapshot_pick_reuses += 1
            health[f"picks_gw_{gw}"] = {"status": "SNAPSHOT", "source": snapshot_source}
        else:
            picks, picks_health = get_json(f"entry/{team_id}/event/{gw}/picks/", retries=1)
            network_pick_fetches += 1
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
        "governance": {
            "entry_history_reused_from_snapshot": True,
            "snapshot_pick_reuses": snapshot_pick_reuses,
            "historical_pick_network_fetches": network_pick_fetches,
            "network_fetch_only_for_missing_historical_pick_artifacts": True,
        },
    }
    detail["historical_entry"] = historical
    atomic_json(DATA / "official_detail.json", detail)

    summary = latest.setdefault("official_detail_summary", {})
    summary.update({
        "historical_submitted_team_authority": "GREEN_PUBLIC_OFFICIAL",
        "historical_gameweeks_available": len(rows),
        "retrospective_proxy_gameweeks": available_proxy,
        "private_pre_deadline_draft_authority": "OPTIONAL_AUTHENTICATED_MONITOR",
        "historical_snapshot_pick_reuses": snapshot_pick_reuses,
        "historical_pick_network_fetches": network_pick_fetches,
    })
    latest["official_historical_authority"] = historical["authority_split"]
    atomic_json(DATA / "latest.json", latest)
    return historical


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
