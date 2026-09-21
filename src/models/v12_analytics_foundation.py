from __future__ import annotations

"""Read-only V12 analytics foundation over normalized V6 factual artifacts.

This module is not a factual authority, source adapter, scheduler, model owner,
or runner.  It consumes only V6-published normalized facts and fails closed
when the match-level contract is incomplete.
"""

from pathlib import Path
from typing import Any, Mapping
import json


JOINABLE = {"EXACT", "VERIFIED", "VERIFIED_MANUAL"}


class AnalyticsFoundationError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _latest_completed_gw(
    bootstrap: Mapping[str, Any], planning_gw: int
) -> int:
    finished = [
        int(row.get("id") or 0)
        for row in bootstrap.get("events") or []
        if isinstance(row, Mapping) and row.get("finished") is True
    ]
    return max(finished or [max(0, int(planning_gw) - 1)])


def _row_is_joinable(row: Mapping[str, Any]) -> bool:
    return bool(
        int(row.get("official_element_id") or 0) > 0
        and str(row.get("identity_status") or "").upper() in JOINABLE
        and int(row.get("official_fixture_id") or 0) > 0
        and str(row.get("fixture_identity_status") or "").upper() in JOINABLE
        and int(row.get("official_opponent_team_id") or 0) > 0
        and str(row.get("opponent_identity_status") or "").upper() in JOINABLE
    )


def _feature_status(
    rows: list[dict[str, Any]], field: str, *, required: bool
) -> dict[str, Any]:
    populated = sum(row.get(field) is not None for row in rows)
    total = len(rows)
    return {
        "feature": field,
        "available_rows": populated,
        "total_rows": total,
        "coverage": 0.0 if total == 0 else round(populated / total, 6),
        "required": required,
        "status": (
            "AVAILABLE"
            if total > 0 and populated == total
            else "PARTIAL"
            if populated > 0
            else "UNAVAILABLE"
        ),
    }


