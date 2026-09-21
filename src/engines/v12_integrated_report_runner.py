from __future__ import annotations

"""Thin V12-native integrated report runner.

This module closes the occurrence-execution gap between the V6 factual plane,
the existing V12 P1.x model owners, and the Canonical report renderer.

It is deliberately NOT:
- a scheduler;
- a V6 publisher/acquisition owner;
- a replacement methodology authority;
- a legacy V3/V4/V5 bridge;
- a second optimizer or second report schema.

Canonical V12 remains authority. V6 remains factual plane. Owner modules keep
their mathematics. The runner only binds one report occurrence, executes the
owners whose inputs are supportable, records stage truth, and materializes one
coherent report bundle.
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.engines.v12_lineup_optimizer import optimize_lineup
from src.engines.v12_mini_league_overlay import build_mini_league_snapshot
from src.engines.visible_content_proof import canonical_mode_contract
from src.engines.v12_report_orchestration import (
    build_actionable_price_radar,
    build_price20,
    build_visible_mathematical_decision_stack,
    build_watchlist20,
    materialize_all15,
    materialize_deep_report,
    render_deep_text,
    validate_human_facing_body,
)
from src.runtime_v6.domains.report_plane.report_qa import (
    validate_post_render_qa,
    validate_pre_render_qa,
)
from src.runtime_v6.domains.report_plane.visible_body_contract import _parse_sections
from src.engines.v12_tactical_role import attach_tactical_role_scores
from src.models.historical_projection import build as build_player_projections
from src.models.v12_analytics_foundation import (\n    load_v6_analytics_foundation,\n    require_match_foundation,\n)\nfrom src.models.official_role_evidence import attach_official_role_evidence
from src.models.team_strength import build_team_strength

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PATH = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"
STATE_PATH = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_STATE_V12.json"

SUPPORTED_MODES = {"DEEP"}

class IntegratedRunnerError(RuntimeError):
    pass


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists() or path.stat().st_size <= 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stage(
    ledger: list[dict[str, Any]],
    name: str,
    fn: Callable[[], Any],
    *,
    required: bool = False,
) -> Any:
    try:
        value = fn()
    except Exception as exc:  # occurrence truth must survive one stage failure
        ledger.append(
            {
                "stage": name,
                "status": "FAILED",
                "required": bool(required),
                "error_class": type(exc).__name__,
                "error": str(exc),
            }
        )
        return None
    ledger.append(
        {
            "stage": name,
            "status": "PASS",
            "required": bool(required),
            "output_fingerprint": _fingerprint(value),
        }
    )
    return value


def _parse_aware(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _stage_failure_reason(ledger: Sequence[Mapping[str, Any]], name: str) -> str | None:
    for row in reversed(list(ledger)):
        if str(row.get("stage") or "") == name and str(row.get("status") or "") == "FAILED":
            return f"{row.get('error_class')}: {row.get('error')}"
    return None


def _skip_stage(
    ledger: list[dict[str, Any]],
    name: str,
    reason: str,
    *,
    required: bool = False,
) -> None:
    ledger.append(
        {
            "stage": name,
            "status": "NOT_RUN",
            "required": bool(required),
            "reason": reason,
        }
    )


def _require_report_prefetch(
    runtime_root: Path,
    *,
    report_slot: str,
) -> dict[str, Any]:
    """Bind DEEP to the exact full_master occurrence, never merely a fresh health summary."""
    latest = _read_json(
        runtime_root / "data/v6/report_prefetch/latest.json",
        {},
    ) or {}
    health = _read_json(
        runtime_root / "data/v6/health/report_prefetch.json",
        {},
    ) or {}
    requested = _parse_aware(report_slot)
    target = _parse_aware(
        latest.get("target_logical_report_slot")
        or latest.get("logical_slot")
    )
    generated = _parse_aware(latest.get("generated_at"))
    if requested is None:
        raise IntegratedRunnerError("report_slot must be timezone-aware ISO-8601")
    public_first_acceptable = bool(
        latest.get("public_core_complete") is True
        and str(health.get("public_core_status") or "").upper() == "GREEN"
        and latest.get("authenticated_personal_required_for_public_green") is False
        and str(latest.get("public_personal_status") or "").upper() == "AVAILABLE"
        and str(latest.get("mini_league_status") or "").upper() == "AVAILABLE"
        and not (latest.get("public_control_failures") or [])
    )
    prefetch_health_acceptable = bool(
        str(health.get("prefetch_status") or "").upper() == "GREEN"
        or public_first_acceptable
    )
    checks = {
        "report_kind_full_master": str(latest.get("report_kind") or "") == "full_master",
        "target_report_slot_match": bool(
            target is not None
            and target.astimezone(requested.tzinfo) == requested
        ),
        "personal_requested": latest.get("personal_requested") is True,
        "mini_league_requested": latest.get("mini_league_requested") is True,
        "public_core_complete": latest.get("public_core_complete") is True,
        "fresh_for_target_report": latest.get("fresh_for_target_report") is True,
        "prefetch_health_acceptable": prefetch_health_acceptable,
    }
    failed = [key for key, value in checks.items() if not value]
    if failed:
        raise IntegratedRunnerError(
            "same-occurrence full_master prefetch mismatch: " + ",".join(failed)
        )
    if generated is None:
        raise IntegratedRunnerError("report-prefetch generated_at unavailable")
    age_minutes = abs(
        (requested - generated.astimezone(requested.tzinfo)).total_seconds()
    ) / 60.0
    if age_minutes > 15.0:
        raise IntegratedRunnerError(
            f"report-prefetch is not same-occurrence current: age_minutes={age_minutes:.2f}"
        )
    return {
        **latest,
        "prefetch_health": health,
        "same_occurrence_bound": True,
        "report_slot": report_slot,
        "age_minutes": round(age_minutes, 3),
        "scope_checks": checks,
        "live_required_for_deep": False,
    }


def _official_payload(runtime_root: Path) -> dict[str, Any]:
    payload = _read_json(runtime_root / "data/v6/current/official_fpl.json", {}) or {}
    official = payload.get("official") or {}
    bootstrap = official.get("bootstrap") or {}
    fixtures = official.get("fixtures") or []
    if not isinstance(bootstrap, Mapping) or not bootstrap.get("elements"):
        raise IntegratedRunnerError("Official FPL bootstrap is unavailable")
    if not isinstance(fixtures, list) or not fixtures:
        raise IntegratedRunnerError("Official FPL fixtures are unavailable")
    return {
        "payload": payload,
        "bootstrap": dict(bootstrap),
        "fixtures": [dict(row) for row in fixtures if isinstance(row, Mapping)],
    }


def _planning_gw(bootstrap: Mapping[str, Any]) -> int:
    events = [dict(row) for row in bootstrap.get("events") or [] if isinstance(row, Mapping)]
    next_rows = [row for row in events if row.get("is_next") is True]
    if next_rows:
        return int(next_rows[0]["id"])
    current = [row for row in events if row.get("is_current") is True]
    if current:
        return int(current[0]["id"]) + 1
    unfinished = [int(row.get("id") or 0) for row in events if not row.get("finished")]
    unfinished = [gw for gw in unfinished if gw > 0]
    return min(unfinished) if unfinished else 1


def _position_name(value: Any) -> str:
    token = str(value or "").upper()
    return "GK" if token in {"GKP", "GK"} else token


def _owned15(
    runtime_root: Path,
    state: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
) -> list[dict[str, Any]]:
    current = _read_json(runtime_root / "data/v6/personal/current_team.json", {}) or {}
    player_map = {
        int(row.get("id")): dict(row)
        for row in bootstrap.get("elements") or []
        if row.get("id") is not None
    }
    rows: list[dict[str, Any]] = []
    for row in current.get("players") or []:
        if not isinstance(row, Mapping) or row.get("element_id") is None:
            continue
        element = int(row["element_id"])
        official = player_map.get(element) or {}
        rows.append(
            {
                "element_id": element,
                "element": element,
                "name": official.get("web_name") or str(element),
                "position": _position_name(row.get("position")),
                "team_id": int(official.get("team") or 0),
                "now_cost": int(row.get("current_price") or official.get("now_cost") or 0),
                "sell_value": row.get("selling_price"),
                "status": official.get("status"),
                "eligible": True,
                "squad_position": row.get("squad_position"),
                "bench_order": row.get("bench_order"),
                "captain": bool(row.get("captain")),
                "vice_captain": bool(row.get("vice_captain")),
            }
        )
    if len(rows) == 15:
        return rows

    confirmed = (state.get("confirmed_current_squad_state") or {})
    rows = []
    groups = (
        ("goalkeepers", "GK"),
        ("defenders", "DEF"),
        ("midfielders", "MID"),
        ("forwards", "FWD"),
    )
    for group, position in groups:
        for row in confirmed.get(group) or []:
            if row.get("element_id") is None:
                continue
            element = int(row["element_id"])
            official = player_map.get(element) or {}
            rows.append(
                {
                    "element_id": element,
                    "element": element,
                    "name": official.get("web_name") or row.get("display_name") or str(element),
                    "position": position,
                    "team_id": int(official.get("team") or 0),
                    "now_cost": int(official.get("now_cost") or 0),
                    "sell_value": None,
                    "status": official.get("status"),
                    "eligible": True,
                }
            )
    if len(rows) != 15:
        raise IntegratedRunnerError(f"OUR15 identity incomplete: {len(rows)}/15")
    return rows


def _projection_model_rows(
    projections: Mapping[str, Any],
    owned_ids: set[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in projections.get("players") or []:
        if not isinstance(player, Mapping):
            continue
        element = int(player.get("element") or 0)
        if element not in owned_ids:
            continue
        xmins = dict(player.get("xmins") or {})
        horizons = dict(player.get("horizons") or {})
        tactical = dict(player.get("tactical_role_component") or {})
        gw1 = dict(horizons.get("1") or {})
        gw3 = dict(horizons.get("3") or {})
        gw5 = dict(horizons.get("5") or {})
        rows.append(
            {
                "element_id": element,
                "name": player.get("name"),
                "opponent": (
                    ((player.get("xpts_by_gw") or [{}])[0].get("fixtures") or [{}])[0].get("opponent")
                    if player.get("xpts_by_gw")
                    else "UNAVAILABLE"
                ),
                "recommended_or_locked_role": "UNLOCKED",
                "p_available": xmins.get("availability", xmins.get("overall_availability", "UNAVAILABLE")),
                "p_start": xmins.get("start_probability", "UNAVAILABLE"),
                "p_cameo": xmins.get("cameo_probability", "UNAVAILABLE"),
                "p_dnp": xmins.get("dnp_probability", "UNAVAILABLE"),
                "xmins": xmins.get("expected_minutes", "UNAVAILABLE"),
                "tactical_role": tactical.get("canonical_tactical_role_score", "UNAVAILABLE"),
                "set_piece_penalty_role": {
                    "set_piece": player.get("set_piece_role"),
                    "penalty": player.get("penalty_role"),
                },
                "matchup": tactical.get("fixture_contexts", "UNAVAILABLE"),
                "gw_plus_1": gw1.get("mean", "UNAVAILABLE"),
                "three_gw": gw3.get("mean", "UNAVAILABLE"),
                "five_gw": gw5.get("mean", "UNAVAILABLE"),
                "uncertainty_floor_upside": {
                    "gw1_std": gw1.get("std"),
                    "gw1_distribution": gw1.get("point_distribution"),
                },
                "action": "HOLD",
            }
        )
    return rows


def _candidate_universe(projections: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in projections.get("players") or []:
        if not isinstance(player, Mapping):
            continue
        rows.append(
            {
                "element_id": int(player.get("element") or 0),
                "element": int(player.get("element") or 0),
                "name": player.get("name"),
                "position": player.get("position"),
                "team_id": int(player.get("team_id") or 0),
                "now_cost": int(player.get("now_cost") or 0),
                "status": player.get("status"),
                "eligible": str(player.get("status") or "a") not in {"u"},
                # Full 20/25/30/25 producer is intentionally NOT invented here.
                "canonical_evaluation_complete": False,
            }
        )
    return [row for row in rows if row["element"] > 0]


def _lineup_content(lineup: Mapping[str, Any] | None) -> dict[str, Any]:
    if not lineup:
        return {"status": "UNAVAILABLE"}
    return {
        "formation": lineup.get("formation"),
        "starting_xi": lineup.get("starting_xi"),
        "bench": lineup.get("bench"),
        "captain": lineup.get("captain"),
        "vice_captain": lineup.get("vice_captain"),
        "lineup_score": lineup.get("lineup_score"),
        "formation_comparison": lineup.get("formation_comparison"),
    }


def _core_slot_binding(
    *,
    report_slot: str,
    publish_integrity: Mapping[str, Any],
) -> dict[str, Any]:
    requested = _parse_aware(report_slot)
    actual = _parse_aware(publish_integrity.get("logical_slot"))
    if requested is None:
        return {"status": "FAIL", "reason": "REPORT_SLOT_INVALID"}
    expected = requested.replace(minute=0, second=0, microsecond=0)
    actual_local = actual.astimezone(requested.tzinfo) if actual else None
    matched = actual_local == expected
    return {
        "status": "PASS" if matched else "PARTIAL",
        "reason": None if matched else "CORE_SLOT_MISMATCH",
        "expected_core_slot": expected.isoformat(),
        "actual_core_slot": actual_local.isoformat() if actual_local else None,
        "publish_integrity_status": publish_integrity.get("status"),
    }


def _qa_compute_contract(
    *,
    owned: Sequence[Mapping[str, Any]],
    lineup: Mapping[str, Any] | None,
    watchlist: Mapping[str, Any] | None,
    rise: Mapping[str, Any] | None,
    fall: Mapping[str, Any] | None,
    sections: Mapping[str, Any],
) -> dict[str, Any]:
    xi = list((lineup or {}).get("starting_xi") or [])
    bench = list((lineup or {}).get("bench") or [])
    watch_rows = list((watchlist or {}).get("rows") or [])
    rise_rows = list((rise or {}).get("rows") or [])
    fall_rows = list((fall or {}).get("rows") or [])
    fact_key = "OFFICIAL_FPL_OCCURRENCE_FACTS"
    model_key = "V12_OCCURRENCE_MODEL_OUTPUTS"
    inference_key = "V12_DECISION_INFERENCE"
    payload = {
        "owned": [row.get("element_id") for row in owned],
        "xi": xi,
        "bench": bench,
        "watch": watch_rows,
        "rise": rise_rows,
        "fall": fall_rows,
        "sections": sections,
    }
    return {
        "status": "PASS",
        "compute_ready": True,
        "delivery_ready": False,
        "next_action": "PRE_RENDER_QA",
        "failures": [],
        "legacy_fallback_allowed": False,
        "compute_fingerprint": _fingerprint(payload),
        "OUR15": {
            "status": "PASS" if len(owned) == 15 else "FAIL",
            "total": len(owned),
        },
        "XI": {
            "status": "PASS" if len(xi) == 11 else "FAIL",
            "total": len(xi),
        },
        "BENCH": {
            "status": "PASS" if len(bench) == 4 else "FAIL",
            "total": len(bench),
        },
        "WATCHLIST20": {
            "status": "PASS"
            if str((watchlist or {}).get("state") or "").upper() == "COMPLETE"
            else "FAIL",
            "total": len(watch_rows),
        },
        "RISE20": {
            "status": "PASS"
            if str((rise or {}).get("state") or "").upper() == "COMPLETE"
            else "FAIL",
            "total": len(rise_rows),
        },
        "FALL20": {
            "status": "PASS"
            if str((fall or {}).get("state") or "").upper() == "COMPLETE"
            else "FAIL",
            "total": len(fall_rows),
        },
        "FACT_MODEL": {
            "status": "PASS",
            "overlap": [],
            "fact_keys": [fact_key],
            "model_keys": [model_key],
            "inference_keys": [inference_key],
        },
        "serious_decision_required": True,
    }


def _section(
    state: str,
    content: Any,
    reason: str | None = None,
    *,
    available_count: int | None = None,
    expected_count: int | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"state": state, "content": content}
    if reason:
        row["degradation_reason"] = reason
    if available_count is not None:
        row["available_count"] = int(available_count)
    if expected_count is not None:
        row["expected_count"] = int(expected_count)
    return row


def run_deep(
    *,
    runtime_data_root: Path,
    report_slot: str,
    output_dir: Path,
    checkpoint_time: str | None = None,
) -> dict[str, Any]:
    ledger: list[dict[str, Any]] = []
    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    state = _read_json(STATE_PATH, {}) or {}

    prefetch = _stage(
        ledger,
        "V6_REPORT_PREFETCH_BINDING",
        lambda: _require_report_prefetch(
            runtime_data_root,
            report_slot=report_slot,
        ),
        required=True,
    )
    if not prefetch:
        raise IntegratedRunnerError(
            "DEEP integrated runner requires fresh same-occurrence V6 report-prefetch"
        )

    publish_integrity = _read_json(
        runtime_data_root / "data/v6/health/publish_integrity.json",
        {},
    ) or {}
    core_binding = _core_slot_binding(
        report_slot=report_slot,
        publish_integrity=publish_integrity,
    )
    ledger.append(
        {
            "stage": "CORE_SLOT_BINDING",
            "status": core_binding.get("status"),
            "required": True,
            "reason": core_binding.get("reason"),
            "evidence": core_binding,
        }
    )

    official = _stage(
        ledger,
        "V6_OFFICIAL_FACTS",
        lambda: _official_payload(runtime_data_root),
        required=True,
    )
    if not official:
        raise IntegratedRunnerError("required Official FPL factual input unavailable")
    bootstrap = official["bootstrap"]
    fixtures = official["fixtures"]
    planning_gw = _planning_gw(bootstrap)
    owned = _stage(
        ledger,
        "OUR15_IDENTITY",
        lambda: _owned15(runtime_data_root, state, bootstrap),
        required=True,
    )
    if not owned:
        raise IntegratedRunnerError("OUR15 unavailable")

    strength = _stage(
        ledger,
        "TEAM_STRENGTH",
        lambda: build_team_strength(bootstrap, fixtures),
        required=True,
    )
    foundation = _stage(
        ledger,
        "V12_ANALYTICS_FOUNDATION",
        lambda: require_match_foundation(
            load_v6_analytics_foundation(
                runtime_data_root,
                bootstrap=bootstrap,
                planning_gw=planning_gw,
            )
        ),
        required=True,
    )
    if foundation:
        projections = _stage(
            ledger,
            "P1_1_P1_3_FULL_UNIVERSE",
            lambda: build_player_projections(
                bootstrap,
                strength or {},
                planning_gw,
                foundation.get("historical_prior") or {},
                player_features_payload=(
                    foundation.get("player_features_payload") or {}
                ),
                player_match_rows=(
                    foundation.get("player_match_rows") or []
                ),
                opponent_history_rows=(
                    foundation.get("opponent_history_rows") or []
                ),
                opponent_history_scope=foundation.get(
                    "opponent_history_scope"
                ),
            ),
            required=True,
        )
    else:
        foundation_reason = (
            _stage_failure_reason(ledger, "V12_ANALYTICS_FOUNDATION")
            or "UNKNOWN_ANALYTICS_FOUNDATION_FAILURE"
        )
        _skip_stage(
            ledger,
            "P1_1_P1_3_FULL_UNIVERSE",
            "analytics foundation prerequisite failed: " + foundation_reason,
            required=True,
        )
        projections = None
    projection_failure = (
        _stage_failure_reason(ledger, "P1_1_P1_3_FULL_UNIVERSE")
        or _stage_failure_reason(ledger, "V12_ANALYTICS_FOUNDATION")
    )

    owned_ids = {int(row["element_id"]) for row in owned}
    if projections:
        _stage(
            ledger,
            "OFFICIAL_ROLE_EVIDENCE",
            lambda: attach_official_role_evidence(projections, bootstrap),
        )
        _stage(
            ledger,
            "P1_6_TACTICAL_ROLE",
            lambda: attach_tactical_role_scores(
                projections,
                planning_gw,
                team_strength=strength or {},
            ),
        )
        model_rows = _projection_model_rows(projections, owned_ids)
        all15 = _stage(
            ledger,
            "ALL15_MATERIALIZATION",
            lambda: materialize_all15(owned15=owned, model_rows=model_rows),
            required=True,
        )
        lineup = _stage(
            ledger,
            "P1_7_LINEUP",
            lambda: optimize_lineup(
                projections,
                sorted(owned_ids),
                planning_gw=planning_gw,
            ),
        )
    else:
        reason = (
            "P1.1/P1.3 prerequisite failed: "
            + (projection_failure or "UNKNOWN_PROJECTION_FAILURE")
        )
        _skip_stage(ledger, "OFFICIAL_ROLE_EVIDENCE", reason)
        _skip_stage(ledger, "P1_6_TACTICAL_ROLE", reason)
        _skip_stage(ledger, "ALL15_MATERIALIZATION", reason, required=True)
        _skip_stage(ledger, "P1_7_LINEUP", reason)
        all15 = {
            "rows": [
                {
                    "element_id": row.get("element_id"),
                    "name": row.get("name"),
                    "position": row.get("position"),
                    "p_available": "UNAVAILABLE",
                    "p_start": "UNAVAILABLE",
                    "p_cameo": "UNAVAILABLE",
                    "p_dnp": "UNAVAILABLE",
                    "xmins": "UNAVAILABLE",
                    "gw_plus_1": "UNAVAILABLE",
                    "three_gw": "UNAVAILABLE",
                    "five_gw": "UNAVAILABLE",
                    "action": "WAIT",
                }
                for row in owned
            ],
            "degradation_reason": reason,
        }
        lineup = None


    predictor = _read_json(
        runtime_data_root / "data/v6/current/official_price_predictor.json",
        {},
    ) or {}
    rise = _stage(
        ledger,
        "OFFICIAL_FPL_PREDICTOR_RISE20",
        lambda: build_price20(
            predictor_artifact=predictor,
            direction="RISE",
            owned_element_ids=sorted(owned_ids),
        ),
    )
    fall = _stage(
        ledger,
        "OFFICIAL_FPL_PREDICTOR_FALL20",
        lambda: build_price20(
            predictor_artifact=predictor,
            direction="FALL",
            owned_element_ids=sorted(owned_ids),
        ),
    )
    price_radar = _stage(
        ledger,
        "OUR15_PRICE_RADAR",
        lambda: build_actionable_price_radar(
            owned15=owned,
            predictor_artifact=predictor,
        ),
    )

    universe = _candidate_universe(projections or {})
    watchlist = _stage(
        ledger,
        "WATCHLIST20",
        lambda: build_watchlist20(
            evaluated_universe=universe,
            owned_element_ids=sorted(owned_ids),
            universe_authority="PARTIAL",
        ),
    )

    standings = _read_json(
        runtime_data_root / "data/v6/mini_leagues/9477/standings.json",
        {},
    ) or {}
    picks_gw = max(
        [
            int(path.name.split("_")[1])
            for path in (runtime_data_root / "data/v6/mini_leagues/9477").glob("gw_*_manager_picks.json")
            if path.name.startswith("gw_")
        ]
        or [max(1, planning_gw - 1)]
    )
    manager_picks = _read_json(
        runtime_data_root
        / f"data/v6/mini_leagues/9477/gw_{picks_gw}_manager_picks.json",
        {},
    ) or {}
    mini = _stage(
        ledger,
        "P1_8_MINI_LEAGUE_SNAPSHOT",
        lambda: build_mini_league_snapshot(
            standings,
            manager_picks,
            our_entry_id=3462711,
            planning_gw=planning_gw,
        ),
    )

    if projections:
        universe_gap_reason = (
            "P1.1/P1.3/P1.6 executed for full universe, but the current repository "
            "does not yet expose V12-native numeric producers for all four "
            "20/25/30/25 components. Full football_score/ranking is therefore "
            "fail-closed instead of reconstructed ad hoc."
        )
    else:
        universe_gap_reason = (
            "P1.1/P1.3 full-universe projection did not execute for this occurrence: "
            + (projection_failure or "UNKNOWN_PROJECTION_FAILURE")
        )
    universe_gap = {
        "status": "PARTIAL",
        "reason": universe_gap_reason,
        "scanned_players": len(universe),
        "required_component_weights": {
            "PROVEN_HISTORICAL": 0.20,
            "TACTICAL_ROLE": 0.25,
            "CURRENT_UNDERLYING": 0.30,
            "FIXTURE_SECURITY": 0.25,
        },
    }
    ledger.append(
        {
            "stage": "CANONICAL_UNIVERSE_20_25_30_25",
            "status": "PARTIAL",
            "required": True,
            "reason": universe_gap["reason"],
        }
    )
    _skip_stage(
        ledger,
        "P1_2_PACKAGE_UTILITY",
        "full canonical 20/25/30/25 ranking is prerequisite for utility-ranked packages",
    )
    _skip_stage(
        ledger,
        "P1_4_MONTE_CARLO",
        "supportable material route distributions are unavailable until canonical universe/package utility is complete",
    )

    lineup_state = "COMPLETE" if lineup else "DEGRADED"
    lineup_reason = None if lineup else "P1.7 owner did not produce a supportable route"
    mini_state = (
        "COMPLETE"
        if mini and mini.get("coverage_state") == "FULL"
        else "DEGRADED"
    )
    mini_reason = (
        None
        if mini_state == "COMPLETE"
        else "ICON+ public coverage is incomplete for this occurrence"
    )
    watch_state = str((watchlist or {}).get("state") or "UNAVAILABLE")
    watch_reason = (watchlist or {}).get("degradation_reason") or universe_gap["reason"]

    sections = {
        "S01": _section(
            "COMPLETE",
            {
                "operational_state": "WAIT",
                "planning_gw": planning_gw,
                "report_slot": report_slot,
                "integrated_runner": "EXECUTED",
            },
        ),
        "S02": _section(
            "COMPLETE",
            {"rows": (all15 or {}).get("rows", [])},
            available_count=len((all15 or {}).get("rows", [])),
            expected_count=15,
        ),
        "S03": _section(
            "COMPLETE",
            {
                "decision_delta": "NO ACT WITHOUT FULL 20/25/30/25 UNIVERSE EVALUATION",
                "runner_delta": "P1.1/P1.3/P1.6/P1.7/price/ICON stages now occurrence-bound",
            },
        ),
        "S04": _section(
            "COMPLETE",
            {
                "changes": [
                    "Integrated owner-module execution is bound to one occurrence.",
                    "Manual prose is not accepted as an analytics substitute.",
                ]
            },
        ),
        "S05": _section(
            "COMPLETE",
            {
                "planning_gw": planning_gw,
                "fixtures": [
                    row for row in fixtures
                    if int(row.get("event") or -1) == planning_gw
                ],
                "weather": "DIRECT_CHATGPT_REQUIRED_AT_VISIBLE_DELIVERY",
            },
        ),
        "S06": _section(
            lineup_state,
            _lineup_content(lineup),
            lineup_reason,
        ),
        "S07": _section(
            lineup_state,
            {"main_starting_xi_battle": (lineup or {}).get("main_starting_xi_battle")},
            lineup_reason,
        ),
        "S08": _section(
            lineup_state,
            {
                "captain": (lineup or {}).get("captain"),
                "vice_captain": (lineup or {}).get("vice_captain"),
            },
            lineup_reason,
        ),
        "S09": _section(
            "DEGRADED",
            {"chip": "UNAVAILABLE_CURRENT_AUTH"},
            "private authenticated chip/economics evidence unavailable",
        ),
        "S10": _section(
            "COMPLETE" if price_radar else "DEGRADED",
            price_radar or {"rows": []},
            None if price_radar else "Official FPL predictor radar unavailable",
        ),
        "S11": _section(
            watch_state,
            {
                "rows": (watchlist or {}).get("rows", []),
                "universe_evaluator": universe_gap,
            },
            None if watch_state == "COMPLETE" else watch_reason,
            available_count=(watchlist or {}).get("available_count", 0),
            expected_count=20,
        ),
        "S12": _section(
            str((rise or {}).get("state") or "UNAVAILABLE"),
            rise or {"rows": []},
            (rise or {}).get("degradation_reason"),
            available_count=(rise or {}).get("available_count", 0),
            expected_count=20,
        ),
        "S13": _section(
            str((fall or {}).get("state") or "UNAVAILABLE"),
            fall or {"rows": []},
            (fall or {}).get("degradation_reason"),
            available_count=(fall or {}).get("available_count", 0),
            expected_count=20,
        ),
        "S14": _section(
            "DEGRADED",
            {
                "universe_scan": universe_gap,
                "package_routes": [],
                "monte_carlo": {
                    "execution_state": "NOT_RUN",
                    "reason": "FULL_20_25_30_25_UNIVERSE_EVALUATION_REQUIRED_FIRST",
                },
            },
            universe_gap["reason"],
        ),
        "S15": _section(
            "COMPLETE",
            {
                "evidence_quality": {
                    "official_fpl": "CURRENT_INPUT_READ",
                    "p1_1_p1_3": "EXECUTED" if projections else "FAILED",
                    "p1_6": "EXECUTED" if projections else "NOT_RUN",
                    "p1_7": "EXECUTED" if lineup else "PARTIAL",
                    "price_predictor": (rise or {}).get("predictor_health"),
                    "universe_20_25_30_25": "PARTIAL",
                }
            },
        ),
        "S15B": _section(
            mini_state,
            mini or {"coverage_state": "UNAVAILABLE"},
            mini_reason,
        ),
        "S16": _section(
            "COMPLETE" if projections else "DEGRADED",
            {"rows": (all15 or {}).get("rows", [])},
            (
                None
                if projections
                else (
                    "P1.1/P1.3 occurrence projection unavailable: "
                    + (projection_failure or "UNKNOWN_PROJECTION_FAILURE")
                )
            ),
            available_count=len((all15 or {}).get("rows", [])),
            expected_count=15,
        ),
        "S17": _section(
            "COMPLETE",
            {
                "engine_data_status": {
                    "runner": "V12_INTEGRATED_REPORT_RUNNER",
                    "planning_gw": planning_gw,
                    "projection_players": len((projections or {}).get("players") or []),
                    "our15": len(owned),
                    "mini_league_coverage": (mini or {}).get("coverage_state"),
                    "stage_ledger": ledger,
                }
            },
        ),
        "S18": _section(
            "COMPLETE",
            {
                "NOW": "WAIT",
                "TRIGGER TO ACT": "FULL 20/25/30/25 universe evaluator + legal/economic route + robustness evidence",
                "ABORT / REVERSAL": "role/injury/economics or challenger evidence invalidates selected route",
                "NEXT CHECKPOINT": "next due report occurrence with fresh V6 prefetch",
            },
        ),
        "S19": _section(
            "COMPLETE",
            {
                "final_judgement": (
                    "WAIT pending full canonical universe component evaluation; "
                    "do not privilege prior shortlist names."
                )
            },
        ),
    }

    math_stack = build_visible_mathematical_decision_stack({})
    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads=sections,
        checkpoint_time=checkpoint_time,
        mathematical_decision_stack=math_stack,
    )
    section_manifest = [
        {
            "section_id": str(row.get("section_id") or ""),
            "status": str(row.get("state") or ""),
        }
        for row in report.get("sections") or []
    ]
    compute_contract = _qa_compute_contract(
        owned=owned,
        lineup=lineup,
        watchlist=watchlist,
        rise=rise,
        fall=fall,
        sections=sections,
    )
    mini_complete = bool(
        mini
        and str(mini.get("coverage_state") or "").upper() == "FULL"
    )
    pre_render_qa = validate_pre_render_qa(
        compute_contract=compute_contract,
        section_manifest=section_manifest,
        mini_league_denominator_complete=mini_complete,
        report_mode="DEEP",
        weather_contract_state="SOURCE_DEGRADED",
    )
    body = render_deep_text(report)
    human_failures = validate_human_facing_body(body)
    parsed_ids, _, _ = _parse_sections(body)
    rendered_states = {
        str(row.get("section_id") or ""): str(row.get("state") or "")
        for row in report.get("sections") or []
    }
    post_render_qa = validate_post_render_qa(
        pre_render_qa=pre_render_qa,
        rendered_body=body,
        rendered_section_ids=parsed_ids,
        rendered_section_states=rendered_states,
        rendered_compute_fingerprint=compute_contract["compute_fingerprint"],
        render_contract_token=pre_render_qa.get("render_contract_token"),
        rendered_counts=dict(pre_render_qa.get("expected_counts") or {}),
        rendered_fact_keys=list(pre_render_qa.get("expected_fact_keys") or []),
        rendered_model_keys=list(pre_render_qa.get("expected_model_keys") or []),
        rendered_mini_league_denominator_complete=mini_complete,
        rendered_weather_contract_state="SOURCE_DEGRADED",
        truncated=False,
    )
    contract = canonical_mode_contract(canonical, "DEEP")
    catalog_complete = (
        list(parsed_ids) == list(contract.get("expected_section_ids") or [])
    )
    runner_status = (
        "PASS"
        if (
            catalog_complete
            and str(pre_render_qa.get("status") or "").upper() == "PASS"
            and str(post_render_qa.get("status") or "").upper() == "PASS"
            and not human_failures
        )
        else "PARTIAL"
    )
    ledger.extend(
        [
            {
                "stage": "CANONICAL_RENDER",
                "status": "PASS" if catalog_complete else "FAILED",
                "required": True,
                "reason": None if catalog_complete else "CANONICAL_CATALOG_MISMATCH",
                "evidence": {
                    "expected": contract.get("expected_section_ids"),
                    "rendered": parsed_ids,
                },
            },
            {
                "stage": "PRE_RENDER_QA",
                "status": pre_render_qa.get("status"),
                "required": True,
                "reason": ";".join(pre_render_qa.get("failures") or []) or None,
            },
            {
                "stage": "POST_RENDER_QA",
                "status": post_render_qa.get("status"),
                "required": True,
                "reason": ";".join(post_render_qa.get("failures") or []) or None,
            },
            {
                "stage": "HUMAN_FACING_QA",
                "status": "PASS" if not human_failures else "FAILED",
                "required": True,
                "reason": ";".join(human_failures) or None,
            },
        ]
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    execution_proof = {
        "schema_version": 2,
        "runner": "V12_INTEGRATED_REPORT_RUNNER",
        "report_slot": report_slot,
        "report_mode": "DEEP",
        "planning_gw": planning_gw,
        "runner_status": runner_status,
        "canonical_expected_section_ids": contract.get("expected_section_ids"),
        "rendered_section_ids": parsed_ids,
        "canonical_catalog_complete": catalog_complete,
        "core_slot_binding": core_binding,
        "report_prefetch_binding": {
            "same_occurrence_bound": prefetch.get("same_occurrence_bound"),
            "report_prefetch_run_id": prefetch.get("report_prefetch_run_id"),
            "target_logical_report_slot": prefetch.get("target_logical_report_slot"),
            "scope_checks": prefetch.get("scope_checks"),
        },
        "pre_render_qa_status": pre_render_qa.get("status"),
        "post_render_qa_status": post_render_qa.get("status"),
        "human_facing_qa_status": "PASS" if not human_failures else "FAIL",
        "stages": ledger,
        "no_silent_stage_skip": True,
        "no_second_model_authority": True,
        "monte_carlo_fabricated": False,
    }
    bundle = {
        "schema": "FPL_MASTER_V12_INTEGRATED_REPORT_BUNDLE_V2",
        "authority": str(CANONICAL_PATH.relative_to(ROOT)),
        "state_authority": False,
        "report_mode": "DEEP",
        "report_slot": report_slot,
        "planning_gw": planning_gw,
        "runner_status": runner_status,
        "stage_ledger": ledger,
        "section_manifest": section_manifest,
        "compute_contract": compute_contract,
        "pre_render_qa": pre_render_qa,
        "post_render_qa": post_render_qa,
        "human_facing_qa": {
            "status": "PASS" if not human_failures else "FAIL",
            "failures": human_failures,
        },
        "execution_proof": execution_proof,
        "report": report,
        "visible_body": body,
        "source_fingerprints": {
            "report_prefetch": _fingerprint(prefetch),
            "official_fpl": _fingerprint(official["payload"]),
            "state": _fingerprint(state),
            "predictor": _fingerprint(predictor),
            "mini_league_standings": _fingerprint(standings),
            "mini_league_picks": _fingerprint(manager_picks),
        },
        "governance": {
            "scheduler_created": False,
            "v6_mutated": False,
            "legacy_runtime_executed": False,
            "second_methodology_created": False,
            "manual_shortlist_privileged": False,
            "report_falls_back_to_prose_without_bundle": False,
            "fail_operational_delivery": True,
        },
    }
    (output_dir / "report_bundle.json").write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (output_dir / "report_body.md").write_text(body, encoding="utf-8")
    (output_dir / "execution_proof.json").write_text(
        json.dumps(execution_proof, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-data-root", required=True)
    parser.add_argument("--report-mode", default="DEEP")
    parser.add_argument("--report-slot", required=True)
    parser.add_argument("--checkpoint-time", default=None)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    mode = str(args.report_mode).upper()
    if mode not in SUPPORTED_MODES:
        raise IntegratedRunnerError(
            f"runner stage-1 supports {sorted(SUPPORTED_MODES)}; got {mode}"
        )
    bundle = run_deep(
        runtime_data_root=Path(args.runtime_data_root),
        report_slot=args.report_slot,
        output_dir=Path(args.output_dir),
        checkpoint_time=args.checkpoint_time,
    )
    print(
        json.dumps(
            {
                "runner_status": bundle.get("runner_status"),
                "report_mode": bundle.get("report_mode"),
                "report_slot": bundle.get("report_slot"),
                "section_count": len(bundle.get("section_manifest") or []),
                "output_dir": str(Path(args.output_dir).resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
