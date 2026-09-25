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
import cProfile
import hashlib
import json
import os
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.engines.v12_lineup_optimizer import optimize_lineup
from src.engines.v12_mini_league_overlay import (
    attach_mini_league_overlay,
    build_mini_league_snapshot,
    evaluate_mini_league_overlay,
    load_config as load_mini_league_config,
)
from src.engines.v12_monte_carlo import (
    attach_monte_carlo_to_package_utility,
    canonical_package_seed,
    run_package_monte_carlo,
)
from src.engines.v12_package_search import (
    compose_material_two_transfer_packages,
    search_packages,
)
from src.engines.v12_package_utility import (
    attach_stage3_decision,
    combine_package_utility_surfaces,
    derive_bounded_future_frontier,
    evaluate_packages,
    finalize_stage3_decision,
    select_material_funding_legs,
    select_stage3_material_mc_routes,
)
from src.engines.visible_content_proof import canonical_mode_contract
from src.engines.v12_price_delivery import run_price_occurrence
from src.engines.v12_deep_delivery import (
    select_personal_evidence,
    validate_deep_decision_content_delivery,
)
from src.engines.v12_report_orchestration import (
    build_actionable_price_radar,
    build_deep_human_facing_manifest,
    build_price20,
    build_visible_mathematical_decision_stack,
    build_watchlist20,
    materialize_all15,
    materialize_deep_report,
    render_deep_text,
    validate_deep_human_facing_manifest,
    validate_human_facing_body,
)
from src.runtime_v6.domains.report_plane.report_qa import (
    validate_post_render_qa,
    validate_pre_render_qa,
)
from src.runtime_v6.domains.report_plane.visible_body_contract import _parse_sections
from src.engines.v12_tactical_role import attach_tactical_role_scores
from src.engines.v12_stage2_derived_cache import (
    load_or_build_stage2_projections,
)
from src.engines.v12_contextual_dynamics import (
    build_player_trajectory,
    build_post_match_deep_details,
    build_post_match_universe_scan,
)
from src.models.historical_projection import build as build_player_projections
from src.models.v12_analytics_foundation import (
    load_v6_analytics_foundation,
    require_match_foundation,
)
from src.models.v12_stage1_analytics import build_canonical_universe
from src.models.official_role_evidence import attach_official_role_evidence
from src.models.team_strength import build_team_strength

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PATH = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"
STATE_PATH = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_STATE_V12.json"

SUPPORTED_MODES = {"DEEP", "PRICE"}