def load_v6_analytics_foundation(
    runtime_data_root: Path,
    *,
    bootstrap: Mapping[str, Any],
    planning_gw: int,
) -> dict[str, Any]:
    normalized = _read_json(
        runtime_data_root
        / "data/v6/normalized/sources/vaastav_fpl.json"
    )
    groups = normalized.get("record_groups") or {}
    raw_rows = [
        dict(row)
        for row in groups.get("player_matches") or []
        if isinstance(row, Mapping)
    ]
    rows = [row for row in raw_rows if _row_is_joinable(row)]

    completed_gw = _latest_completed_gw(bootstrap, planning_gw)
    observed_gws = sorted(
        {
            int(row.get("gw") or 0)
            for row in rows
            if int(row.get("gw") or 0) > 0
        }
    )
    max_gw = max(observed_gws or [0])
    rejected = len(raw_rows) - len(rows)

    required_core = (
        "official_element_id",
        "official_fixture_id",
        "official_opponent_team_id",
        "gw",
        "minutes",
        "starter",
        "home",
        "fpl_points",
        "xg",
        "xa",
        "xgi",
    )
    optional_known = (
        "bonus",
        "bps",
        "saves",
        "penalties_saved",
        "defensive",
        "clearances_blocks_interceptions",
        "recoveries",
        "tackles",
        "creativity",
        "influence",
        "threat",
    )
    explicitly_unavailable = (
        "sub_minute",
        "actual_role",
        "npxg",
        "shots",
        "sot",
        "shots_in_box",
        "big_chances",
        "big_chances_created",
        "touches_in_box",
        "key_passes",
        "crosses",
        "team_shares",
        "psxg_xgot",
        "goals_prevented",
        "errors",
        "coach",
        "nominal_formation",
        "in_possession_shape",
        "out_of_possession_shape",
        "press_block",
        "width",
        "transition_style",
        "build_up_style",
        "set_piece_style",
        "substitution_tendencies",
    )
    matrix = [
        _feature_status(rows, field, required=True)
        for field in required_core
    ] + [
        _feature_status(rows, field, required=False)
        for field in optional_known
    ] + [
        {
            "feature": field,
            "available_rows": 0,
            "total_rows": len(rows),
            "coverage": 0.0,
            "required": False,
            "status": "UNAVAILABLE_REQUIRES_OTHER_FACTUAL_SOURCE",
        }
        for field in explicitly_unavailable
    ]

    blockers: list[str] = []
    if str(normalized.get("source_health") or "").upper() != "GREEN":
        blockers.append("VAASTAV_NORMALIZED_SOURCE_NOT_GREEN")
    if not raw_rows:
        blockers.append("VAASTAV_MERGED_GW_NOT_PUBLISHED")
    if rejected:
        blockers.append(
            f"NON_DETERMINISTIC_IDENTITY_ROWS_REJECTED={rejected}"
        )
    if max_gw < completed_gw:
        blockers.append(
            f"MATCH_ROWS_STALE_MAX_GW={max_gw}_COMPLETED_GW={completed_gw}"
        )
    missing_core = [
        row["feature"]
        for row in matrix
        if row.get("required")
        and row.get("status") != "AVAILABLE"
    ]
    if missing_core:
        blockers.append(
            "REQUIRED_MATCH_FEATURES_INCOMPLETE=" + ",".join(missing_core)
        )

    match_rows = [
        {
            "player_id": int(row["official_element_id"]),
            "element": int(row["official_element_id"]),
            "fixture": int(row["official_fixture_id"]),
            "match_id": int(row["official_fixture_id"]),
            "opponent_team_id": int(row["official_opponent_team_id"]),
            "opponent": int(row["official_opponent_team_id"]),
            "gw": int(row.get("gw") or 0),
            "home": bool(row.get("home")),
            "minutes": row.get("minutes"),
            "minutes_played": row.get("minutes"),
            "starter": bool(row.get("starter")),
            "position": row.get("position"),
            "goals": row.get("goals"),
            "assists": row.get("assists"),
            "xg": row.get("xg"),
            "xa": row.get("xa"),
            "xgi": row.get("xgi"),
            "xgc": row.get("xgc"),
            "clean_sheets": row.get("clean_sheets"),
            "goals_conceded": row.get("goals_conceded"),
            "saves": row.get("saves"),
            "penalties_saved": row.get("penalties_saved"),
            "penalties_missed": row.get("penalties_missed"),
            "bonus": row.get("bonus"),
            "bps": row.get("bps"),
            "defensive": row.get("defensive"),
            "clearances_blocks_interceptions": row.get(
                "clearances_blocks_interceptions"
            ),
            "recoveries": row.get("recoveries"),
            "tackles": row.get("tackles"),
            "fpl_points": row.get("fpl_points"),
            "source": row.get("source") or "vaastav_fpl",
            "dataset": row.get("dataset") or "merged_gw",
            "freshness": normalized.get("effective_at"),
            "provenance": {
                "source_id": normalized.get("source_id"),
                "source_snapshot_ids": normalized.get("source_snapshot_ids"),
                "normalization_version": normalized.get(
                    "normalization_version"
                ),
                "identity_status": row.get("identity_status"),
                "fixture_identity_status": row.get(
                    "fixture_identity_status"
                ),
                "opponent_identity_status": row.get(
                    "opponent_identity_status"
                ),
            },
        }
        for row in rows
        if 1 <= int(row.get("gw") or 0) <= completed_gw
    ]

    status = "MATCH_FOUNDATION_READY" if not blockers else "BLOCKED"
    return {
        "contract": "V12_ANALYTICS_FOUNDATION_V1",
        "status": status,
        "stage1_full_foundation_ready": False,
        "stage1_full_foundation_reason": (
            "Advanced player/tactical/GK features, formal opponent-strength "
            "adjustment, distribution-selection validation, hierarchical "
            "posterior uncertainty and full xMins state split remain separate "
            "Stage-1 gaps until validated; they are never fabricated here."
        ),
        "planning_gw": int(planning_gw),
        "latest_completed_gw": completed_gw,
        "observed_gws": observed_gws,
        "raw_match_rows": len(raw_rows),
        "joinable_match_rows": len(rows),
        "rejected_identity_rows": rejected,
        "blockers": blockers,
        "feature_matrix": matrix,
        "player_match_rows": match_rows,
        "opponent_history_rows": match_rows,
        "opponent_history_scope": "CURRENT-SEASON ONLY",
        "historical_prior": {"model": None, "season": None, "players": {}},
        "player_features_payload": {},
        "governance": {
            "v6_only_factual_input": True,
            "name_or_fuzzy_join_forbidden": True,
            "season_aggregate_only_forbidden": True,
            "missing_features_fabricated": False,
            "new_model_owner_created": False,
        },
    }


def require_match_foundation(payload: Mapping[str, Any]) -> dict[str, Any]:
    if str(payload.get("status") or "") != "MATCH_FOUNDATION_READY":
        blockers = payload.get("blockers") or ["UNKNOWN_FOUNDATION_BLOCKER"]
        raise AnalyticsFoundationError(
            "match-by-match factual foundation unavailable: "
            + ";".join(str(value) for value in blockers)
        )
    return dict(payload)
