from __future__ import annotations

"""Read-only V12 analytics foundation over normalized V6 factual artifacts."""

from pathlib import Path
from typing import Any, Mapping
import json

from src.models.v12_stage1_analytics import (
    build_hierarchical_priors,
    distribution_selection_matrix,
    opponent_adjust_match_rows,
    probabilistic_tactical_states,
    walk_forward_validate,
)

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
    bootstrap: Mapping[str, Any],
    planning_gw: int,
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
    rows: list[dict[str, Any]],
    field: str,
    *,
    required: bool,
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


def _match_source_candidate(
    runtime_data_root: Path,
    source_id: str,
    completed_gw: int,
) -> dict[str, Any]:
    normalized = _read_json(
        runtime_data_root
        / f"data/v6/normalized/sources/{source_id}.json"
    )
    groups = normalized.get("record_groups") or {}
    raw_rows = [
        dict(row)
        for row in groups.get("player_matches") or []
        if isinstance(row, Mapping)
    ]
    rows = [row for row in raw_rows if _row_is_joinable(row)]
    observed_gws = sorted(
        {
            int(row.get("gw") or 0)
            for row in rows
            if int(row.get("gw") or 0) > 0
        }
    )
    max_gw = max(observed_gws or [0])
    history = normalized.get("history_coverage") or {}
    missing_gws = [
        int(value)
        for value in history.get("missing_gws") or []
        if int(value or 0) > 0
    ]
    source_green = (
        str(normalized.get("source_health") or "").upper() == "GREEN"
    )
    normalized_ok = (
        str(normalized.get("normalization_status") or "").upper()
        == "NORMALIZED"
    )
    complete = bool(
        source_green
        and normalized_ok
        and rows
        and max_gw >= completed_gw
        and not missing_gws
    )
    return {
        "source_id": source_id,
        "normalized": normalized,
        "raw_rows": raw_rows,
        "rows": rows,
        "observed_gws": observed_gws,
        "max_gw": max_gw,
        "missing_gws": missing_gws,
        "complete": complete,
    }


def _select_match_source(
    runtime_data_root: Path,
    completed_gw: int,
) -> dict[str, Any]:
    official = _match_source_candidate(
        runtime_data_root,
        "official_fpl",
        completed_gw,
    )
    vaastav = _match_source_candidate(
        runtime_data_root,
        "vaastav_fpl",
        completed_gw,
    )
    if official["complete"]:
        selected = official
        selection_reason = "OFFICIAL_FPL_COMPLETE_PRIMARY"
    elif vaastav["complete"]:
        selected = vaastav
        selection_reason = "COMPLETE_MIRROR_FALLBACK"
    else:
        selected = official if official["raw_rows"] else vaastav
        selection_reason = "NO_COMPLETE_MATCH_HISTORY_SOURCE"
    return {
        **selected,
        "selection_reason": selection_reason,
        "candidates": {
            "official_fpl": {
                "complete": official["complete"],
                "max_gw": official["max_gw"],
                "missing_gws": official["missing_gws"],
                "row_count": len(official["rows"]),
            },
            "vaastav_fpl": {
                "complete": vaastav["complete"],
                "max_gw": vaastav["max_gw"],
                "missing_gws": vaastav["missing_gws"],
                "row_count": len(vaastav["rows"]),
            },
        },
    }