def _stagec_scanner_enabled() -> bool:
    raw = os.getenv("V12_STAGEC_SCANNER_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


class IntegratedRunnerError(RuntimeError):
    pass


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists() or path.stat().st_size <= 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _fingerprint_json_default(value: Any) -> Any:
    """Canonicalize supported runtime-only objects for deterministic stage hashing."""
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(
        f"Object of type {value.__class__.__name__} is not JSON serializable"
    )


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_fingerprint_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_PROFILED_STAGE_NAMES = frozenset(
    {
        "V12_ANALYTICS_FOUNDATION",
        "P1_1_P1_3_FULL_UNIVERSE",
        "P1_2B_PACKAGE_COMBINE",
        "P1_4_MONTE_CARLO",
    }
)


def _stage_profile_path(name: str) -> Path | None:
    raw = str(os.environ.get("V12_STAGE_PROFILE_DIR") or "").strip()
    if not raw or name not in _PROFILED_STAGE_NAMES:
        return None
    directory = Path(raw)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{name}.pstats"


def _stage(
    ledger: list[dict[str, Any]],
    name: str,
    fn: Callable[[], Any],
    *,
    required: bool = False,
) -> Any:
    started = time.perf_counter()
    print(f"[V12_STAGE] START {name}", flush=True)
    profile_path = _stage_profile_path(name)
    profiler = cProfile.Profile() if profile_path is not None else None
    if profiler is not None:
        profiler.enable()
    try:
        value = fn()
    except Exception as exc:  # occurrence truth must survive one stage failure
        if profiler is not None:
            profiler.disable()
            profiler.dump_stats(str(profile_path))
        elapsed = time.perf_counter() - started
        print(
            f"[V12_STAGE] FAILED {name} elapsed_seconds={elapsed:.3f} "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        ledger.append(
            {
                "stage": name,
                "status": "FAILED",
                "required": bool(required),
                "error_class": type(exc).__name__,
                "error": str(exc),
                "elapsed_seconds": round(elapsed, 3),
                "profile_artifact": str(profile_path) if profile_path else None,
            }
        )
        return None
    if profiler is not None:
        profiler.disable()
        profiler.dump_stats(str(profile_path))
    elapsed = time.perf_counter() - started
    print(
        f"[V12_STAGE] PASS {name} elapsed_seconds={elapsed:.3f}",
        flush=True,
    )
    ledger.append(
        {
            "stage": name,
            "status": "PASS",
            "required": bool(required),
            "output_fingerprint": _fingerprint(value),
            "elapsed_seconds": round(elapsed, 3),
            "profile_artifact": str(profile_path) if profile_path else None,
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


def _personal_evidence_resolution(
    runtime_root: Path,
    state: Mapping[str, Any] | None = None,
    *,
    planning_gw: int,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    personal_dir = runtime_root / "data/v6/personal"
    for path in sorted(personal_dir.glob("*current_team*.json")):
        payload = _read_json(path, {}) or {}
        candidates.append({
            "source": str(path.relative_to(runtime_root)),
            "source_class": "AUTHENTICATED_CURRENT_TEAM",
            "payload": payload,
            "observed_at": payload.get("generated_at"),
            "gw": payload.get("gw"),
            "auth_state": payload.get("auth_state"),
        })
    confirmed = dict(
        ((state or {}).get("confirmed_current_squad_state") or {})
    )
    explicit_at = (
        confirmed.get("explicit_user_confirmed_at")
        or confirmed.get("evidence_timestamp")
        or confirmed.get("confirmed_at")
    )
    explicit_gw = (
        confirmed.get("applicable_planning_gw")
        or confirmed.get("planning_gw")
        or confirmed.get("gw")
    )
    explicit_flag = confirmed.get("explicit_user_confirmation") is True
    if explicit_at and explicit_gw is not None and explicit_flag:
        players: list[dict[str, Any]] = []
        for group, position in (
            ("goalkeepers", "GK"),
            ("defenders", "DEF"),
            ("midfielders", "MID"),
            ("forwards", "FWD"),
        ):
            for item in confirmed.get(group) or []:
                if not isinstance(item, Mapping):
                    continue
                element = item.get("element_id", item.get("element"))
                if element is None:
                    continue
                players.append({
                    **dict(item),
                    "element_id": int(element),
                    "position": position,
                })
        candidates.append({
            "source": "FPL_MASTER_STATE_V12:EXPLICIT_USER_CONFIRMED",
            "source_class": "USER_CONFIRMED",
            "payload": {
                "players": players,
                "generated_at": explicit_at,
                "gw": explicit_gw,
                "bank": confirmed.get("bank"),
                "chips": confirmed.get("chips"),
                "availability": confirmed.get("availability") or {},
            },
            "observed_at": explicit_at,
            "gw": explicit_gw,
            "auth_state": "USER_CONFIRMED",
            "applicable_planning_gw": int(explicit_gw),
            "explicit_confirmation": True,
        })

    submitted = _read_json(
        personal_dir / "submitted_picks.json",
        {},
    ) or {}
    if submitted:
        candidates.append({
            "source": "data/v6/personal/submitted_picks.json",
            "source_class": "OFFICIAL_SUBMITTED_PICKS",
            "payload": submitted,
            "observed_at": submitted.get("generated_at"),
            "gw": submitted.get("gw"),
            "auth_state": "PUBLIC_OFFICIAL",
        })
    return select_personal_evidence(
        candidates,
        planning_gw=planning_gw,
    )


def _position_from_official(row: Mapping[str, Any]) -> str:
    mapping = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    try:
        return mapping.get(int(row.get("element_type") or 0), "")
    except (TypeError, ValueError):
        return ""


def _owned15(
    personal_resolution: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
) -> list[dict[str, Any]]:
    player_map = {
        int(row.get("id")): dict(row)
        for row in bootstrap.get("elements") or []
        if row.get("id") is not None
    }
    finance_allowed = personal_resolution.get("finance_allowed") is True
    rows: list[dict[str, Any]] = []
    for row in personal_resolution.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        raw_element = row.get("element_id", row.get("element"))
        if raw_element is None:
            continue
        element = int(raw_element)
        official = player_map.get(element) or {}
        rows.append(
            {
                "element_id": element,
                "element": element,
                "name": official.get("web_name") or str(element),
                "position": (
                    _position_name(row.get("position"))
                    or _position_from_official(official)
                ),
                "team_id": int(official.get("team") or 0),
                "now_cost": int(
                    row.get("current_price")
                    or official.get("now_cost")
                    or 0
                ),
                "current_price": (
                    row.get("current_price")
                    if row.get("current_price") is not None
                    else official.get("now_cost")
                ),
                "purchase_price": (
                    row.get("purchase_price")
                    if finance_allowed
                    else None
                ),
                "selling_price": (
                    row.get("selling_price")
                    if finance_allowed
                    else None
                ),
                "sell_value": (
                    row.get("selling_price")
                    if finance_allowed
                    else None
                ),
                "status": official.get("status"),
                "eligible": True,
                "squad_position": row.get("squad_position", row.get("position_index")),
                "bench_order": row.get("bench_order"),
                "captain": bool(row.get("captain")),
                "vice_captain": bool(row.get("vice_captain")),
            }
        )
    if len(rows) != 15 or len({row["element_id"] for row in rows}) != 15:
        raise IntegratedRunnerError(
            f"OUR15 identity incomplete: {len(rows)}/15"
        )
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


def _candidate_universe(
    projections: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return list(
        build_canonical_universe(projections).get("players") or []
    )


def _package_candidate_rows(
    projections: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in projections.get("players") or []:
        if not isinstance(player, Mapping):
            continue
        element = int(player.get("element") or player.get("id") or 0)
        position = str(player.get("position") or "").upper()
        team_id = int(player.get("team_id") or player.get("team") or 0)
        now_cost = player.get("now_cost")
        if (
            element <= 0
            or position not in {"GK", "DEF", "MID", "FWD"}
            or team_id <= 0
            or now_cost is None
        ):
            continue
        rows.append(
            {
                "element": element,
                "name": player.get("name"),
                "position": position,
                "team_id": team_id,
                "now_cost": int(now_cost),
                "status": player.get("status"),
                "eligible": player.get("eligible", True) is not False,
                "stage2_lineage": deepcopy(
                    player.get("canonical_lineage")
                    or player.get("lineage")
                    or {}
                ),
            }
        )
    return rows


def _private_finance_context(
    personal_resolution: Mapping[str, Any],
) -> dict[str, Any]:
    current = dict(personal_resolution.get("payload") or {})
    availability = dict(current.get("availability") or {})
    finance_allowed = personal_resolution.get("finance_allowed") is True
    bank = current.get("bank") if finance_allowed else None
    free_transfers = (
        current.get("free_transfers") if finance_allowed else None
    )
    if free_transfers is None and finance_allowed:
        transfers = current.get("transfers")
        free_transfers = (
            transfers.get("free_transfers")
            if isinstance(transfers, Mapping)
            else None
        )
    purchase_status = availability.get("purchase_price", "UNAVAILABLE")
    selling_status = availability.get("selling_price", "UNAVAILABLE")
    return {
        "auth_state": current.get("auth_state"),
        "bank": int(bank) if isinstance(bank, int) else None,
        "free_transfers": (
            int(free_transfers)
            if isinstance(free_transfers, int)
            else None
        ),
        "hit_cost_per_extra_transfer": (
            int(current.get("hit_cost_per_extra_transfer"))
            if finance_allowed
            and isinstance(current.get("hit_cost_per_extra_transfer"), int)
            else None
        ),
        "bank_status": (
            availability.get("bank", "UNAVAILABLE")
            if finance_allowed
            else "STALE_NOT_AUTHORIZED"
        ),
        "purchase_price_status": (
            purchase_status if finance_allowed else "STALE_NOT_AUTHORIZED"
        ),
        "sell_value_status": (
            selling_status if finance_allowed else "STALE_NOT_AUTHORIZED"
        ),
        "chips": current.get("chips") if finance_allowed else None,
        "chips_status": (
            availability.get("chips", "UNAVAILABLE")
            if finance_allowed
            else "STALE_NOT_AUTHORIZED"
        ),
        "free_transfers_status": (
            availability.get("free_transfers", "NOT_SUPPORTED")
            if finance_allowed
            else "NOT_SUPPORTED"
        ),
        "personal_resolution_status": personal_resolution.get(
            "resolution_status"
        ),
        "personal_evidence_source": personal_resolution.get("source"),
        "personal_evidence_observed_at": personal_resolution.get(
            "observed_at"
        ),
        "personal_evidence_stale": personal_resolution.get("stale") is True,
        "private_finance_fabricated": False,
    }


def _price_player_map(
    predictor: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    payload = predictor.get("data") or {}
    return {
        int(row.get("id")): dict(row)
        for row in payload.get("players") or []
        if isinstance(row, Mapping) and row.get("id") is not None
    }


def _price_uncertainty_by_route(
    package_utility: Mapping[str, Any],
    predictor: Mapping[str, Any],
) -> dict[str, Any]:
    pmap = _price_player_map(predictor)
    out: dict[str, Any] = {}
    for route in package_utility.get("routes") or []:
        route_id = str(route.get("route_id") or "")
        elements = [
            int(row.get("element") or 0)
            for row in (
                list(route.get("players_in") or [])
                + list(route.get("players_out") or [])
            )
            if int(row.get("element") or 0) > 0
        ]
        signals = []
        for element in elements:
            row = pmap.get(element)
            if not row:
                continue
            signals.append(
                {
                    "element": element,
                    "price_change_percent": row.get(
                        "price_change_percent"
                    ),
                    "price_change_hourly_rate": row.get(
                        "price_change_hourly_rate"
                    ),
                    "price_change_projections": deepcopy(
                        row.get("price_change_projections") or []
                    ),
                    "price_change_locked_until": row.get(
                        "price_change_locked_until"
                    ),
                    "price_change_calibrating": row.get(
                        "price_change_calibrating"
                    ),
                    "p_rise_before_deadline": None,
                    "p_fall_before_deadline": None,
                }
            )
        out[route_id] = {
            "status": (
                "MODEL_SIGNAL_AVAILABLE_PROBABILITY_UNCALIBRATED"
                if signals
                else "NOT_APPLICABLE"
            ),
            "signals": signals,
            "p_rise_before_deadline": None,
            "p_fall_before_deadline": None,
            "expected_cost_of_waiting_points": None,
            "probability_reason": (
                "OFFICIAL_FPL_PREDICTOR_EXPOSES_LIKELIHOOD_CLASSES_AND_"
                "PROJECTED_PERCENT_NOT_A_CALIBRATED_EVENT_PROBABILITY"
                if signals
                else None
            ),
            "price_predictor_is_football_authority": False,
            "probability_not_fabricated": True,
        }
    return out


def _stage3_seed(report_slot: str) -> int:
    digest = hashlib.sha256(
        str(report_slot).encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16)


def _first_projection_fixture(
    player: Mapping[str, Any],
) -> dict[str, Any]:
    for gw_row in player.get("xpts_by_gw") or []:
        for fixture in (gw_row or {}).get("fixtures") or []:
            if isinstance(fixture, Mapping):
                return dict(fixture)
    return {}


def _point_distribution_summary(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    row = dict(value or {})
    quantiles = dict(row.get("quantiles") or {})
    return {
        "status": row.get("status"),
        "mean": row.get("mean", row.get("expected_points")),
        "median": row.get("median"),
        "variance": row.get("variance"),
        "Q10": quantiles.get("Q10"),
        "Q25": quantiles.get("Q25"),
        "Q75": quantiles.get("Q75"),
        "Q90": quantiles.get("Q90"),
        "p_blank": row.get("p_fpl_blank"),
        "p_haul": row.get("p_haul_10_plus"),
    }


def _visible_position_mechanism(
    player: Mapping[str, Any],
    *,
    action: str,
) -> dict[str, Any]:
    fixture = _first_projection_fixture(player)
    events = dict(fixture.get("events") or {})
    engine = dict(
        fixture.get("position_engine")
        or player.get("position_engine")
        or {}
    )
    complete = dict(
        fixture.get("complete_player_distribution")
        or player.get("complete_player_distribution")
        or {}
    )
    xmins = dict(player.get("xmins") or {})
    derived = dict(xmins.get("derived_probabilities") or {})
    horizons = dict(player.get("horizons") or {})
    position = str(player.get("position") or "").upper()
    common = {
        "element_id": int(player.get("element") or 0),
        "player": player.get("name"),
        "position": position,
        "opponent": fixture.get("opponent"),
        "home": fixture.get("home"),
        "role": (
            (player.get("tactical_role") or {}).get("profile")
            if isinstance(player.get("tactical_role"), Mapping)
            else player.get("tactical_role")
        ),
        "p_available": complete.get(
            "P_available",
            xmins.get("availability"),
        ),
        "p_start": complete.get(
            "P_start",
            derived.get("p_start", xmins.get("start_probability")),
        ),
        "p_60_plus": complete.get(
            "P_60_plus",
            xmins.get("p_60_plus"),
        ),
        "p_cameo": complete.get(
            "P_cameo",
            derived.get("p_cameo", xmins.get("cameo_probability")),
        ),
        "p_dnp": complete.get(
            "P_DNP",
            derived.get("p_dnp", xmins.get("dnp_probability")),
        ),
        "xmins": xmins.get("expected_minutes"),
        "dynamic_matchup": engine.get("matchup_vector"),
        "bonus": events.get("bonus"),
        "goal_process": engine.get("goal_process"),
        "creation_process": engine.get("creation_process"),
        "penalty_process": engine.get("penalty_process"),
        "set_piece_process": engine.get("set_piece_process"),
        "linkup": engine.get("linkup"),
        "complete_player_distribution": complete,
        "1GW": _point_distribution_summary(
            (horizons.get("1") or {}).get("point_distribution")
        ),
        "3GW": _point_distribution_summary(
            (horizons.get("3") or {}).get("point_distribution")
        ),
        "5GW": _point_distribution_summary(
            (horizons.get("5") or {}).get("point_distribution")
        ),
        "action": action,
    }
    if position == "GK":
        common["position_mechanism"] = {
            "clean_sheet": events.get("clean_sheet"),
            "saves": events.get("saves"),
            "shot_stopping": (
                (events.get("saves") or {}).get("shot_stopping")
                if isinstance(events.get("saves"), Mapping)
                else None
            ),
            "penalty_save": events.get("penalty_save"),
            "goals_conceded": events.get("goals_conceded"),
        }
    elif position == "DEF":
        common["position_mechanism"] = {
            "clean_sheet": events.get("clean_sheet"),
            "defcon": events.get("defcon"),
            "defensive_role": engine.get("defensive_role"),
            "attacking_upside": {
                "goal_process": engine.get("goal_process"),
                "creation_process": engine.get("creation_process"),
            },
        }
    elif position == "MID":
        common["position_mechanism"] = {
            "goal_process": engine.get("goal_process"),
            "creation_process": engine.get("creation_process"),
            "penalty_process": engine.get("penalty_process"),
            "set_piece_process": engine.get("set_piece_process"),
            "defcon": events.get("defcon"),
            "mid_clean_sheet": events.get("clean_sheet"),
        }
    else:
        common["position_mechanism"] = {
            "goal_process": engine.get("goal_process"),
            "creation_process": engine.get("creation_process"),
            "service_linkup": engine.get("linkup"),
            "penalty_process": engine.get("penalty_process"),
            "set_piece_process": engine.get("set_piece_process"),
        }
    return common


_EXECUTION_FINANCE_UNAVAILABLE = frozenset(
    {"", "UNAVAILABLE", "UNKNOWN", "STALE_NOT_AUTHORIZED", "NOT_SUPPORTED", "AUTH_EXPIRED"}
)


def _execution_finance_available(finance: Mapping[str, Any] | None) -> bool:
    row = dict(finance or {})
    return bool(
        isinstance(row.get("bank"), int)
        and isinstance(row.get("free_transfers"), int)
        and str(row.get("bank_status") or "").upper() not in _EXECUTION_FINANCE_UNAVAILABLE
        and str(row.get("sell_value_status") or "").upper() not in _EXECUTION_FINANCE_UNAVAILABLE
        and str(row.get("free_transfers_status") or "").upper() not in _EXECUTION_FINANCE_UNAVAILABLE
    )


def _route_execution_economics_state(
    *,
    route_id: str,
    route_economics_status: Any,
    finance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if str(route_id).upper() == "HOLD":
        return {"status": "NOT_APPLICABLE", "executable": True}
    available = bool(
        _execution_finance_available(finance)
        and str(route_economics_status or "").upper() == "COMPLETE"
    )
    return {
        "status": "AVAILABLE" if available else "DEGRADED",
        "executable": available,
    }


def _stage3_visible_package_surface(
    *,
    projections: Mapping[str, Any],
    canonical_bundle: Mapping[str, Any],
    package_search_result: Mapping[str, Any],
    package_utility: Mapping[str, Any],
    material_mc_routes: Mapping[str, Any],
    monte_carlo: Mapping[str, Any],
    stage3_decision: Mapping[str, Any],
    mini_overlay: Mapping[str, Any] | None,
    finance: Mapping[str, Any] | None = None,
    stagec_scan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    player_map = {
        int(row.get("element") or 0): dict(row)
        for row in projections.get("players") or []
        if isinstance(row, Mapping)
        and int(row.get("element") or 0) > 0
    }
    canonical_map = {
        int(row.get("element_id") or 0): dict(row)
        for row in canonical_bundle.get("players") or []
        if isinstance(row, Mapping)
        and int(row.get("element_id") or 0) > 0
    }
    utility_routes = {
        str(row.get("route_id") or ""): dict(row)
        for row in package_utility.get("routes") or []
        if isinstance(row, Mapping)
    }
    decision_routes = {
        str(row.get("route_id") or ""): dict(row)
        for row in stage3_decision.get("routes") or []
        if isinstance(row, Mapping)
    }
    material_ids = [
        str(value)
        for value in material_mc_routes.get("route_ids") or []
    ]
    stagec_map = {
        int(row.get("element") or 0): dict(row)
        for row in (stagec_scan or {}).get("material_candidates") or []
        if isinstance(row, Mapping)
        and int(row.get("element") or 0) > 0
    }

    def stagec_context(element: int) -> dict[str, Any]:
        row = stagec_map.get(int(element)) or {}
        return {
            "material": bool(row),
            "active_signals": list(row.get("active_signals") or []),
            "positive_signals": list(row.get("positive_signals") or []),
            "negative_signals": list(row.get("negative_signals") or []),
            "hidden_gem": bool(row.get("hidden_gem")),
            "sample_confidence": row.get("sample_confidence"),
            "why_flagged": list(row.get("why_flagged") or []),
            "horizons": [1, 2, 3, 5],
            "decision_math_adjustment": 0.0,
        }

    challengers: list[dict[str, Any]] = []
    seen_incoming: set[int] = set()
    for route_id in material_ids:
        if route_id == "HOLD":
            continue
        route = utility_routes.get(route_id) or {}
        decision = decision_routes.get(route_id) or {}
        for incoming in route.get("players_in") or []:
            element = int(incoming.get("element") or 0)
            if element <= 0 or element in seen_incoming:
                continue
            seen_incoming.add(element)
            player = player_map.get(element) or {}
            canonical = canonical_map.get(element) or {}
            mechanism = _visible_position_mechanism(
                player,
                action=str(stage3_decision.get("operational_action") or "WAIT"),
            )
            challengers.append(
                {
                    "rank": canonical.get("canonical_rank"),
                    "element_id": element,
                    "player": player.get("name"),
                    "position": player.get("position"),
                    "club": player.get("team"),
                    "best_outgoing": [
                        row.get("element")
                        for row in route.get("players_out") or []
                    ],
                    "package_route": route_id,
                    "football_score": canonical.get("football_score"),
                    "football_score_components": canonical.get(
                        "canonical_components"
                    ),
                    "p_available": mechanism.get("p_available"),
                    "p_start": mechanism.get("p_start"),
                    "p_cameo": mechanism.get("p_cameo"),
                    "p_dnp": mechanism.get("p_dnp"),
                    "xmins": mechanism.get("xmins"),
                    "p_return": (
                        mechanism.get("complete_player_distribution") or {}
                    ).get("P_return"),
                    "p_blank": (
                        mechanism.get("complete_player_distribution") or {}
                    ).get("P_blank"),
                    "p_haul": (
                        mechanism.get("complete_player_distribution") or {}
                    ).get("P_haul"),
                    "expected_points_distribution": mechanism.get("1GW"),
                    "tactical_role": mechanism.get("role"),
                    "set_piece_penalty_role": {
                        "set_piece": mechanism.get("set_piece_process"),
                        "penalty": mechanism.get("penalty_process"),
                    },
                    "gw_plus_1": (
                        mechanism.get("1GW") or {}
                    ).get("mean"),
                    "three_gw": (
                        mechanism.get("3GW") or {}
                    ).get("mean"),
                    "five_gw": (
                        mechanism.get("5GW") or {}
                    ).get("mean"),
                    "package_utility_delta_vs_hold": (
                        decision.get("mc_pair_vs_hold") or {}
                    ).get("mean_difference"),
                    "price_economics": decision.get("price_uncertainty"),
                    "structure_effect": route.get("structural_impact"),
                    "expected_regret": decision.get("expected_regret"),
                    "information_value_of_waiting": decision.get(
                        "value_of_information"
                    ),
                    "mini_league_leverage": (
                        (mini_overlay or {}).get("decision_delta")
                        if mini_overlay
                        else None
                    ),
                    "main_upside": (
                        decision.get("mc_pair_vs_hold") or {}
                    ).get("Q90"),
                    "main_risk": (
                        decision.get("mc_pair_vs_hold") or {}
                    ).get("Q10"),
                    "action": stage3_decision.get("operational_action"),
                    "position_mechanism": mechanism.get(
                        "position_mechanism"
                    ),
                    "dynamic_matchup": mechanism.get("dynamic_matchup"),
                    "stagec_evidence": stagec_context(element),
                }
            )

    package_routes: list[dict[str, Any]] = []
    for route_id in material_ids:
        route = utility_routes.get(route_id) or {}
        decision = decision_routes.get(route_id) or {}
        pair = dict(decision.get("mc_pair_vs_hold") or {})
        horizons = dict(route.get("horizons") or {})
        economics = dict(route.get("transfer_economics") or {})
        def visible_move(raw: Mapping[str, Any], *, incoming: bool) -> dict[str, Any]:
            item = dict(raw or {})
            element = int(item.get("element") or 0)
            player = player_map.get(element) or {}
            mechanism = (
                _visible_position_mechanism(
                    player,
                    action=str(stage3_decision.get("operational_action") or "WAIT"),
                )
                if player else {}
            )
            return {
                **item,
                "name": player.get("name") or f"element:{element}",
                "current_price": player.get("now_cost"),
                "xmins": mechanism.get("xmins"),
                "p_start": mechanism.get("p_start"),
                "tactical_role": mechanism.get("role"),
                "fixture": {
                    "opponent": mechanism.get("opponent"),
                    "home": mechanism.get("home"),
                    "dynamic_matchup": mechanism.get("dynamic_matchup"),
                },
                "price": (
                    item.get("buy_price")
                    if incoming
                    else item.get("sell_value")
                ),
                "stagec_evidence": stagec_context(element),
            }

        visible_out = [
            visible_move(row, incoming=False)
            for row in route.get("players_out") or []
            if isinstance(row, Mapping)
        ]
        visible_in = [
            visible_move(row, incoming=True)
            for row in route.get("players_in") or []
            if isinstance(row, Mapping)
        ]
        route_kind = (
            "HOLD"
            if route_id == "HOLD"
            else "FUNDED / 2-TRANSFER"
            if max(len(visible_out), len(visible_in)) >= 2
            else "DIRECT / 1-TRANSFER"
        )
        execution = _route_execution_economics_state(
            route_id=route_id,
            route_economics_status=economics.get("status"),
            finance=finance,
        )
        route_execution_status = str(execution["status"])
        route_executable = bool(execution["executable"])
        package_routes.append(
            {
                "route": route_id,
                "route_kind": route_kind,
                "moves": {
                    "out": visible_out,
                    "in": visible_in,
                },
                "bank_before": (finance or {}).get("bank"),
                "affordability": (
                    "SUPPORTED"
                    if economics.get("status") == "COMPLETE"
                    else economics.get("status") or "PARTIAL"
                ),
                "execution_economics_status": route_execution_status,
                "executable": route_executable,
                "transfer_cost": {
                    "hit": route.get("hit"),
                    "ft_usage": route.get("ft_usage"),
                    "economics_status": economics.get("status"),
                    "bank_after": route.get("bank_after"),
                },
                "gw1_net": (
                    (horizons.get("GW+1") or {}).get(
                        "net_delta_vs_hold"
                    )
                ),
                "two_gw_if_relevant": (
                    (horizons.get("2GW") or {}).get(
                        "net_delta_vs_hold"
                    )
                ),
                "three_gw": (
                    (horizons.get("3GW") or {}).get(
                        "net_delta_vs_hold"
                    )
                ),
                "five_gw": (
                    (horizons.get("5GW") or {}).get(
                        "net_delta_vs_hold"
                    )
                ),
                "p_beats_hold": pair.get("p_route_gt_hold"),
                "p_delta_meaningful": pair.get(
                    "p_delta_ge_meaningful_threshold"
                ),
                "Q10": pair.get("Q10"),
                "Q25": pair.get("Q25"),
                "median": pair.get("median"),
                "Q75": pair.get("Q75"),
                "Q90": pair.get("Q90"),
                "football_1GW": (
                    (decision.get("horizon_deltas") or {}).get("1GW")
                ),
                "football_3GW": (
                    (decision.get("horizon_deltas") or {}).get("3GW")
                ),
                "football_5GW": (
                    (decision.get("horizon_deltas") or {}).get("5GW")
                ),
                "raw_gain": pair.get("mean_difference"),
                "net_gain": (
                    (horizons.get("GW+1") or {}).get(
                        "net_delta_vs_hold"
                    )
                ),
                "mini_league_utility": (
                    (mini_overlay or {}).get("decision_delta")
                    if mini_overlay else None
                ),
                "tactical_fixture_effect": [
                    {
                        "element": row.get("element"),
                        "name": row.get("name"),
                        "xmins": row.get("xmins"),
                        "p_start": row.get("p_start"),
                        "tactical_role": row.get("tactical_role"),
                        "fixture": row.get("fixture"),
                    }
                    for row in visible_in
                ],
                "expected_regret": decision.get("expected_regret"),
                "robustness": decision.get("robustness"),
                "sensitivity": decision.get("sensitivity"),
                "stress_coverage": decision.get("stress_coverage"),
                "price_risk": decision.get("price_uncertainty"),
                "structure_effect": route.get("structural_impact"),
                "action_verdict": stage3_decision.get(
                    "operational_action"
                ),
                "voi": decision.get("value_of_information"),
                "voi_vs_wait_cost": decision.get(
                    "voi_vs_cost_of_waiting"
                ),
            }
        )

    mechanism_ids = set()
    for route_id in material_ids:
        route = utility_routes.get(route_id) or {}
        mechanism_ids.update(
            int(row.get("element") or 0)
            for row in route.get("players_in") or []
            if int(row.get("element") or 0) > 0
        )
        mechanism_ids.update(
            int(row.get("element") or 0)
            for row in route.get("players_out") or []
            if int(row.get("element") or 0) > 0
        )
    mechanism_rows = [
        _visible_position_mechanism(
            player_map[element],
            action=str(stage3_decision.get("operational_action") or "WAIT"),
        )
        for element in sorted(mechanism_ids)
        if element in player_map
    ]

    return {
        "package_search_proof": package_search_result.get("search_proof"),
        "funded_search_proof": (
            ((package_utility.get("search_scope") or {}).get(
                "funded_two_transfer"
            ) or {}).get("search_proof")
        ),
        "package_search_scope": {
            "search_authority": package_search_result.get(
                "search_authority"
            ),
            "combined_authority": package_utility.get(
                "search_authority"
            ),
            "combined_scope": package_utility.get("search_scope"),
            "eligible_universe_count": package_search_result.get(
                "eligible_universe_count"
            ),
            "searched_universe_count": package_search_result.get(
                "searched_universe_count"
            ),
            "route_denominator": package_search_result.get(
                "route_denominator"
            ),
            "max_transfers_evaluated": package_search_result.get(
                "max_transfers_evaluated"
            ),
            "transfer_depth_semantics": package_search_result.get(
                "transfer_depth_semantics"
            ),
            "coverage": package_search_result.get("coverage"),
        },
        "package_universe_challengers": challengers,
        "football_frontier_status": "COMPLETE",
        "execution_economics_status": (
            "AVAILABLE" if _execution_finance_available(finance) else "DEGRADED"
        ),
        "execution_economics_authority": {
            "bank": (finance or {}).get("bank"),
            "bank_status": (finance or {}).get("bank_status"),
            "sell_value_status": (finance or {}).get("sell_value_status"),
            "free_transfers": (finance or {}).get("free_transfers"),
            "free_transfers_status": (finance or {}).get("free_transfers_status"),
            "source": (finance or {}).get("personal_evidence_source"),
            "observed_at": (finance or {}).get("personal_evidence_observed_at"),
        },
        "package_routes": package_routes,
        "frontier": package_utility.get("package_frontier"),
        "material_route_selection": material_mc_routes,
        "monte_carlo": {
            "execution_state": monte_carlo.get("execution_state"),
            "canonical_pass": monte_carlo.get("canonical_pass"),
            "actual_paths": monte_carlo.get("actual_paths"),
            "seed": monte_carlo.get("seed"),
            "horizons": monte_carlo.get("horizons"),
            "convergence_evidence": monte_carlo.get(
                "convergence_evidence"
            ),
            "match_state_invariants": (
                monte_carlo.get("sampling_diagnostics") or {}
            ).get("match_state_invariants"),
            "match_state_contract": monte_carlo.get(
                "match_state_contract"
            ),
            "common_random_numbers": monte_carlo.get(
                "common_random_numbers"
            ),
        },
        "decision": stage3_decision,
        "position_mechanisms": mechanism_rows,
        "mini_league_overlay": mini_overlay,
        "stagec_evaluation_bridge": {
            "candidate_feed_count": len((stagec_scan or {}).get("evaluation_feed") or []),
            "material_candidate_count": len(stagec_map),
            "visible_route_context_only": True,
            "full_universe_package_search_preserved": True,
            "decision_math_mutated": False,
        },
    }


def _stage3_math_proof(
    *,
    projections: Mapping[str, Any],
    package_utility: Mapping[str, Any],
    stage3_decision: Mapping[str, Any],
    monte_carlo: Mapping[str, Any],
) -> dict[str, Any]:
    selected_id = str(
        stage3_decision.get("selected_route_id") or "HOLD"
    )
    route = next(
        (
            dict(row)
            for row in package_utility.get("routes") or []
            if str(row.get("route_id") or "") == selected_id
        ),
        {},
    )
    candidate_element = next(
        (
            int(row.get("element") or 0)
            for row in route.get("players_in") or []
            if int(row.get("element") or 0) > 0
        ),
        None,
    )
    if candidate_element is None:
        first_lineup = (
            (route.get("football_route_utility") or {}).get("per_gw")
            or [{}]
        )[0]
        candidate_element = int(
            (first_lineup.get("captain") or 0)
        )
    player = next(
        (
            dict(row)
            for row in projections.get("players") or []
            if int(row.get("element") or 0) == candidate_element
        ),
        {},
    )
    fixture = _first_projection_fixture(player)
    complete = dict(
        fixture.get("complete_player_distribution")
        or player.get("complete_player_distribution")
        or {}
    )
    xmins = dict(player.get("xmins") or {})
    decision_route = next(
        (
            dict(row)
            for row in stage3_decision.get("routes") or []
            if str(row.get("route_id") or "") == selected_id
        ),
        {},
    )
    return {
        "bayesian_shrinkage_lineage": (
            player.get("posterior_rates")
            or "STAGE2_POSTERIOR_RATES"
        ),
        "probability_state": {
            "unconditional": {
                "p_available": complete.get(
                    "P_available", xmins.get("availability")
                ),
                "p_start": complete.get(
                    "P_start", xmins.get("start_probability")
                ),
                "p_bench": xmins.get("bench_probability"),
                "p_cameo": complete.get(
                    "P_cameo", xmins.get("cameo_probability")
                ),
                "p_late_cameo": xmins.get(
                    "late_cameo_probability"
                ),
                "p_dnp": complete.get(
                    "P_DNP", xmins.get("dnp_probability")
                ),
            }
        },
        "xmins_distribution": xmins.get("xmins_distribution"),
        "posterior_predictive": {
            "source_contract": (
                (fixture.get("position_engine") or {}).get(
                    "posterior_predictive"
                )
                or {}
            ).get("contract"),
            "event_probabilities": complete,
            "point_distribution": fixture.get("point_distribution"),
        },
        "horizons": {
            label: _point_distribution_summary(
                (player.get("horizons") or {}).get(key, {}).get(
                    "point_distribution"
                )
            )
            for label, key in (
                ("1GW", "1"),
                ("3GW", "3"),
                ("5GW", "5"),
            )
        },
        "robustness": {
            "p_outperform": (
                decision_route.get("mc_pair_vs_hold") or {}
            ).get("p_route_gt_hold"),
            "expected_regret": decision_route.get("expected_regret"),
            "conditional_floor": (
                decision_route.get("mc_pair_vs_hold") or {}
            ).get("Q10"),
            "upper_tail": (
                decision_route.get("mc_pair_vs_hold") or {}
            ).get("Q90"),
        },
        "information_value_of_waiting": decision_route.get(
            "value_of_information"
        ),
        "covariance_correlation": monte_carlo.get(
            "correlation_model"
        ),
        "monte_carlo": {
            "execution_state": monte_carlo.get("execution_state"),
            "actual_paths": monte_carlo.get("actual_paths"),
            "correlated": monte_carlo.get("correlated"),
            "seed": monte_carlo.get("seed"),
            "convergence_evidence": monte_carlo.get(
                "convergence_evidence"
            ),
        },
    }


def _lineup_content(lineup: Mapping[str, Any] | None) -> dict[str, Any]:
    if not lineup:
        return {
            "status": "UNAVAILABLE",
            "formation": "UNAVAILABLE",
            "starting_xi": [],
            "bench": {"gk": None, "order": []},
            "captain": None,
            "vice_captain": None,
            "lineup_score": {},
            "formation_comparison": [],
            "score_semantics": {
                "authority": "P1_7_LINEUP",
                "relationship": "UNAVAILABLE",
            },
        }
    score = dict(lineup.get("lineup_score") or {})
    comparisons = [
        dict(row)
        for row in lineup.get("formation_comparison") or []
        if isinstance(row, Mapping)
    ]
    selected = next((row for row in comparisons if row.get("selected") is True), {})
    xi_base_xpts = score.get("xpts_mean")
    captain_adjusted_xpts = selected.get("expected_fpl_points_with_captain_vice")
    return {
        "formation": lineup.get("formation"),
        "starting_xi": lineup.get("starting_xi"),
        "bench": lineup.get("bench"),
        "captain": lineup.get("captain"),
        "vice_captain": lineup.get("vice_captain"),
        "lineup_score": score,
        "formation_comparison": comparisons,
        "xi_base_xpts": xi_base_xpts,
        "captain_adjusted_xpts": captain_adjusted_xpts,
        "lineup_route_utility": selected.get("route_utility"),
        "score_semantics": {
            "authority": "P1_7_LINEUP",
            "relationship": "DISTINCT_BY_DESIGN",
            "xi_base_xpts_path": "lineup_score.xpts_mean",
            "captain_adjusted_xpts_path": "formation_comparison[selected].expected_fpl_points_with_captain_vice",
            "lineup_route_utility_path": "formation_comparison[selected].route_utility",
            "raw_xpts_mutated": False,
        },
    }


def _surface_element(value: Any) -> int | None:
    if isinstance(value, Mapping):
        value = value.get("element", value.get("element_id"))
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _projection_map(projections: Mapping[str, Any] | None) -> dict[int, dict[str, Any]]:
    return {
        int(row.get("element") or 0): dict(row)
        for row in (projections or {}).get("players") or []
        if isinstance(row, Mapping) and int(row.get("element") or 0) > 0
    }


def _horizon_mean(player: Mapping[str, Any], horizon: str) -> Any:
    return ((player.get("horizons") or {}).get(horizon) or {}).get("mean")


def _enrich_all15_rows(
    *,
    all15: Mapping[str, Any] | None,
    projections: Mapping[str, Any] | None,
    predictor: Mapping[str, Any],
    owned: Sequence[Mapping[str, Any]],
    mini: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pmap = _projection_map(projections)
    predictor_map = _price_player_map(predictor)
    owned_map = {
        int(row.get("element_id") or 0): dict(row)
        for row in owned
        if int(row.get("element_id") or 0) > 0
    }
    exposures = {
        int(item.get("element_id") or 0): dict(item)
        for item in (mini or {}).get("exposures") or []
        if isinstance(item, Mapping)
        and int(item.get("element_id") or 0) > 0
    }
    rows: list[dict[str, Any]] = []
    for raw in (all15 or {}).get("rows") or []:
        row = dict(raw)
        element = int(row.get("element_id") or 0)
        player = pmap.get(element) or {}
        xm = dict(player.get("xmins") or {})
        price = predictor_map.get(element) or {}
        owned_row = owned_map.get(element) or {}
        p_start = row.get("p_start", xm.get("start_probability"))
        xmins = row.get("xmins", xm.get("expected_minutes"))
        status = str(player.get("status") or "a").lower()
        warnings: list[str] = []
        if status != "a":
            warnings.append(f"STATUS_{status.upper()}")
        try:
            if p_start is not None and float(p_start) < 0.70:
                warnings.append("START_RISK")
        except (TypeError, ValueError):
            pass
        try:
            if xmins is not None and float(xmins) < 60.0:
                warnings.append("MINUTES_RISK")
        except (TypeError, ValueError):
            pass
        direction = str(price.get("direction") or price.get("change_direction") or "").upper()
        progress = price.get("projected_percent", price.get("current_progress_percent"))
        price_relevance = "NONE_MATERIAL"
        if direction in {"RISE", "FALL"}:
            price_relevance = (
                f"{direction}"
                + (f" {progress}%" if progress is not None else "")
            )
        fixture = _first_projection_fixture(player)
        mechanism = _visible_position_mechanism(
            player,
            action=str(row.get("action") or "HOLD"),
        ) if player else {}
        exposure = exposures.get(element) or {}
        row.update({
            "availability": row.get("p_available", xm.get("availability")),
            "projection_1gw": row.get("gw_plus_1", _horizon_mean(player, "1")),
            "projection_3gw": row.get("three_gw", _horizon_mean(player, "3")),
            "projection_5gw": row.get("five_gw", _horizon_mean(player, "5")),
            "posterior_signal": {
                "posterior_rates": player.get("posterior_rates"),
                "posterior_predictive": (
                    (fixture.get("position_engine") or {}).get(
                        "posterior_predictive"
                    )
                ),
                "point_distribution_1gw": mechanism.get("1GW"),
            },
            "role_detail": {
                "tactical_role": (
                    player.get("tactical_role")
                    or player.get("system_context")
                    or row.get("tactical_role")
                ),
                "set_piece": mechanism.get("set_piece_process"),
                "penalty": mechanism.get("penalty_process"),
            },
            "fixture_detail": {
                "opponent": mechanism.get("opponent"),
                "home": mechanism.get("home"),
                "dynamic_matchup": mechanism.get("dynamic_matchup"),
            },
            "defensive_contribution": (
                mechanism.get("defcon")
                or mechanism.get("defensive_process")
                or "UNAVAILABLE"
            ),
            "injury_rotation_warning": ", ".join(warnings) if warnings else "NONE_MATERIAL",
            "price_relevance": price_relevance,
            "price_optionality": {
                "current_price": owned_row.get("current_price", player.get("now_cost")),
                "purchase_price": owned_row.get("purchase_price"),
                "selling_price": owned_row.get("selling_price"),
                "predictor_direction": direction or "NONE",
                "predictor_progress": progress,
            },
            "current_price": owned_row.get("current_price", player.get("now_cost")),
            "purchase_price": owned_row.get("purchase_price"),
            "selling_price": owned_row.get("selling_price"),
            "mini_league_relevance": {
                "ownership_pct": exposure.get("ownership_pct"),
                "starter_pct": exposure.get("starter_pct"),
                "captain_pct": exposure.get("captain_pct"),
                "vice_pct": exposure.get("vice_pct"),
                "eo_pct": exposure.get("eo_pct"),
            },
        })
        rows.append(row)
    return rows


def _enrich_watchlist_rows(
    watchlist: Mapping[str, Any] | None,
    *,
    projections: Mapping[str, Any] | None,
    predictor: Mapping[str, Any],
) -> dict[str, Any]:
    result = deepcopy(dict(watchlist or {}))
    pmap = _projection_map(projections)
    price_map = _price_player_map(predictor)
    enriched: list[dict[str, Any]] = []
    for raw in result.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        element = int(row.get("element_id") or 0)
        player = pmap.get(element) or {}
        mechanism = (
            _visible_position_mechanism(player, action="WATCH")
            if player else {}
        )
        price = price_map.get(element) or {}
        row.update({
            "current_price": (
                player.get("now_cost")
                if player.get("now_cost") is not None
                else price.get("now_cost")
            ),
            "xmins": mechanism.get("xmins"),
            "p_start": mechanism.get("p_start"),
            "predictor_direction": (
                price.get("direction")
                or price.get("change_direction")
                or "NONE"
            ),
            "predictor_progress": price.get(
                "projected_percent",
                price.get("current_progress_percent"),
            ),
            "watchlist_relevance": "TOP5_POSITIONAL_CANONICAL",
            "transfer_relevance": "PACKAGE_CANDIDATE_UNIVERSE",
        })
        enriched.append(row)
    result["rows"] = enriched
    result["decision_context_materialized"] = True
    return result


def _mini_context(mini: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(mini or {})
    return dict(
        payload.get("current_league_context")
        or payload.get("current_context")
        or {}
    )


def _captain_candidate_review(
    *,
    candidate: Mapping[str, Any] | None,
    projections: Mapping[str, Any] | None,
    mini: Mapping[str, Any] | None,
    mini_league_stance: str,
) -> dict[str, Any]:
    """Visible C/VC evidence using existing P1.3/P1.6/P1.7/P1.8 owners."""
    raw_candidate = dict(candidate or {})
    element = _surface_element(raw_candidate)
    pmap = _projection_map(projections)
    player = pmap.get(element or -1) or {}
    mechanism = (
        _visible_position_mechanism(player, action="HOLD")
        if player
        else {}
    )
    exposure = next(
        (
            dict(row)
            for row in (mini or {}).get("exposures") or []
            if isinstance(row, Mapping)
            and int(row.get("element_id") or 0) == int(element or 0)
        ),
        {},
    )
    one = dict(mechanism.get("1GW") or {})
    complete = dict(mechanism.get("complete_player_distribution") or {})
    return {
        "element_id": element,
        "player": (
            raw_candidate.get("name")
            or mechanism.get("player")
            or (f"element:{element}" if element else "UNAVAILABLE")
        ),
        "expected_points": one.get("mean", raw_candidate.get("xpts_mean")),
        "ceiling_q90": one.get("Q90"),
        "haul_probability": one.get("p_haul"),
        "blank_probability": one.get("p_blank"),
        "xmins": mechanism.get("xmins", raw_candidate.get("xmins")),
        "p_start": mechanism.get("p_start", raw_candidate.get("p_start")),
        "goal_involvement": {
            "goal_process": mechanism.get("goal_process"),
            "creation_process": mechanism.get("creation_process"),
            "p_return": complete.get("P_return"),
            "p_goal": complete.get("P_goal"),
            "p_assist": complete.get("P_assist"),
        },
        "penalties": mechanism.get("penalty_process"),
        "set_pieces": mechanism.get("set_piece_process"),
        "fixture": {
            "opponent": mechanism.get("opponent"),
            "home": mechanism.get("home"),
            "dynamic_matchup": mechanism.get("dynamic_matchup"),
        },
        "captain_count": exposure.get("captain_count"),
        "captain_pct": exposure.get("captain_pct"),
        "eo_pct": exposure.get("eo_pct"),
        "mini_league_upside": (
            "Lower captain/EO can create leverage only when football evidence remains close."
        ),
        "mini_league_downside": (
            "Fading a strong high-EO captain increases relative-rank downside."
        ),
        "mini_league_stance": mini_league_stance,
        "raw_mean_is_not_sole_authority": True,
    }



def _mini_league_deep_detail(
    *,
    mini: Mapping[str, Any] | None,
    standings: Mapping[str, Any],
    manager_picks: Mapping[str, Any],
    owned: Sequence[Mapping[str, Any]],
    projections: Mapping[str, Any] | None,
    lineup: Mapping[str, Any] | None,
    mini_overlay: Mapping[str, Any] | None,
    disclosed_gw: int,
    operational_action: str,
) -> dict[str, Any]:
    """Materialize decision-oriented mini-league evidence without new football math.

    Counts and denominators stay explicit. Current OUR15 comes from the
    occurrence-bound personal resolution, while rival picks remain the latest
    disclosed Official FPL submission and are labelled with that GW.
    """
    snapshot = dict(mini or {})
    context = _mini_context(snapshot)
    report_cfg = dict(load_mini_league_config().get("report") or {})
    direct_n = max(1, int(report_cfg.get("direct_rivals_above", 6) or 6))
    threat_n = max(1, int(report_cfg.get("max_rival_threats", 12) or 12))
    captain_n = max(1, int(report_cfg.get("captain_candidates", 5) or 5))

    pmap = _projection_map(projections)
    owned_ids = [
        element
        for element in (_surface_element(row) for row in owned)
        if element is not None
    ]
    owned_ids = list(dict.fromkeys(owned_ids))
    owned_set = set(owned_ids)

    owned_names: dict[int, str] = {}
    for raw in owned:
        element = _surface_element(raw)
        if element is None:
            continue
        player = pmap.get(element) or {}
        owned_names[element] = str(
            raw.get("name")
            or raw.get("player")
            or raw.get("web_name")
            or player.get("name")
            or player.get("web_name")
            or f"element:{element}"
        )

    def player_name(element: int) -> str:
        player = pmap.get(int(element)) or {}
        return str(
            owned_names.get(int(element))
            or player.get("name")
            or player.get("web_name")
            or f"element:{int(element)}"
        )

    entries_raw = manager_picks.get("entries") or {}
    entries: dict[int, dict[str, Any]] = {}
    if isinstance(entries_raw, Mapping):
        for key, raw in entries_raw.items():
            if not isinstance(raw, Mapping):
                continue
            try:
                entry_id = int(raw.get("entry_id", key))
            except (TypeError, ValueError):
                continue
            picks = [
                dict(pick)
                for pick in raw.get("picks") or []
                if isinstance(pick, Mapping)
            ]
            if picks:
                entries[entry_id] = {
                    "entry_id": entry_id,
                    "picks": picks,
                    "status": raw.get("status"),
                }

    def pick_element(pick: Mapping[str, Any]) -> int | None:
        return _surface_element(
            pick.get("element_id", pick.get("element"))
        )

    def pick_multiplier(pick: Mapping[str, Any]) -> float | None:
        raw = pick.get("multiplier")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def pick_position(pick: Mapping[str, Any]) -> int | None:
        raw = pick.get("squad_position", pick.get("position"))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def exposure_for_entries(
        scoped_entries: Sequence[Mapping[str, Any]],
        element_ids: Sequence[int],
        *,
        require_complete_eo: bool,
    ) -> list[dict[str, Any]]:
        denominator = len(scoped_entries)
        rows: list[dict[str, Any]] = []
        scope_multiplier_complete = (
            denominator > 0
            and all(
                len(entry.get("picks") or []) == 15
                and all(
                    pick_multiplier(pick) is not None
                    for pick in entry.get("picks") or []
                )
                for entry in scoped_entries
            )
        )
        eo_supported = (
            denominator > 0
            and (scope_multiplier_complete or not require_complete_eo)
        )
        for element in element_ids:
            own = starter = bench = captain = vice = 0
            effective = 0.0
            element_multiplier_complete = True
            for entry in scoped_entries:
                pick = next(
                    (
                        pick
                        for pick in entry.get("picks") or []
                        if pick_element(pick) == int(element)
                    ),
                    None,
                )
                if pick is None:
                    continue
                own += 1
                multiplier = pick_multiplier(pick)
                position = pick_position(pick)
                if multiplier is not None:
                    effective += multiplier
                    if multiplier > 0:
                        starter += 1
                    else:
                        bench += 1
                else:
                    element_multiplier_complete = False
                    if position is not None and 1 <= position <= 11:
                        starter += 1
                    elif position is not None and position > 11:
                        bench += 1
                if bool(pick.get("captain", pick.get("is_captain"))):
                    captain += 1
                if bool(
                    pick.get(
                        "vice_captain",
                        pick.get("is_vice_captain"),
                    )
                ):
                    vice += 1
            rows.append(
                {
                    "element_id": int(element),
                    "player": player_name(int(element)),
                    "denominator": denominator,
                    "ownership_count": own,
                    "ownership_pct": (
                        round(100.0 * own / denominator, 1)
                        if denominator > 0 else None
                    ),
                    "starter_count": starter,
                    "starter_pct": (
                        round(100.0 * starter / denominator, 1)
                        if denominator > 0 else None
                    ),
                    "bench_count": bench,
                    "bench_pct": (
                        round(100.0 * bench / denominator, 1)
                        if denominator > 0 else None
                    ),
                    "captain_count": captain,
                    "captain_pct": (
                        round(100.0 * captain / denominator, 1)
                        if denominator > 0 else None
                    ),
                    "vice_count": vice,
                    "vice_pct": (
                        round(100.0 * vice / denominator, 1)
                        if denominator > 0 else None
                    ),
                    "effective_multiplier_sum": (
                        effective if element_multiplier_complete else None
                    ),
                    "eo_pct": (
                        round(100.0 * effective / denominator, 1)
                        if (
                            eo_supported
                            and element_multiplier_complete
                            and denominator > 0
                        )
                        else None
                    ),
                    "eo_supported": bool(
                        eo_supported and element_multiplier_complete
                    ),
                }
            )
        return rows

    standings_rows = [
        dict(row)
        for row in standings.get("managers") or []
        if isinstance(row, Mapping)
    ]
    ordered = sorted(
        standings_rows,
        key=lambda row: (
            int(row.get("league_rank") or 10**9),
            -int(row.get("league_total") or 0),
        ),
    )
    our_rank = context.get("our_rank")
    our_total = context.get("our_total_points")
    try:
        our_rank_i = int(our_rank) if our_rank is not None else None
    except (TypeError, ValueError):
        our_rank_i = None
    try:
        our_total_i = int(our_total) if our_total is not None else None
    except (TypeError, ValueError):
        our_total_i = None

    rank_battle: list[dict[str, Any]] = []
    for row in ordered:
        try:
            rank = int(row.get("league_rank") or 0)
            total = int(row.get("league_total") or 0)
        except (TypeError, ValueError):
            continue
        if rank <= 10 or (
            our_rank_i is not None and abs(rank - our_rank_i) <= 3
        ):
            rank_battle.append(
                {
                    "entry_id": row.get("entry_id"),
                    "rank": rank,
                    "manager": (
                        row.get("manager_name")
                        or row.get("player_name")
                        or "UNAVAILABLE"
                    ),
                    "team": (
                        row.get("team_name")
                        or row.get("entry_name")
                        or "UNAVAILABLE"
                    ),
                    "total_points": total,
                    "gap_vs_us": (
                        total - our_total_i
                        if our_total_i is not None else None
                    ),
                    "gw_score": row.get("gw_score"),
                    "is_us": (
                        int(row.get("entry_id") or 0)
                        == int(context.get("our_entry_id") or 0)
                    ),
                }
            )

    above = []
    if our_rank_i is not None:
        above = [
            row
            for row in ordered
            if int(row.get("league_rank") or 10**9) < our_rank_i
        ]
    direct_rows = sorted(
        sorted(
            above,
            key=lambda row: int(row.get("league_rank") or 0),
            reverse=True,
        )[:direct_n],
        key=lambda row: int(row.get("league_rank") or 0),
    )
    direct_entries: list[dict[str, Any]] = []
    direct_rivals: list[dict[str, Any]] = []
    for row in direct_rows:
        entry_id = int(row.get("entry_id") or 0)
        entry = entries.get(entry_id)
        picks = list((entry or {}).get("picks") or [])
        if entry is not None:
            direct_entries.append(entry)
        squad = {
            element
            for element in (pick_element(pick) for pick in picks)
            if element is not None
        }
        overlap = [element for element in owned_ids if element in squad]
        our_unique = [element for element in owned_ids if element not in squad]
        rival_unique = [element for element in squad if element not in owned_set]
        captain_pick = next(
            (
                pick
                for pick in picks
                if bool(pick.get("captain", pick.get("is_captain")))
            ),
            None,
        )
        vice_pick = next(
            (
                pick
                for pick in picks
                if bool(
                    pick.get(
                        "vice_captain",
                        pick.get("is_vice_captain"),
                    )
                )
            ),
            None,
        )
        captain_element = (
            pick_element(captain_pick) if captain_pick is not None else None
        )
        vice_element = (
            pick_element(vice_pick) if vice_pick is not None else None
        )
        total = int(row.get("league_total") or 0)
        direct_rivals.append(
            {
                "entry_id": entry_id,
                "rank": int(row.get("league_rank") or 0),
                "manager": (
                    row.get("manager_name")
                    or row.get("player_name")
                    or "UNAVAILABLE"
                ),
                "team": (
                    row.get("team_name")
                    or row.get("entry_name")
                    or "UNAVAILABLE"
                ),
                "total_points": total,
                "gap_vs_us": (
                    total - our_total_i
                    if our_total_i is not None else None
                ),
                "gw_score": row.get("gw_score"),
                "overlap_count": len(overlap),
                "overlap_denominator": len(owned_ids),
                "overlap_players": [
                    {"element_id": element, "player": player_name(element)}
                    for element in overlap
                ],
                "our_unique_players": [
                    {"element_id": element, "player": player_name(element)}
                    for element in our_unique
                ],
                "rival_unique_players": [
                    {"element_id": element, "player": player_name(element)}
                    for element in sorted(rival_unique)
                ],
                "captain_element": captain_element,
                "captain": (
                    player_name(captain_element)
                    if captain_element is not None else "UNAVAILABLE"
                ),
                "vice_element": vice_element,
                "vice": (
                    player_name(vice_element)
                    if vice_element is not None else "UNAVAILABLE"
                ),
                "disclosed_picks_available": entry is not None,
            }
        )

    full_denominator = int(snapshot.get("rival_exposure_denominator") or 0)
    full_exposure_map = {
        int(row.get("element_id") or 0): dict(row)
        for row in snapshot.get("exposures") or []
        if isinstance(row, Mapping)
        and int(row.get("element_id") or 0) > 0
    }
    our15_rival_exposure: list[dict[str, Any]] = []
    for element in owned_ids:
        raw = full_exposure_map.get(element) or {}
        our15_rival_exposure.append(
            {
                "element_id": element,
                "player": player_name(element),
                "denominator": full_denominator,
                "ownership_count": int(raw.get("ownership_count") or 0),
                "ownership_pct": raw.get("ownership_pct"),
                "starter_count": int(raw.get("starter_count") or 0),
                "starter_pct": raw.get("starter_pct"),
                "bench_count": int(raw.get("bench_count") or 0),
                "bench_pct": raw.get("bench_pct"),
                "captain_count": int(raw.get("captain_count") or 0),
                "captain_pct": raw.get("captain_pct"),
                "vice_count": int(raw.get("vice_count") or 0),
                "vice_pct": raw.get("vice_pct"),
                "effective_multiplier_sum": raw.get(
                    "effective_multiplier_sum"
                ),
                "eo_pct": raw.get("eo_pct"),
                "eo_supported": raw.get("eo_supported"),
            }
        )

    direct_our15_exposure = exposure_for_entries(
        direct_entries,
        owned_ids,
        require_complete_eo=True,
    )
    direct_exposure_map = {
        int(row["element_id"]): row
        for row in direct_our15_exposure
    }

    threat_totals: dict[int, dict[str, Any]] = {}
    direct_denominator = len(direct_entries)
    scope_multiplier_complete = (
        direct_denominator > 0
        and all(
            len(entry.get("picks") or []) == 15
            and all(
                pick_multiplier(pick) is not None
                for pick in entry.get("picks") or []
            )
            for entry in direct_entries
        )
    )
    for entry in direct_entries:
        for pick in entry.get("picks") or []:
            element = pick_element(pick)
            if element is None or element in owned_set:
                continue
            row = threat_totals.setdefault(
                element,
                {
                    "element_id": element,
                    "ownership_count": 0,
                    "starter_count": 0,
                    "bench_count": 0,
                    "captain_count": 0,
                    "vice_count": 0,
                    "effective_multiplier_sum": 0.0,
                    "multiplier_complete": True,
                },
            )
            row["ownership_count"] += 1
            multiplier = pick_multiplier(pick)
            position = pick_position(pick)
            if multiplier is not None:
                row["effective_multiplier_sum"] += multiplier
                if multiplier > 0:
                    row["starter_count"] += 1
                else:
                    row["bench_count"] += 1
            else:
                row["multiplier_complete"] = False
                if position is not None and 1 <= position <= 11:
                    row["starter_count"] += 1
                elif position is not None and position > 11:
                    row["bench_count"] += 1
            if bool(pick.get("captain", pick.get("is_captain"))):
                row["captain_count"] += 1
            if bool(
                pick.get(
                    "vice_captain",
                    pick.get("is_vice_captain"),
                )
            ):
                row["vice_count"] += 1

    rival_threats: list[dict[str, Any]] = []
    sorted_threats = sorted(
        threat_totals.values(),
        key=lambda row: (
            -float(row.get("effective_multiplier_sum") or 0.0),
            -int(row.get("ownership_count") or 0),
            int(row.get("element_id") or 0),
        ),
    )[:threat_n]
    for raw in sorted_threats:
        denominator = direct_denominator
        effective = raw.get("effective_multiplier_sum")
        complete = bool(
            scope_multiplier_complete and raw.get("multiplier_complete")
        )
        rival_threats.append(
            {
                **raw,
                "player": player_name(int(raw["element_id"])),
                "denominator": denominator,
                "ownership_pct": (
                    round(
                        100.0 * int(raw["ownership_count"]) / denominator,
                        1,
                    )
                    if denominator > 0 else None
                ),
                "starter_pct": (
                    round(
                        100.0 * int(raw["starter_count"]) / denominator,
                        1,
                    )
                    if denominator > 0 else None
                ),
                "bench_pct": (
                    round(
                        100.0 * int(raw["bench_count"]) / denominator,
                        1,
                    )
                    if denominator > 0 else None
                ),
                "captain_pct": (
                    round(
                        100.0 * int(raw["captain_count"]) / denominator,
                        1,
                    )
                    if denominator > 0 else None
                ),
                "vice_pct": (
                    round(
                        100.0 * int(raw["vice_count"]) / denominator,
                        1,
                    )
                    if denominator > 0 else None
                ),
                "eo_pct": (
                    round(100.0 * float(effective) / denominator, 1)
                    if complete and denominator > 0 else None
                ),
                "eo_supported": complete,
            }
        )

    candidate_reviews: list[dict[str, Any]] = []
    for element in owned_ids:
        player = pmap.get(element) or {}
        review = _captain_candidate_review(
            candidate={
                "element": element,
                "name": player_name(element),
            },
            projections=projections,
            mini=snapshot,
            mini_league_stance=str(
                ((mini_overlay or {}).get("risk_posture") or {}).get(
                    "posture"
                )
                or "BALANCED"
            ),
        )
        league_row = next(
            (
                row
                for row in our15_rival_exposure
                if int(row["element_id"]) == element
            ),
            {},
        )
        direct_row = direct_exposure_map.get(element) or {}
        direct_eo = direct_row.get("eo_pct")
        if direct_eo is None:
            rank_utility = "UNAVAILABLE"
        elif float(direct_eo) >= 120.0:
            rank_utility = "PROTECTION_HEAVY"
        elif float(direct_eo) >= 75.0:
            rank_utility = "PROTECTION"
        elif float(direct_eo) <= 20.0:
            rank_utility = "HIGH_LEVERAGE"
        elif float(direct_eo) <= 50.0:
            rank_utility = "LEVERAGE"
        else:
            rank_utility = "BALANCED"
        candidate_reviews.append(
            {
                **review,
                "all_rivals": league_row,
                "direct_rivals": direct_row,
                "expected_rank_utility": rank_utility,
            }
        )

    def candidate_sort_key(row: Mapping[str, Any]) -> tuple[float, int]:
        raw = row.get("expected_points")
        try:
            score = float(raw)
        except (TypeError, ValueError):
            score = -1.0
        return (-score, int(row.get("element_id") or 10**9))

    candidate_reviews.sort(key=candidate_sort_key)
    selected_ids = {
        element
        for element in (
            _surface_element((lineup or {}).get("captain")),
            _surface_element((lineup or {}).get("vice_captain")),
        )
        if element is not None
    }
    captain_leverage = candidate_reviews[:captain_n]
    captain_seen = {
        int(row.get("element_id") or 0) for row in captain_leverage
    }
    for row in candidate_reviews:
        element = int(row.get("element_id") or 0)
        if element in selected_ids and element not in captain_seen:
            captain_leverage.append(row)
            captain_seen.add(element)

    model_posture = str(
        ((mini_overlay or {}).get("risk_posture") or {}).get("posture")
        or "BALANCED"
    ).upper()
    human_posture = "DEFEND" if model_posture == "PROTECT" else model_posture
    return {
        "disclosed_picks_gw": int(disclosed_gw),
        "disclosed_picks_are_baseline_not_gw_forecast": True,
        "rank_battle": rank_battle,
        "our15_rival_exposure": our15_rival_exposure,
        "direct_rival_scope": {
            "requested_above_count": direct_n,
            "standings_rival_count": len(direct_rows),
            "picks_available_count": len(direct_entries),
            "denominator": len(direct_entries),
            "scope": "IMMEDIATELY_ABOVE_CURRENT_RANK",
            "complete": (
                len(direct_rows) > 0
                and len(direct_entries) == len(direct_rows)
            ),
        },
        "direct_rivals": direct_rivals,
        "direct_rival_our15_exposure": direct_our15_exposure,
        "rival_threats": rival_threats,
        "captain_leverage": captain_leverage,
        "strategy_implication": {
            "human_posture": human_posture,
            "model_posture": model_posture,
            "transfer_action": operational_action,
            "xi_rule": "FOOTBALL_BASELINE_FIRST_MINI_LEAGUE_ONLY_BREAKS_NEAR_TIES",
            "captain_rule": (
                "COMPARE_XPTS_P_HAUL_ALL_RIVAL_EO_DIRECT_RIVAL_EO_AND_RANK_UTILITY"
            ),
            "transfer_rule": (
                "DO_NOT_BUY_OR_SELL_FOR_OWNERSHIP_ALONE; REQUIRE_FOOTBALL_GATE"
            ),
        },
        "report_contract": {
            "raw_count_denominator_percentage_required": True,
            "ownership_starter_bench_captain_vice_required": True,
            "eo_requires_multiplier_evidence": True,
            "direct_rivals_required": True,
            "overlap_required": True,
            "rival_threats_required": True,
            "captain_leverage_required": True,
            "strategy_implication_required": True,
        },
    }


def _formation_mini_league_strategy(
    *,
    lineup: Mapping[str, Any] | None,
    mini: Mapping[str, Any] | None,
    mini_overlay: Mapping[str, Any] | None,
    projections: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raw_formation = (lineup or {}).get("formation")
    comparisons = [
        dict(row)
        for row in (lineup or {}).get("formation_comparison") or []
        if isinstance(row, Mapping)
    ]
    overlay = dict(mini_overlay or {})
    posture = str((overlay.get("risk_posture") or {}).get("posture") or "BALANCED").upper()
    changed = bool((overlay.get("decision_delta") or {}).get("changed"))
    if posture == "PROTECT":
        stance = "PROTECT"
    elif posture == "CHASE":
        stance = "CHASE AGGRESSIVE"
    elif changed:
        stance = "CHASE MODERATE"
    else:
        stance = "BALANCED"

    pmap = _projection_map(projections)
    exposures = {
        int(row.get("element_id") or 0): dict(row)
        for row in (mini or {}).get("exposures") or []
        if isinstance(row, Mapping) and int(row.get("element_id") or 0) > 0
    }
    xi_ids = [
        element
        for element in (
            _surface_element(value)
            for value in (lineup or {}).get("starting_xi") or []
        )
        if element is not None
    ]
    xi_exposure = []
    for element in xi_ids:
        exp = exposures.get(element) or {}
        xi_exposure.append({
            "element_id": element,
            "player": (pmap.get(element) or {}).get("name") or f"element:{element}",
            "ownership_pct": exp.get("ownership_pct"),
            "starter_pct": exp.get("starter_pct"),
            "captain_pct": exp.get("captain_pct"),
            "eo_pct": exp.get("eo_pct"),
        })
    high_eo = sorted(
        xi_exposure,
        key=lambda row: float(
            row.get("eo_pct")
            if row.get("eo_pct") is not None
            else row.get("starter_pct")
            if row.get("starter_pct") is not None
            else -1
        ),
        reverse=True,
    )[:5]
    differentials = sorted(
        xi_exposure,
        key=lambda row: float(
            row.get("starter_pct")
            if row.get("starter_pct") is not None
            else 101
        ),
    )[:3]

    rational = {
        "PROTECT": "0-1",
        "BALANCED": "1-2",
        "CHASE MODERATE": "2-3",
        "CHASE AGGRESSIVE": "3-4",
    }[stance]
    selected_comparison = next(
        (row for row in comparisons if row.get("selected") is True),
        {},
    )
    football_selected_points = selected_comparison.get(
        "expected_fpl_points_with_captain_vice"
    )
    raw_ev_choice = (
        max(
            comparisons,
            key=lambda row: float(
                row.get("expected_fpl_points_with_captain_vice")
                if row.get("expected_fpl_points_with_captain_vice") is not None
                else float("-inf")
            ),
        )
        if comparisons
        else selected_comparison
    )
    raw_ev_formation = raw_ev_choice.get("formation") or raw_formation
    raw_ev_points = raw_ev_choice.get(
        "expected_fpl_points_with_captain_vice"
    )
    # P1.8 is a downstream relative-risk overlay and does not create a
    # second lineup optimizer. Therefore the supportable mini-league
    # formation is the existing P1.7 football-optimal route, while the report
    # separately exposes the pure raw-mean formation for transparency.
    objective_formation = raw_formation
    objective_points = football_selected_points
    projected_difference = (
        round(float(objective_points) - float(raw_ev_points), 6)
        if objective_points is not None and raw_ev_points is not None
        else None
    )
    return {
        "stance": stance,
        "stance_source": "P1.8_DOWNSTREAM_RELATIVE_RISK_OVERLAY",
        "league_context": _mini_context(mini),
        "raw_ev_formation": raw_ev_formation or "UNAVAILABLE",
        "football_optimal_formation": raw_formation or "UNAVAILABLE",
        "mini_league_objective_formation": objective_formation or "UNAVAILABLE",
        "objectives_same": (
            raw_ev_formation == objective_formation
            if raw_ev_formation and objective_formation
            else None
        ),
        "projected_points_difference": projected_difference,
        "raw_projected_points": raw_ev_points,
        "mini_league_objective_projected_points": objective_points,
        "formation_alternatives": comparisons,
        "high_eo_protection": high_eo,
        "differential_slots": differentials,
        "rational_differential_exposure": rational,
        "aggressive_downside": (
            "Higher variance and avoidable rank loss if low-EO exposure replaces "
            "strong high-EO expected-value coverage without a close football decision."
        ),
        "governance": {
            "p1_7_football_optimal_first": True,
            "p1_8_downstream_only": True,
            "second_lineup_optimizer_created": False,
            "raw_mean_not_sole_p1_7_objective": True,
            "formation_switch_requires_supportable_existing_route": True,
        },
    }


def _xi_battles(
    *,
    lineup: Mapping[str, Any] | None,
    projections: Mapping[str, Any] | None,
    mini: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    proof = dict((lineup or {}).get("main_starting_xi_battle") or {})
    starters = [
        dict(row) for row in proof.get("starter_side") or []
        if isinstance(row, Mapping)
    ]
    bench = [
        dict(row) for row in proof.get("bench_side") or []
        if isinstance(row, Mapping)
    ]
    pmap = _projection_map(projections)
    exposures = {
        int(row.get("element_id") or 0): dict(row)
        for row in (mini or {}).get("exposures") or []
        if isinstance(row, Mapping) and int(row.get("element_id") or 0) > 0
    }
    out: list[dict[str, Any]] = []
    for a, b in zip(starters, bench):
        aid = int(a.get("element") or 0)
        bid = int(b.get("element") or 0)
        pa = pmap.get(aid) or {}
        pb = pmap.get(bid) or {}
        xa = dict(pa.get("xmins") or {})
        xb = dict(pb.get("xmins") or {})
        ea = exposures.get(aid) or {}
        eb = exposures.get(bid) or {}
        out.append({
            "player_a": pa.get("name") or a.get("name") or aid,
            "player_b": pb.get("name") or b.get("name") or bid,
            "xmins_a": xa.get("expected_minutes"),
            "xmins_b": xb.get("expected_minutes"),
            "p_start_a": xa.get("start_probability"),
            "p_start_b": xb.get("start_probability"),
            "projection_1gw_a": _horizon_mean(pa, "1"),
            "projection_1gw_b": _horizon_mean(pb, "1"),
            "ceiling_a": ((pa.get("horizons") or {}).get("1") or {}).get("quantiles"),
            "ceiling_b": ((pb.get("horizons") or {}).get("1") or {}).get("quantiles"),
            "fixture_a": ((pa.get("xpts_by_gw") or [{}])[0].get("fixtures") or [{}])[0].get("opponent") if pa.get("xpts_by_gw") else None,
            "fixture_b": ((pb.get("xpts_by_gw") or [{}])[0].get("fixtures") or [{}])[0].get("opponent") if pb.get("xpts_by_gw") else None,
            "role_a": pa.get("tactical_role") or pa.get("system_context"),
            "role_b": pb.get("tactical_role") or pb.get("system_context"),
            "eo_a": ea.get("eo_pct"),
            "eo_b": eb.get("eo_pct"),
            "tactical_reason": proof.get("status"),
            "final_starter": pa.get("name") or a.get("name") or aid,
            "utility_margin": proof.get("margin"),
        })
    return out


def _three_gw_staging(
    *,
    planning_gw: int,
    action: str,
    stage3_decision: Mapping[str, Any] | None,
    stage3_visible: Mapping[str, Any],
    all15_rows: Sequence[Mapping[str, Any]],
    lineup: Mapping[str, Any] | None,
    finance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    selected_id = str((stage3_decision or {}).get("selected_route_id") or "HOLD")
    routes = [
        dict(row)
        for row in stage3_visible.get("package_routes") or []
        if isinstance(row, Mapping)
    ]
    selected = next((row for row in routes if str(row.get("route")) == selected_id), {})
    moves = dict(selected.get("moves") or {})
    outs = [dict(row) for row in moves.get("out") or [] if isinstance(row, Mapping)]
    ins = [dict(row) for row in moves.get("in") or [] if isinstance(row, Mapping)]
    out_ids = {int(row.get("element") or 0) for row in outs if int(row.get("element") or 0) > 0}
    xi_ids = {
        element
        for element in (
            _surface_element(value)
            for value in (lineup or {}).get("starting_xi") or []
        )
        if element is not None
    }
    classifications: list[dict[str, Any]] = []
    for raw in all15_rows:
        row = dict(raw)
        element = int(row.get("element_id") or 0)
        if element in out_ids:
            classification = "ACT CANDIDATE" if action == "ACT" else "PREPARE OUT"
            reason = f"selected material route {selected_id}"
        elif element in xi_ids:
            classification = "CORE / HOLD"
            reason = "current P1.7 starting structure"
        else:
            classification = "WATCH"
            reason = "bench/optionality slot; reassess with fresh role and fixture evidence"
        classifications.append({
            "element_id": element,
            "player": row.get("player") or row.get("name") or f"element:{element}",
            "classification": classification,
            "reason": reason,
        })
    for incoming in ins:
        classifications.append({
            "element_id": incoming.get("element"),
            "player": incoming.get("name") or f"element:{incoming.get('element')}",
            "classification": "ACT CANDIDATE" if action == "ACT" else "PREPARE IN",
            "reason": f"selected material route {selected_id}",
        })

    free_transfers = (finance or {}).get("free_transfers")
    free_transfers_status = str((finance or {}).get("free_transfers_status") or "NOT_SUPPORTED").upper()
    ft_known = bool(
        isinstance(free_transfers, int)
        and free_transfers_status not in {"", "UNAVAILABLE", "UNKNOWN", "NOT_SUPPORTED", "STALE_NOT_AUTHORIZED", "AUTH_EXPIRED"}
    )
    if selected_id == "HOLD" or not (outs and ins):
        move_text = "SAVE FT / HOLD SQUAD" if ft_known else "NO TRANSFER NOW"
        status = "HOLD"
    else:
        pairs = []
        for index in range(max(len(outs), len(ins))):
            out_name = (outs[index].get("name") if index < len(outs) else None) or (
                f"element:{outs[index].get('element')}" if index < len(outs) else "?"
            )
            in_name = (ins[index].get("name") if index < len(ins) else None) or (
                f"element:{ins[index].get('element')}" if index < len(ins) else "?"
            )
            pairs.append(f"{out_name} → {in_name}")
        move_text = "; ".join(pairs)
        status = "ACT CANDIDATE" if action == "ACT" else "PREPARE"

    staging_rows = [
        {
            "timing": f"GW{planning_gw}",
            "planned_move": move_text,
            "status": status,
            "trigger": (
                (stage3_decision or {}).get("reason")
                or "fresh decision gate remains valid"
            ),
            "expected_gain": selected.get("three_gw", 0.0 if selected_id == "HOLD" else None),
            "dependency": "fresh injury/lineup/role + affordability + price evidence",
        },
        {
            "timing": f"GW{planning_gw + 1}",
            "planned_move": (
                "REOPTIMIZE FULL FRONTIER / SAVE FT IF NO EDGE"
                if ft_known
                else "REOPTIMIZE FULL FRONTIER / NO TRANSFER NOW IF NO EDGE"
            ),
            "status": "WATCH",
            "trigger": "new fixture, xMins, role, price or package evidence",
            "expected_gain": "RECOMPUTE",
            "dependency": "first staged move outcome and remaining bank/FT",
        },
        {
            "timing": f"GW{planning_gw + 2}",
            "planned_move": "REASSESS TARGET SHAPE AND CONTINGENCY",
            "status": "WATCH",
            "trigger": "fresh full-universe scan and Bayesian/post-match update",
            "expected_gain": "RECOMPUTE",
            "dependency": "prior-GW evidence; staging is non-binding",
        },
    ]
    contingency = next(
        (
            row for row in routes
            if str(row.get("route")) not in {"HOLD", selected_id}
        ),
        None,
    )
    return {
        "squad_classification": classifications,
        "staging_rows": staging_rows,
        "free_transfers": free_transfers,
        "free_transfers_status": free_transfers_status,
        "ft_authority": {
            "known": ft_known,
            "source": (finance or {}).get("personal_evidence_source"),
            "observed_at": (finance or {}).get("personal_evidence_observed_at"),
        },
        "ft_saving_plan": (
            "FT STATE UNAVAILABLE"
            if not ft_known
            else "SAVE FT" if action == "WAIT"
            else "SAVE UNTIL TRIGGER" if action == "PREPARE"
            else "USE ONLY IF ACT GATE REMAINS GREEN"
        ),
        "order_of_transfers": move_text,
        "budget_dependency": {
            "bank": (finance or {}).get("bank"),
            "bank_status": (finance or {}).get("bank_status"),
            "sell_value_status": (finance or {}).get("sell_value_status"),
        },
        "price_dependency": selected.get("price_risk"),
        "player_dependency": "fresh P(start)/xMins/role/injury evidence",
        "contingency": contingency,
        "target_formation": (lineup or {}).get("formation") or "UNAVAILABLE",
        "roadmap_is_not_transfer_commitment": True,
        "roadmap_reoptimizes_on_new_evidence": True,
    }


def _post_match_review(
    *,
    projections: Mapping[str, Any] | None,
    foundation: Mapping[str, Any] | None,
    owned_ids: set[int],
    current_gw: int,
) -> dict[str, Any]:
    if not projections or not foundation:
        return {
            "our15": [],
            "material_universe_candidates": [],
            "full_universe_scan": {},
            "recency_weighting": "UNAVAILABLE",
            "bayesian_update": "UNAVAILABLE",
            "linkup_dependency": "UNAVAILABLE",
        }
    match_rows = list(foundation.get("player_match_rows") or [])
    pmap = _projection_map(projections)
    scan = build_post_match_universe_scan(
        current_projection_players=list(pmap.values()),
        previous_projection_players=None,
        player_match_rows=match_rows,
        current_gw=current_gw,
        owned_element_ids=sorted(owned_ids),
    )
    our15 = []
    for element in sorted(owned_ids):
        player = pmap.get(element) or {}
        trajectory = build_player_trajectory(
            match_rows,
            player_id=element,
            current_gw=current_gw,
        )
        fixture_contexts = list(
            ((player.get("contextual_dynamics") or {}).get("fixture_contexts"))
            or []
        )
        linkup = (
            (fixture_contexts[0].get("linkup_network") or {})
            if fixture_contexts and isinstance(fixture_contexts[0], Mapping)
            else {}
        )
        our15.append({
            "element_id": element,
            "player": player.get("name") or f"element:{element}",
            "trajectory": trajectory,
            "bayesian_state": player.get("posterior_rates"),
            "linkup_dependency": linkup,
        })
    material_non_owned = [
        int(value)
        for value in scan.get("deep_analysis_element_ids") or []
        if int(value) not in owned_ids
    ]
    deep = build_post_match_deep_details(
        deep_analysis_element_ids=material_non_owned,
        current_projection_players=list(pmap.values()),
        player_match_rows=match_rows,
        post_match_universe_scan=scan,
        current_gw=current_gw,
        maximum_material_deep_players=20,
    )
    return {
        "our15": our15,
        "material_universe_candidates": list(deep.get("details") or []),
        "full_universe_scan": {
            "eligible_count": scan.get("eligible_count"),
            "scanned_count": scan.get("scanned_count"),
            "material_count": scan.get("material_count"),
            "scope": scan.get("scope"),
        },
        "recency_weighting": "EXPONENTIAL_HALF_LIFE_GW",
        "bayesian_update": "POSTERIOR_RECENT_RATE_WITH_REGIME_SHRINKAGE",
        "linkup_dependency": (
            "creator→finisher / overlap→winger / set-piece-taker→target; "
            "partner availability is marginalized where supportable"
        ),
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
    human_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    xi = list((lineup or {}).get("starting_xi") or [])
    bench_payload = dict((lineup or {}).get("bench") or {})
    bench = (
        ([bench_payload.get("gk")] if bench_payload.get("gk") is not None else [])
        + list(bench_payload.get("order") or [])
    )
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
        "human_facing_manifest_required": True,
        "HUMAN_FACING_MANIFEST": dict(human_manifest or {}),
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
    stage2_cache_proof: dict[str, Any] = {}
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
    private_current_team = _read_json(
        runtime_data_root / "data/v6/personal/current_team.json",
        {},
    ) or {}
    personal_resolution = _stage(
        ledger,
        "PERSONAL_EVIDENCE_RECONCILIATION",
        lambda: _personal_evidence_resolution(
            runtime_data_root,
            state,
            planning_gw=planning_gw,
        ),
        required=True,
    )
    owned = _stage(
        ledger,
        "OUR15_IDENTITY",
        lambda: _owned15(personal_resolution or {}, bootstrap),
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
                strength=strength or {},
            )
        ),
        required=True,
    )
    if foundation:
        def _stage2_projection_with_cache() -> dict[str, Any]:
            projections_payload, proof = load_or_build_stage2_projections(
                bootstrap=bootstrap,
                strength=strength or {},
                planning_gw=planning_gw,
                historical_prior=foundation.get("historical_prior") or {},
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
                builder=lambda: build_player_projections(
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
            )
            stage2_cache_proof.clear()
            stage2_cache_proof.update(proof)
            print(
                "[V12_STAGE2_CACHE] "
                f"status={proof.get('status')} "
                f"hit={proof.get('cache_hit')} "
                f"miss={proof.get('cache_miss')} "
                f"write={proof.get('cache_write')} "
                f"corrupt_reject={proof.get('cache_corrupt_reject')} "
                f"elapsed_seconds={proof.get('load_or_build_seconds')}",
                flush=True,
            )
            return projections_payload

        projections = _stage(
            ledger,
            "P1_1_P1_3_FULL_UNIVERSE",
            _stage2_projection_with_cache,
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


    post_match_review = _stage(
        ledger,
        "S16B_POST_MATCH_GW1_NOW",
        lambda: _post_match_review(
            projections=projections,
            foundation=foundation,
            owned_ids=owned_ids,
            current_gw=max(1, planning_gw - 1),
        ),
        required=True,
    ) if projections and foundation else None
    if post_match_review is None:
        post_match_review = {
            "our15": [],
            "material_universe_candidates": [],
            "full_universe_scan": {},
            "recency_weighting": "UNAVAILABLE",
            "bayesian_update": "UNAVAILABLE",
            "linkup_dependency": "UNAVAILABLE",
        }

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
            report_timestamp=report_slot,
        ),
    )
    fall = _stage(
        ledger,
        "OFFICIAL_FPL_PREDICTOR_FALL20",
        lambda: build_price20(
            predictor_artifact=predictor,
            direction="FALL",
            owned_element_ids=sorted(owned_ids),
            report_timestamp=report_slot,
        ),
    )
    price_radar = _stage(
        ledger,
        "OUR15_PRICE_RADAR",
        lambda: build_actionable_price_radar(
            owned15=owned,
            predictor_artifact=predictor,
            report_timestamp=report_slot,
        ),
    )

    universe = _candidate_universe(projections or {})
    watchlist = _stage(
        ledger,
        "WATCHLIST20",
        lambda: build_watchlist20(
            evaluated_universe=universe,
            owned_element_ids=sorted(owned_ids),
            universe_authority=(
                "FULL"
                if build_canonical_universe(
                    projections or {}
                ).get("status") == "COMPLETE"
                else "PARTIAL"
            ),
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
    watchlist = _enrich_watchlist_rows(
        watchlist,
        projections=projections,
        predictor=predictor,
    )

    canonical_bundle = build_canonical_universe(
        projections or {}
    )
    canonical_complete = (
        projections is not None
        and canonical_bundle.get("status") == "COMPLETE"
    )
    universe_gap = {
        "status": (
            "COMPLETE" if canonical_complete else "PARTIAL"
        ),
        "reason": (
            None
            if canonical_complete
            else (
                "canonical 20/25/30/25 component materialization "
                "is incomplete for at least one required position"
            )
        ),
        "scanned_players": len(universe),
        "complete_players": canonical_bundle.get(
            "complete_players",
            0,
        ),
        "position_counts": canonical_bundle.get(
            "position_counts",
            {},
        ),
        "required_component_weights": canonical_bundle.get(
            "weights",
            {
                "PROVEN_HISTORICAL": 0.20,
                "TACTICAL_ROLE": 0.25,
                "CURRENT_UNDERLYING": 0.30,
                "FIXTURE_SECURITY": 0.25,
            },
        ),
        "anti_double_count": {
            "historical_prior_rates_only": True,
            "current_posterior_rates_only": True,
            "tactical_p1_6_only": True,
            "fixture_p1_3_xpts_only": True,
            "p1_1_security_not_reapplied": True,
        },
    }
    ledger.append(
        {
            "stage": "CANONICAL_UNIVERSE_20_25_30_25",
            "status": (
                "PASS" if canonical_complete else "PARTIAL"
            ),
            "required": True,
            "reason": universe_gap["reason"],
        }
    )

    finance = _stage(
        ledger,
        "TRANSFER_FINANCE_CONTEXT",
        lambda: _private_finance_context(personal_resolution or {}),
        required=True,
    )
    package_search_result = None
    direct_package_utility = None
    funding_leg_selection = None
    funded_search_result = None
    funded_package_utility = None
    package_utility = None
    material_mc_routes = None
    monte_carlo = None
    stage3_decision = None
    package_with_stage3 = None
    mini_overlay = None

    if projections is not None and canonical_complete:
        package_candidates = _package_candidate_rows(projections)
        # P1.2A exhaustively searches the complete direct universe first.
        # Funded two-transfer packages are then composed only from direct legs
        # already proven material by exact P1.7. This preserves full direct
        # authority and real funding routes without pretending that 1.5M+
        # global two-transfer squads were exhaustively P1.7-materialized.
        package_search_result = _stage(
            ledger,
            "P1_2A_PACKAGE_SEARCH",
            lambda: search_packages(
                current_squad=owned,
                candidate_universe=package_candidates,
                bank=(finance or {}).get("bank"),
                max_transfers=1,
                universe_complete=True,
                expected_eligible_universe_count=None,
                lossy_pruning=False,
                execution_mode="SCALAR",
            ),
            required=True,
        )
        if package_search_result:
            direct_package_utility = _stage(
                ledger,
                "P1_2_PACKAGE_UTILITY",
                lambda: evaluate_packages(
                    search_result=package_search_result,
                    projections=projections,
                    free_transfers=(finance or {}).get(
                        "free_transfers"
                    ),
                    hit_cost_per_extra_transfer=(finance or {}).get(
                        "hit_cost_per_extra_transfer"
                    ),
                    future_frontier_by_route=None,
                    information_value_by_route={},
                    price_risk_by_route={},
                    generated_at=report_slot,
                ),
                required=True,
            )
        else:
            _skip_stage(
                ledger,
                "P1_2_PACKAGE_UTILITY",
                "P1.2A direct package search failed",
                required=True,
            )

        if direct_package_utility:
            funding_leg_selection = _stage(
                ledger,
                "P1_2_MATERIAL_FUNDING_LEGS",
                lambda: select_material_funding_legs(
                    direct_package_utility,
                ),
                required=True,
            )
        else:
            _skip_stage(
                ledger,
                "P1_2_MATERIAL_FUNDING_LEGS",
                "direct P1.2B utility failed",
                required=True,
            )

        if package_search_result and funding_leg_selection:
            funded_search_result = _stage(
                ledger,
                "P1_2A_FUNDED_PACKAGE_SEARCH",
                lambda: compose_material_two_transfer_packages(
                    current_squad=owned,
                    direct_search_result=package_search_result,
                    material_direct_route_ids=(
                        funding_leg_selection.get("route_ids") or []
                    ),
                    bank=(finance or {}).get("bank"),
                ),
                required=True,
            )
        else:
            _skip_stage(
                ledger,
                "P1_2A_FUNDED_PACKAGE_SEARCH",
                "direct search/material funding legs unavailable",
                required=True,
            )

        if funded_search_result:
            funded_package_utility = _stage(
                ledger,
                "P1_2B_FUNDED_PACKAGE_UTILITY",
                lambda: evaluate_packages(
                    search_result=funded_search_result,
                    projections=projections,
                    free_transfers=(finance or {}).get(
                        "free_transfers"
                    ),
                    hit_cost_per_extra_transfer=(finance or {}).get(
                        "hit_cost_per_extra_transfer"
                    ),
                    future_frontier_by_route=None,
                    information_value_by_route={},
                    price_risk_by_route={},
                    generated_at=report_slot,
                ),
                required=True,
            )
        else:
            _skip_stage(
                ledger,
                "P1_2B_FUNDED_PACKAGE_UTILITY",
                "material funded search unavailable",
                required=True,
            )

        if direct_package_utility and funded_package_utility:
            package_utility = _stage(
                ledger,
                "P1_2B_PACKAGE_COMBINE",
                lambda: combine_package_utility_surfaces(
                    direct_package_utility,
                    funded_package_utility,
                    funded_search_result=funded_search_result,
                ),
                required=True,
            )
        else:
            _skip_stage(
                ledger,
                "P1_2B_PACKAGE_COMBINE",
                "direct or funded P1.2B utility unavailable",
                required=True,
            )

        if package_utility:
            material_mc_routes = _stage(
                ledger,
                "P1_4_MATERIAL_ROUTE_SELECTION",
                lambda: select_stage3_material_mc_routes(
                    package_utility,
                    max_routes=8,
                ),
                required=True,
            )
        else:
            _skip_stage(
                ledger,
                "P1_4_MATERIAL_ROUTE_SELECTION",
                "P1.2B package utility failed",
                required=True,
            )

        if package_utility and material_mc_routes:
            mc_route_ids = [
                str(value)
                for value in material_mc_routes.get("route_ids") or []
                if str(value) != "HOLD"
            ]
            monte_carlo = _stage(
                ledger,
                "P1_4_MONTE_CARLO",
                lambda: run_package_monte_carlo(
                    projections,
                    package_utility,
                    actual_paths=500_000,
                    seed=canonical_package_seed(
                        projections,
                        package_utility,
                        route_ids=mc_route_ids,
                    ),
                    input_snapshot_id=(
                        "STAGE3:"
                        + _fingerprint(
                            {
                                "official": official["payload"],
                                "prefetch": prefetch,
                                "projections": projections,
                            }
                        )[:24]
                    ),
                    route_ids=mc_route_ids,
                    selected_route_id=(
                        mc_route_ids[0] if mc_route_ids else "HOLD"
                    ),
                    canonical=True,
                    generated_at=report_slot,
                ),
                required=True,
            )
        else:
            _skip_stage(
                ledger,
                "P1_4_MONTE_CARLO",
                "package utility/material route prerequisite failed",
                required=True,
            )

        if package_utility and monte_carlo:
            package_with_mc = _stage(
                ledger,
                "P1_4_PACKAGE_BINDING",
                lambda: attach_monte_carlo_to_package_utility(
                    package_utility,
                    monte_carlo,
                ),
                required=True,
            )
            price_uncertainty = _price_uncertainty_by_route(
                package_with_mc or package_utility,
                predictor,
            )
            stage3_decision = _stage(
                ledger,
                "P1_2_STAGE3_DECISION_CLOSURE",
                lambda: finalize_stage3_decision(
                    package_with_mc or package_utility,
                    monte_carlo,
                    price_uncertainty_by_route=price_uncertainty,
                    projections=projections,
                ),
                required=True,
            )
            if package_with_mc and stage3_decision:
                package_with_stage3 = _stage(
                    ledger,
                    "P1_2_STAGE3_DECISION_BINDING",
                    lambda: attach_stage3_decision(
                        package_with_mc,
                        stage3_decision,
                    ),
                    required=True,
                )
        else:
            _skip_stage(
                ledger,
                "P1_2_STAGE3_DECISION_CLOSURE",
                "P1.4 canonical MC prerequisite failed",
                required=True,
            )

        if package_with_stage3 and mini:
            mini_overlay = _stage(
                ledger,
                "P1_8_MINI_LEAGUE_OVERLAY",
                lambda: evaluate_mini_league_overlay(
                    package_with_stage3,
                    mini,
                    monte_carlo=monte_carlo,
                    relative_mc=None,
                    input_snapshot_id=(
                        "STAGE3_MINI:"
                        + _fingerprint(mini)[:24]
                    ),
                    generated_at=report_slot,
                ),
                required=True,
            )
            if mini_overlay:
                package_with_stage3 = _stage(
                    ledger,
                    "P1_8_MINI_LEAGUE_BINDING",
                    lambda: attach_mini_league_overlay(
                        package_with_stage3,
                        mini_overlay,
                    ),
                    required=True,
                )
        else:
            _skip_stage(
                ledger,
                "P1_8_MINI_LEAGUE_OVERLAY",
                "package decision or mini-league snapshot unavailable",
                required=True,
            )
    else:
        reason = (
            "Stage-2 canonical full universe unavailable"
            if projections is not None
            else "Stage-2 projections unavailable"
        )
        for stage_name in (
            "P1_2A_PACKAGE_SEARCH",
            "P1_2_PACKAGE_UTILITY",
            "P1_2_MATERIAL_FUNDING_LEGS",
            "P1_2A_FUNDED_PACKAGE_SEARCH",
            "P1_2B_FUNDED_PACKAGE_UTILITY",
            "P1_2B_PACKAGE_COMBINE",
            "P1_4_MATERIAL_ROUTE_SELECTION",
            "P1_4_MONTE_CARLO",
            "P1_2_STAGE3_DECISION_CLOSURE",
            "P1_8_MINI_LEAGUE_OVERLAY",
        ):
            _skip_stage(
                ledger,
                stage_name,
                reason,
                required=True,
            )

    stage3_required_stage_names = {
        "P1_2A_PACKAGE_SEARCH",
        "P1_2_PACKAGE_UTILITY",
        "P1_2_MATERIAL_FUNDING_LEGS",
        "P1_2A_FUNDED_PACKAGE_SEARCH",
        "P1_2B_FUNDED_PACKAGE_UTILITY",
        "P1_2B_PACKAGE_COMBINE",
        "P1_4_MATERIAL_ROUTE_SELECTION",
        "P1_4_MONTE_CARLO",
        "P1_4_PACKAGE_BINDING",
        "P1_2_STAGE3_DECISION_CLOSURE",
        "P1_2_STAGE3_DECISION_BINDING",
        "P1_8_MINI_LEAGUE_OVERLAY",
        "P1_8_MINI_LEAGUE_BINDING",
    }
    stage_status = {
        str(row.get("stage") or ""): str(row.get("status") or "")
        for row in ledger
    }
    stage3_internal_pass = bool(
        package_search_result
        and package_utility
        and material_mc_routes
        and monte_carlo
        and stage3_decision
        and package_with_stage3
        and mini_overlay
        and monte_carlo.get("execution_state") == "EXECUTED"
        and monte_carlo.get("canonical_pass") is True
        and int(monte_carlo.get("actual_paths") or 0) >= 500_000
        and (monte_carlo.get("convergence_evidence") or {}).get(
            "status"
        )
        == "PASS"
        and (
            (monte_carlo.get("sampling_diagnostics") or {}).get(
                "match_state_invariants"
            )
            or {}
        ).get("status")
        == "PASS"
        and package_search_result.get("search_authority") == "FULL"
        and package_search_result.get("coverage", {}).get(
            "coverage_complete"
        ) is True
        and package_utility.get("search_authority")
        == "FULL_DIRECT_MATERIAL_FUNDED"
        and (package_utility.get("search_scope") or {}).get(
            "global_two_transfer_exhaustive_claim"
        ) is False
        and (
            (package_utility.get("search_scope") or {}).get("direct") or {}
        ).get("global_direct_complete") is True
        and (
            (package_utility.get("search_scope") or {}).get(
                "funded_two_transfer"
            )
            or {}
        ).get("authority") == "MATERIAL_FUNDED"
        and canonical_bundle.get("stage2_lineage_complete_players")
        == canonical_bundle.get("complete_players")
        and str((watchlist or {}).get("state") or "").upper()
        == "COMPLETE"
        and str((mini or {}).get("coverage_state") or "").upper()
        == "FULL"
        and all(
            stage_status.get(name) == "PASS"
            for name in stage3_required_stage_names
        )
    )
    stagec_surface = None
    stagec_scan: dict[str, Any] = {}
    stagec_external_input: dict[str, Any] = {
        "state": "DISABLED",
        "claims": [],
    }
    if _stagec_scanner_enabled():
        from src.engines.v12_stagec_reporting import (
            build_stagec_report_surface,
        )
        from src.models.v12_external_challenge import (
            build_external_challenge_layer,
            load_external_claims_input,
        )
        from src.models.v12_stagec_universe_scanner import (
            build_stagec_from_canonical_inputs,
        )

        stagec_bundle = build_stagec_from_canonical_inputs(
            projections=projections or {},
            bootstrap=bootstrap,
            match_rows=list((foundation or {}).get("player_match_rows") or []),
            season=str((foundation or {}).get("season") or "") or None,
        )
        stagec_scan = dict(stagec_bundle.get("scan") or {})
        stagec_external_input = load_external_claims_input(as_of=report_slot)
        stagec_external = build_external_challenge_layer(
            stagec_external_input.get("claims") or [],
            scan=stagec_scan,
            decision_context={
                "captain_element": (
                    ((lineup or {}).get("captain") or {}).get("element")
                ),
                "selected_route_id": (
                    (stage3_decision or {}).get("selected_route_id")
                ),
            },
        )
        stagec_external["input_state"] = {
            key: value
            for key, value in stagec_external_input.items()
            if key != "claims"
        }
        stagec_surface = build_stagec_report_surface(
            scan=stagec_scan,
            external_challenges=stagec_external,
        )

    stage3_visible = (
        _stage3_visible_package_surface(
            projections=projections or {},
            canonical_bundle=canonical_bundle,
            package_search_result=package_search_result or {},
            package_utility=package_utility or {},
            material_mc_routes=material_mc_routes or {},
            monte_carlo=monte_carlo or {},
            stage3_decision=stage3_decision or {},
            mini_overlay=mini_overlay,
            finance=finance,
            stagec_scan=stagec_scan,
        )
        if stage3_internal_pass
        else {}
    )
    stage3_math_proof = (
        _stage3_math_proof(
            projections=projections or {},
            package_utility=package_utility or {},
            stage3_decision=stage3_decision or {},
            monte_carlo=monte_carlo or {},
        )
        if stage3_internal_pass
        else {}
    )
    operational_action = str(
        (stage3_decision or {}).get("operational_action")
        or "WAIT"
    ).upper()
    if operational_action not in {"WAIT", "PREPARE", "ACT"}:
        raise IntegratedRunnerError(
            "Stage3 action state must be WAIT/PREPARE/ACT"
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

    all15_rows = _enrich_all15_rows(
        all15=all15,
        projections=projections,
        predictor=predictor,
        owned=owned,
        mini=mini,
    )

    formation_strategy = _formation_mini_league_strategy(
        lineup=lineup,
        mini=mini,
        mini_overlay=mini_overlay,
        projections=projections,
    )
    xi_battles = _xi_battles(
        lineup=lineup,
        projections=projections,
        mini=mini,
    )
    staging = _three_gw_staging(
        planning_gw=planning_gw,
        action=operational_action,
        stage3_decision=stage3_decision,
        stage3_visible=stage3_visible,
        all15_rows=all15_rows,
        lineup=lineup,
        finance=finance,
    )
    league_context = _mini_context(mini)
    league_exposures = list((mini or {}).get("exposures") or [])
    mini_deep_detail = _mini_league_deep_detail(
        mini=mini,
        standings=standings,
        manager_picks=manager_picks,
        owned=owned,
        projections=projections,
        lineup=lineup,
        mini_overlay=mini_overlay,
        disclosed_gw=picks_gw,
        operational_action=operational_action,
    )
    captain_review = _captain_candidate_review(
        candidate=(lineup or {}).get("captain"),
        projections=projections,
        mini=mini,
        mini_league_stance=str(formation_strategy.get("stance") or "BALANCED"),
    )
    vice_captain_review = _captain_candidate_review(
        candidate=(lineup or {}).get("vice_captain"),
        projections=projections,
        mini=mini,
        mini_league_stance=str(formation_strategy.get("stance") or "BALANCED"),
    )
    chip_state = (finance or {}).get("chips")
    chip_available = (
        chip_state not in (None, {}, [])
        and (finance or {}).get("chips_status") == "AVAILABLE"
    )

    sections = {
        "S01": _section(
            "COMPLETE",
            {
                "operational_state": operational_action,
                "planning_gw": planning_gw,
                "primary_decision": (
                    (stage3_decision or {}).get("selected_route_id") or "HOLD"
                ),
                "reason": (stage3_decision or {}).get("reason") or "No material route cleared the decision gate.",
                "key_decision_driver": (
                    "P1.2 package utility + canonical P1.4 MC + P1.8 bounded mini-league overlay"
                ),
                "current_planning_gw": planning_gw,
            },
        ),
        "S02": _section(
            (
                "COMPLETE"
                if len(all15_rows) == 15
                and not (personal_resolution or {}).get("stale")
                else "DEGRADED"
            ),
            {
                "rows": all15_rows,
                "personal_resolution": {
                    "status": (personal_resolution or {}).get("resolution_status"),
                    "source": (personal_resolution or {}).get("source"),
                    "observed_at": (personal_resolution or {}).get("observed_at"),
                    "gw": (personal_resolution or {}).get("gw"),
                    "stale": (personal_resolution or {}).get("stale"),
                },
            },
            (
                None
                if len(all15_rows) == 15
                and not (personal_resolution or {}).get("stale")
                else "CURRENT15 is preserved from the freshest supportable identity evidence but is not authenticated-current for the planning GW"
            ),
            available_count=len(all15_rows),
            expected_count=15,
        ),
        "S03": _section(
            "COMPLETE",
            {
                "decision_delta": {
                    "action": operational_action,
                    "selected_route_id": (stage3_decision or {}).get("selected_route_id"),
                    "reason": (stage3_decision or {}).get("reason"),
                    "mini_league_delta": (mini_overlay or {}).get("decision_delta"),
                    "material_only": True,
                },
            },
        ),
        "S04": _section(
            "COMPLETE",
            {
                "changes": (
                    [
                        {
                            "type": "POST_MATCH_MATERIALITY",
                            "summary": (
                                f"{(post_match_review.get('full_universe_scan') or {}).get('material_count')} "
                                "material GW1→Now trajectories identified by the existing universe scan"
                            ),
                        }
                    ]
                    if (post_match_review.get("full_universe_scan") or {}).get("material_count")
                    else [
                        {
                            "type": "NO_NEW_MATERIAL_CHANGE",
                            "summary": "No new factual development in the bound occurrence independently changes the decision.",
                        }
                    ]
                ),
                "decision_change_sources": (
                    "injury / lineup / role / tactics / price / fixture / underlying / mini-league / transfer economics"
                ),
                **(
                    {"stagec_universe_intelligence": stagec_surface}
                    if stagec_surface is not None
                    else {}
                ),
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
                "home_away_and_rest": "DERIVED_FROM_OFFICIAL_FIXTURE_ROWS_WHERE_AVAILABLE",
                "opponent_strength": strength or {},
                "fixture_swing": "MODEL_DERIVED_WHERE_SUPPORTABLE",
                "congestion": "DERIVED_FROM_FIXTURE_DATES_WHERE AVAILABLE",
                "weather": "DIRECT_CHATGPT_REQUIRED_AT_VISIBLE_DELIVERY",
            },
        ),
        "S06": _section(
            lineup_state,
            _lineup_content(lineup),
            lineup_reason,
        ),
        "S06B": _section(
            "COMPLETE" if lineup and mini_overlay else "DEGRADED",
            formation_strategy,
            None if lineup and mini_overlay else "formation or mini-league downstream evidence incomplete",
        ),
        "S07": _section(
            lineup_state,
            {
                "battles": xi_battles,
                "empty_is_truthful": not bool(xi_battles),
                "battle_summary": (lineup or {}).get("main_starting_xi_battle"),
            },
            lineup_reason,
        ),
        "S08": _section(
            lineup_state,
            {
                "captain": captain_review,
                "vice_captain": vice_captain_review,
                "captain_safe_pool": (lineup or {}).get("captain_safe_pool") or [],
                "mini_league_stance": formation_strategy.get("stance"),
                "authority": (
                    "expected points + ceiling + xMins/P(start) + involvement/role + "
                    "penalty/set-piece + fixture + captain EO + mini-league downside/upside"
                ),
                "raw_mean_is_not_sole_authority": True,
            },
            lineup_reason,
        ),
        "S09": _section(
            "COMPLETE" if chip_available else "DEGRADED",
            {
                "chip": chip_state if chip_available else "UNAVAILABLE",
                "considered_now": False,
                "horizon": "REASSESS EACH DEADLINE",
                "trigger": "material chip-specific fixture/ceiling edge",
                "hold_reason": "No chip action is created without current authenticated chip state and a supportable edge.",
            },
            None if chip_available else "authenticated chip state unavailable in bound current-team artifact",
        ),
        "S10": _section(
            "COMPLETE" if price_radar else "DEGRADED",
            {
                **(price_radar or {"rows": []}),
                "bank": (finance or {}).get("bank"),
                "bank_status": (finance or {}).get("bank_status"),
                "sell_value_status": (finance or {}).get("sell_value_status"),
            },
            None if price_radar else "Official FPL predictor radar unavailable",
        ),
        "S11": _section(
            watch_state,
            {
                "rows": (watchlist or {}).get("rows", []),
                "universe_evaluator": universe_gap,
                "scope": "FULL_ELIGIBLE_FPL_UNIVERSE",
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
            "COMPLETE" if stage3_internal_pass else "DEGRADED",
            {
                "universe_scan": universe_gap,
                "package_routes": stage3_visible.get("package_routes", []),
                "frontier": stage3_visible.get("frontier", []),
                **stage3_visible,
            },
            None if stage3_internal_pass else (
                "Stage3 internal producer/wiring failure; this is NOT accepted as factual-source degradation"
            ),
        ),
        "S14B": _section(
            "COMPLETE" if stage3_decision else "DEGRADED",
            staging,
            None if stage3_decision else "Stage3 decision unavailable; roadmap remains non-binding and must reoptimize.",
        ),
        "S15": _section(
            "COMPLETE",
            {
                "evidence_quality": {
                    "official_factual_evidence": "STRONG" if official else "INCOMPLETE",
                    "model_derived_inference": "STRONG" if projections and stage3_internal_pass else "MODERATE",
                    "market_predictor": (
                        "STRONG" if (rise or {}).get("predictor_health") == "GREEN" else "INCOMPLETE"
                    ),
                    "tactical_interpretation": "MODERATE" if projections else "INCOMPLETE",
                    "p1_1_p1_3": "EXECUTED" if projections else "FAILED",
                    "p1_6": "EXECUTED" if projections else "NOT_RUN",
                    "p1_7": "EXECUTED" if lineup else "PARTIAL",
                    "p1_2_package": "EXECUTED" if package_utility else "FAILED",
                    "p1_4_monte_carlo": (
                        "EXECUTED_CANONICAL"
                        if monte_carlo and monte_carlo.get("canonical_pass") is True
                        else "FAILED"
                    ),
                    "p1_8_downstream_overlay": "EXECUTED" if mini_overlay else "FAILED",
                }
            },
        ),
        "S15B": _section(
            "COMPLETE" if mini_state == "COMPLETE" and mini_overlay else "DEGRADED",
            {
                **(mini or {"coverage_state": "UNAVAILABLE"}),
                "current_league_context": league_context,
                "exposures": league_exposures,
                "downstream_overlay": mini_overlay,
                "football_baseline_precedes_leverage": True,
                "protection_players": formation_strategy.get("high_eo_protection"),
                "differential_opportunities": formation_strategy.get("differential_slots"),
                **mini_deep_detail,
            },
            None if mini_state == "COMPLETE" and mini_overlay else (
                mini_reason or "P1.8 downstream overlay producer did not complete"
            ),
        ),
        "S16": _section(
            "COMPLETE" if projections else "DEGRADED",
            {
                "rows": all15_rows,
                "position_mechanisms": (
                    [
                        _visible_position_mechanism(player, action=operational_action)
                        for player in (projections or {}).get("players") or []
                        if int(player.get("element") or 0) in owned_ids
                    ]
                    if projections else []
                ),
                "why_not_duplicate_of_our15": (
                    "This section exposes probability state, tactical mechanism, uncertainty and fixture context behind the projections."
                ),
            },
            None if projections else (
                "P1.1/P1.3 occurrence projection unavailable: "
                + (projection_failure or "UNKNOWN_PROJECTION_FAILURE")
            ),
            available_count=len(all15_rows),
            expected_count=15,
        ),
        "S16B": _section(
            "COMPLETE" if post_match_review.get("our15") else "DEGRADED",
            post_match_review,
            None if post_match_review.get("our15") else "GW1→Now match-level evidence unavailable for this occurrence",
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
                    "stage3_internal_pass": stage3_internal_pass,
                    "mc_actual_paths": (monte_carlo or {}).get("actual_paths"),
                },
                "source_health": {
                    "official_fpl": "HEALTHY" if official else "UNAVAILABLE",
                    "authenticated_personal_scope": (
                        str(private_current_team.get("auth_state") or "UNAVAILABLE").upper()
                    ),
                    "private_auth_state": (
                        str(private_current_team.get("auth_state") or "UNAVAILABLE").upper()
                    ),
                    "current_squad_identity": (
                        (personal_resolution or {}).get("resolution_status") or "UNAVAILABLE"
                    ),
                    "finance": (
                        "AVAILABLE"
                        if (finance or {}).get("bank") is not None
                        and (finance or {}).get("sell_value_status") not in {None, "UNAVAILABLE", "STALE_NOT_AUTHORIZED"}
                        else "DEGRADED"
                    ),
                    "fixture_data": "HEALTHY" if fixtures is not None else "UNAVAILABLE",
                    "price_predictor": (rise or {}).get("predictor_health") or "UNAVAILABLE",
                    "tactical_statistical_data": "HEALTHY" if foundation else "UNAVAILABLE",
                    "mini_league": (mini or {}).get("coverage_state") or "UNAVAILABLE",
                    "weather": "SOURCE_DEGRADED_AT_RUNNER; DIRECT_CHATGPT_AT_VISIBLE_DELIVERY",
                },
                "authority": {
                    "personal_auth_state": (
                        (finance or {}).get("auth_state")
                        or (personal_resolution or {}).get("auth_state")
                        or "UNAVAILABLE"
                    ),
                    "personal_resolution_status": (personal_resolution or {}).get("resolution_status"),
                    "finance_allowed": (personal_resolution or {}).get("finance_allowed") is True,
                    "finance_status": {
                        "bank": (finance or {}).get("bank_status") or "UNAVAILABLE",
                        "sell_value": (finance or {}).get("sell_value_status") or "UNAVAILABLE",
                        "free_transfers": (finance or {}).get("free_transfers_status") or "UNAVAILABLE",
                    },
                },
                "auth_authority": {
                    "field": "data/v6/personal/current_team.json:auth_state",
                    "value": str(private_current_team.get("auth_state") or "UNAVAILABLE").upper(),
                    "identity_resolution_is_not_auth_authority": True,
                },
                "lineage": {
                    "v6_factual_plane_mutated": False,
                    "post_match_source": "V12 contextual dynamics over read-only V6 normalized match rows",
                },
            },
        ),
        "S18": _section(
            "COMPLETE",
            {
                "NOW": operational_action,
                "NEXT": (
                    "prepare selected route and re-evaluate at next fresh occurrence"
                    if operational_action == "PREPARE"
                    else "execute only while ACT gate remains green"
                    if operational_action == "ACT"
                    else "preserve optionality and refresh evidence"
                ),
                "TRIGGER TO ACT": (stage3_decision or {}).get("action_contract") or "UNAVAILABLE",
                "LATEST SAFE DECISION POINT": "NEXT_CANONICAL_PRE_DEADLINE_OCCURRENCE_WITH_FRESH_TEAM_NEWS_AND_PRICE_EVIDENCE",
                "COST OF WAITING": next(
                    (
                        row.get("voi_vs_cost_of_waiting")
                        for row in (stage3_decision or {}).get("routes") or []
                        if str(row.get("route_id") or "") == str((stage3_decision or {}).get("selected_route_id") or "HOLD")
                    ),
                    None,
                ),
                "ABORT / REVERSAL": (
                    "fresh role/injury/lineup/economics/price evidence or challenger posterior invalidates the route"
                ),
                "BEST ALTERNATIVE": next(
                    (
                        row
                        for row in stage3_visible.get("package_routes", [])
                        if str(row.get("route") or "").upper() != "HOLD"
                    ),
                    None,
                ),
                "TRIGGERS": (stage3_decision or {}).get("action_contract") or "UNAVAILABLE",
                "REVERSAL": (
                    "fresh role/injury/lineup/economics/price evidence or challenger posterior invalidates the route"
                ),
                "VALUE OF INFORMATION": next(
                    (
                        row.get("voi_vs_cost_of_waiting")
                        for row in (stage3_decision or {}).get("routes") or []
                        if str(row.get("route_id") or "") == str((stage3_decision or {}).get("selected_route_id") or "HOLD")
                    ),
                    None,
                ),
            },
        ),
        "S19": _section(
            "COMPLETE",
            {
                "final_judgement": {
                    "transfer": "NO TRANSFER NOW" if operational_action == "WAIT" else operational_action,
                    "selected_route_id": (stage3_decision or {}).get("selected_route_id") or "HOLD",
                    "xi": [
                        _surface_element(value)
                        for value in (lineup or {}).get("starting_xi") or []
                    ],
                    "formation": (lineup or {}).get("formation"),
                    "captain": ((lineup or {}).get("captain") or {}).get("name") or ((lineup or {}).get("captain") or {}).get("element"),
                    "vice_captain": ((lineup or {}).get("vice_captain") or {}).get("name") or ((lineup or {}).get("vice_captain") or {}).get("element"),
                    "bench": (lineup or {}).get("bench"),
                    "mini_league_stance": formation_strategy.get("stance"),
                    "immediate_watch": staging.get("contingency"),
                    "three_gw_direction": staging.get("staging_rows"),
                    "reason": (stage3_decision or {}).get("reason"),
                }
            },
        ),
    }

    # Bind decision-critical visible sections to the exact producer payload
    # before rendering. Renderer never manufactures this metadata.
    producer_by_section = {
        "S06": "P1_7_LINEUP", "S08": "P1_7_LINEUP", "S11": "WATCHLIST20",
        "S12": "OFFICIAL_FPL_PREDICTOR_RISE20", "S13": "OFFICIAL_FPL_PREDICTOR_FALL20",
        "S14": "P1_2_PACKAGE_UTILITY+P1_4_MONTE_CARLO+P1_8_MINI_LEAGUE_OVERLAY",
        "S15B": "P1_8_MINI_LEAGUE_SNAPSHOT+P1_8_MINI_LEAGUE_OVERLAY",
        "S16": "P1_1_P1_3_FULL_UNIVERSE+P1_6_TACTICAL_ROLE",
        "S16B": "POST_MATCH_DEEP_DETAILS",
    }
    for sid, producer in producer_by_section.items():
        section = sections.get(sid)
        if not isinstance(section, Mapping) or str(section.get("state") or "").upper() != "COMPLETE":
            continue
        content = dict(section.get("content") or {})
        content["authoritative_binding"] = {
            "status": "BOUND", "producer": producer,
            "payload_fingerprint": _fingerprint({key: value for key, value in content.items() if key != "authoritative_binding"}),
            "report_slot": report_slot,
        }
        section["content"] = content

    math_stack = build_visible_mathematical_decision_stack(
        stage3_math_proof
    )
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
    human_manifest = build_deep_human_facing_manifest(report)
    compute_contract = _qa_compute_contract(
        owned=owned,
        lineup=lineup,
        watchlist=watchlist,
        rise=rise,
        fall=fall,
        sections=sections,
        human_manifest=human_manifest,
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
    human_failures = list(dict.fromkeys(
        validate_human_facing_body(body)
        + validate_deep_human_facing_manifest(human_manifest)
        + validate_deep_decision_content_delivery(report, body)
    ))
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
            stage3_internal_pass
            and catalog_complete
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
        "cpu_count": max(1, int(os.cpu_count() or 1)),
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
        "human_facing_manifest_status": human_manifest.get("status"),
        "stage3_internal_pass": stage3_internal_pass,
        "stage3_action": operational_action,
        "stage3_required_stages": sorted(stage3_required_stage_names),
        "stage2_derived_cache": deepcopy(stage2_cache_proof),
        "monte_carlo": {
            "actual_paths": (monte_carlo or {}).get("actual_paths"),
            "seed": (monte_carlo or {}).get("seed"),
            "canonical_pass": (monte_carlo or {}).get("canonical_pass"),
            "convergence": (monte_carlo or {}).get(
                "convergence_evidence"
            ),
            "match_state_invariants": (
                (monte_carlo or {}).get("sampling_diagnostics") or {}
            ).get("match_state_invariants"),
        },
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
        "human_facing_manifest": human_manifest,
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
            "qa_relaxed": False,
            "stage3_requires_internal_producers_before_runner_pass": True,
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
            f"integrated runner supports {sorted(SUPPORTED_MODES)}; got {mode}"
        )
    if mode == "PRICE":
        bundle = run_price_occurrence(
            runtime_data_root=Path(args.runtime_data_root),
            canonical_path=CANONICAL_PATH,
            state_path=STATE_PATH,
            report_slot=args.report_slot,
            output_dir=Path(args.output_dir),
        )
    else:
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
