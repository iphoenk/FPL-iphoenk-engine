from __future__ import annotations

from typing import Any, Iterable

from src.utils import iso_now

CONTRACT = "official_historical_submission_v1"
AUTHORITY = "PUBLIC_OFFICIAL_POST_DEADLINE"


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def finished_gameweeks(entry_history: dict[str, Any] | None) -> list[int]:
    rows = (entry_history or {}).get("current")
    if not isinstance(rows, list):
        return []
    return sorted({_i(row.get("event")) for row in rows if isinstance(row, dict) and _i(row.get("event")) > 0})


def compact_submitted_picks(payload: dict[str, Any]) -> dict[str, Any]:
    entry_history = payload.get("entry_history") if isinstance(payload.get("entry_history"), dict) else {}
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
        "automatic_subs": payload.get("automatic_subs") if isinstance(payload.get("automatic_subs"), list) else [],
    }


def reconcile_historical_submissions(
    *,
    team_id: int,
    entry_history: dict[str, Any] | None,
    picks_by_gw: dict[int, Any],
    source_health: dict[str, Any] | None = None,
    max_historical_gameweeks: int = 5,
    retrospective_proxy_gameweeks: Iterable[int] = (1,),
) -> dict[str, Any]:
    current_rows = (entry_history or {}).get("current")
    current_rows = current_rows if isinstance(current_rows, list) else []
    history_by_gw = {
        _i(row.get("event")): row
        for row in current_rows
        if isinstance(row, dict) and _i(row.get("event")) > 0
    }
    wanted = finished_gameweeks(entry_history)[-max(1, int(max_historical_gameweeks)) :]
    rows: dict[str, Any] = {}
    available = 0
    for gw in wanted:
        picks = picks_by_gw.get(gw)
        if not isinstance(picks, dict) or not isinstance(picks.get("picks"), list):
            rows[str(gw)] = {
                "gw": gw,
                "status": "OFFICIAL_PICKS_UNAVAILABLE",
                "history": history_by_gw.get(gw, {}),
            }
            continue
        rows[str(gw)] = {
            "gw": gw,
            "status": "PUBLIC_OFFICIAL_SUBMITTED_TEAM",
            "authority": AUTHORITY,
            "history": history_by_gw.get(gw, {}),
            "submitted": compact_submitted_picks(picks),
        }
        available += 1

    proxy_requested = sorted({_i(value) for value in retrospective_proxy_gameweeks if _i(value) > 0})
    proxy_available = [
        gw
        for gw in proxy_requested
        if (rows.get(str(gw)) or {}).get("status") == "PUBLIC_OFFICIAL_SUBMITTED_TEAM"
    ]
    return {
        "schema_version": 1,
        "contract": CONTRACT,
        "generated_at": iso_now(),
        "team_id": int(team_id),
        "status": "READY" if available else ("NO_FINISHED_GAMEWEEK_HISTORY" if not wanted else "OFFICIAL_PICKS_UNAVAILABLE"),
        "authority": AUTHORITY,
        "gameweeks": rows,
        "coverage": {
            "requested": len(wanted),
            "available": available,
            "complete": bool(wanted) and available == len(wanted),
        },
        "retrospective_proxy_baseline": {
            "label": "RETROSPECTIVE_PROXY_BASELINE",
            "gameweeks": proxy_available,
            "forecast_capture": "NOT_VERIFIED_PRE_DEADLINE",
            "use_for_predictive_accuracy": False,
            "use_for_dynamic_weight": False,
            "purpose": "historical submitted-team and actual-outcome reconciliation only",
        },
        "authority_split": {
            "historical_submitted_team": "GREEN_PUBLIC_OFFICIAL",
            "current_private_pre_deadline_draft": "OPTIONAL_AUTHENTICATED_MONITOR",
        },
        "source_health": source_health or {},
        "governance": {
            "historical_state_never_overrides_current_pre_deadline_authority": True,
            "retrospective_proxy_is_decision_neutral": True,
            "raw_authenticated_payload_persisted": False,
        },
    }