def load_v6_analytics_foundation(
    runtime_data_root: Path,
    *,
    bootstrap: Mapping[str, Any],
    planning_gw: int,
    strength: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    completed_gw = _latest_completed_gw(
        bootstrap,
        planning_gw,
    )
    selected_source = _select_match_source(
        runtime_data_root,
        completed_gw,
    )
    normalized = dict(selected_source.get("normalized") or {})
    raw_rows = list(selected_source.get("raw_rows") or [])
    rows = list(selected_source.get("rows") or [])
    observed_gws = list(selected_source.get("observed_gws") or [])
    max_gw = int(selected_source.get("max_gw") or 0)
    rejected = len(raw_rows) - len(rows)
    selected_source_id = str(
        selected_source.get("source_id") or "UNAVAILABLE"
    )
    official = {
        int(row.get("id")): dict(row)
        for row in bootstrap.get("elements") or []
        if int(row.get("id") or 0) > 0
    }

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
    matrix = (
        [
            _feature_status(rows, field, required=True)
            for field in required_core
        ]
        + [
            _feature_status(rows, field, required=False)
            for field in optional_known
        ]
        + [
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
    )

    blockers: list[str] = []
    if selected_source.get("complete") is not True:
        blockers.append("NO_COMPLETE_MATCH_HISTORY_SOURCE")
    if str(normalized.get("source_health") or "").upper() != "GREEN":
        blockers.append(
            f"{selected_source_id.upper()}_NORMALIZED_SOURCE_NOT_GREEN"
        )
    if not raw_rows:
        blockers.append(
            f"{selected_source_id.upper()}_PLAYER_MATCHES_NOT_PUBLISHED"
        )
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
        if row.get("required") and row.get("status") != "AVAILABLE"
    ]
    if missing_core:
        blockers.append(
            "REQUIRED_MATCH_FEATURES_INCOMPLETE="
            + ",".join(missing_core)
        )

    match_rows = []
    for row in rows:
        gw = int(row.get("gw") or 0)
        if not 1 <= gw <= completed_gw:
            continue
        element = int(row["official_element_id"])
        player = official.get(element) or {}
        position = row.get("position") or {
            1: "GK",
            2: "DEF",
            3: "MID",
            4: "FWD",
        }.get(int(player.get("element_type") or 0))
        match_rows.append(
            {
                "player_id": element,
                "element": element,
                "team_id": int(player.get("team") or 0),
                "fixture": int(row["official_fixture_id"]),
                "match_id": int(row["official_fixture_id"]),
                "opponent_team_id": int(
                    row["official_opponent_team_id"]
                ),
                "opponent": int(row["official_opponent_team_id"]),
                "gw": gw,
                "home": bool(row.get("home")),
                "minutes": row.get("minutes"),
                "minutes_played": row.get("minutes"),
                "starter": bool(row.get("starter")),
                "position": position,
                "actual_role": None,
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
                "source": row.get("source") or selected_source_id,
                "dataset": row.get("dataset") or "player_matches",
                "freshness": normalized.get("effective_at"),
                "provenance": {
                    "source_id": normalized.get("source_id"),
                    "source_snapshot_ids": normalized.get(
                        "source_snapshot_ids"
                    ),
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
        )

    adjusted = opponent_adjust_match_rows(match_rows, strength or {})
    hierarchy = build_hierarchical_priors(adjusted)
    distributions = distribution_selection_matrix(adjusted)
    validation = walk_forward_validate(adjusted)
    tactical_states = probabilistic_tactical_states(
        bootstrap,
        adjusted,
    )

    match_ready = not blockers
    stage1_ready = bool(
        match_ready
        and validation.get("status") == "PASS"
        and hierarchy.get("players")
        and distributions.get("matrix")
    )
    return {
        "contract": "V12_ANALYTICS_FOUNDATION_V2",
        "status": "MATCH_FOUNDATION_READY" if match_ready else "BLOCKED",
        "stage1_full_foundation_ready": stage1_ready,
        "stage1_full_foundation_reason": (
            None
            if stage1_ready
            else (
                "required match facts or walk-forward/statistical "
                "diagnostics are not execution-ready"
            )
        ),
        "planning_gw": int(planning_gw),
        "latest_completed_gw": completed_gw,
        "selected_match_source": selected_source_id,
        "match_source_selection_reason": selected_source.get(
            "selection_reason"
        ),
        "match_source_candidates": selected_source.get("candidates") or {},
        "observed_gws": observed_gws,
        "raw_match_rows": len(raw_rows),
        "joinable_match_rows": len(rows),
        "rejected_identity_rows": rejected,
        "blockers": blockers,
        "feature_matrix": matrix,
        "player_match_rows": adjusted,
        "opponent_history_rows": adjusted,
        "opponent_history_scope": "CURRENT-SEASON ONLY",
        "historical_prior": {
            "model": None,
            "season": None,
            "players": {},
        },
        "player_features_payload": {
            "contract": "V12_STAGE1_FOUNDATION_V2",
            "model_opt_in": True,
            "stage1_hierarchical_priors": hierarchy.get("players") or {},
            "stage1_distribution_selection": distributions,
            "stage1_walk_forward_validation": validation,
            "stage1_tactical_states": tactical_states,
        },
        "opponent_adjustment": {
            "status": "AVAILABLE" if adjusted else "UNAVAILABLE",
            "attack_strength": "SUPPORTED",
            "defence_strength": "SUPPORTED",
            "home_advantage": "SUPPORTED_VENUE_SPECIFIC",
            "set_piece_attack": "UNAVAILABLE",
            "set_piece_defence": "UNAVAILABLE",
            "transition_attack": "UNAVAILABLE",
            "transition_defence": "UNAVAILABLE",
            "aerial_attack": "UNAVAILABLE",
            "aerial_defence": "UNAVAILABLE",
            "league_position_primary": False,
        },
        "hierarchical_bayesian": hierarchy,
        "distribution_selection": distributions,
        "walk_forward_validation": validation,
        "probabilistic_tactical_states": tactical_states,
        "governance": {
            "v6_only_factual_input": True,
            "official_fpl_match_history_primary": True,
            "mirror_fallback_requires_complete_current_gw": True,
            "stale_mirror_rejected": True,
            "name_or_fuzzy_join_forbidden": True,
            "season_aggregate_only_forbidden": True,
            "missing_features_fabricated": False,
            "unknown_tactical_state_explicit": True,
            "new_model_owner_created": False,
        },
    }


def require_match_foundation(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if str(payload.get("status") or "") != "MATCH_FOUNDATION_READY":
        blockers = payload.get("blockers") or [
            "UNKNOWN_FOUNDATION_BLOCKER"
        ]
        raise AnalyticsFoundationError(
            "match-by-match factual foundation unavailable: "
            + ";".join(str(value) for value in blockers)
        )
    if payload.get("stage1_full_foundation_ready") is not True:
        raise AnalyticsFoundationError(
            "Stage-1 statistical foundation diagnostics are not green"
        )
    return dict(payload)
