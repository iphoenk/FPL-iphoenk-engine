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
import subprocess
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.engines.v12_lineup_optimizer import optimize_lineup
from src.engines.v12_captain_frontier import decide_captain_vice
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
from src.engines.v12_delivery_reliability import (
    CANONICAL_DEEP_SECTIONS,
    assemble_degraded_deep_report,
    canonical_deep_sections,
    wait_for_prefetch_terminal,
    write_serving_artifacts,
)
from src.engines.v12_personal_data_plane import (
    collect_personal_evidence_candidates,
)
from src.engines.v12_final_delivery_barrier import validate_final_delivery_barrier
from src.engines.v12_report_orchestration import (
    build_actionable_price_radar,
    build_calendar_workload_context,
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
from src.engines.v12_s05_binding import build_report_time_s05_inputs
from src.engines.v12_s16b_lifecycle import (
    resolve_s16b_context,
    state_after_occurrence,
)
from src.engines.v12_contextual_dynamics import (
    build_player_trajectory,
    build_post_match_deep_details,
    build_post_match_universe_scan,
)
from src.engines.v12_competitive_window import resolve_competitive_window
from src.engines.v12_material_news import (
    build_official_fpl_material_news,
    build_report_time_material_news,
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


def _iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _section_content_from_report(
    report: Mapping[str, Any] | None,
    section_id: str,
) -> dict[str, Any]:
    for raw in (report or {}).get("sections") or []:
        if (
            isinstance(raw, Mapping)
            and str(raw.get("section_id") or "").upper() == section_id.upper()
        ):
            return dict(raw.get("content") or {})
    return {}


def _section_state_from_report(
    report: Mapping[str, Any] | None,
    section_id: str,
) -> str:
    for raw in (report or {}).get("sections") or []:
        if (
            isinstance(raw, Mapping)
            and str(raw.get("section_id") or "").upper() == section_id.upper()
        ):
            return str(raw.get("state") or "").upper()
    return "UNAVAILABLE"


def _delta_element(value: Any) -> int | None:
    if isinstance(value, Mapping):
        value = value.get("element_id", value.get("element", value.get("id")))
    try:
        element = int(value)
    except (TypeError, ValueError):
        return None
    return element if element > 0 else None


def _mini_delta_state(mini_detail: Mapping[str, Any] | None) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (mini_detail or {}).get("rank_battle") or []
        if isinstance(row, Mapping)
    ]
    our = next((row for row in rows if row.get("is_us") is True), {})
    if not our:
        return {}
    try:
        our_rank = int(our.get("rank"))
    except (TypeError, ValueError):
        our_rank = None
    try:
        our_points = int(our.get("total_points"))
    except (TypeError, ValueError):
        our_points = None

    by_rank = {}
    for row in rows:
        try:
            rank = int(row.get("rank"))
            points = int(row.get("total_points"))
        except (TypeError, ValueError):
            continue
        by_rank[rank] = {"points": points, "manager": row.get("manager")}

    leader = by_rank.get(1) or {}
    top3 = by_rank.get(3) or {}
    top5 = by_rank.get(5) or {}
    above = by_rank.get(our_rank - 1) if our_rank and our_rank > 1 else None
    below = by_rank.get(our_rank + 1) if our_rank else None

    def gap(target: Mapping[str, Any] | None) -> int | None:
        if not target or our_points is None or target.get("points") is None:
            return None
        return int(target["points"]) - our_points

    return {
        "our_rank": our_rank,
        "our_points": our_points,
        "leader_gap": gap(leader),
        "top3_gap": gap(top3),
        "top5_gap": gap(top5),
        "nearest_above": (
            {"manager": above.get("manager"), "gap": gap(above)}
            if above else None
        ),
        "nearest_below": (
            {"manager": below.get("manager"), "gap": gap(below)}
            if below else None
        ),
    }


def _decision_snapshot_from_report(
    report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    s01 = _section_content_from_report(report, "S01")
    s02 = _section_content_from_report(report, "S02")
    s06 = _section_content_from_report(report, "S06")
    s09 = _section_content_from_report(report, "S09")
    s15b = _section_content_from_report(report, "S15B")
    s17 = _section_content_from_report(report, "S17")
    s19 = _section_content_from_report(report, "S19")
    dashboard = dict(s01.get("decision_dashboard") or {})
    judgement = dict(s19.get("final_judgement") or {})
    bench = dict(s06.get("bench") or {})

    xi = [
        element
        for element in (
            _delta_element(value)
            for value in (
                judgement.get("xi")
                or s06.get("starting_xi")
                or []
            )
        )
        if element is not None
    ]
    bench_order = [
        element
        for element in (
            _delta_element(value)
            for value in (
                judgement.get("bench_order")
                or bench.get("order")
                or []
            )
        )
        if element is not None
    ]
    player_state: dict[str, dict[str, Any]] = {}
    for raw in s02.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        element = _delta_element(raw)
        if element is None:
            continue
        player_state[str(element)] = {
            "player": raw.get("player") or raw.get("name") or f"element:{element}",
            "p_start": raw.get("p_start"),
            "xmins": raw.get("xmins"),
            "projection_1gw": raw.get("projection_1gw", raw.get("gw_plus_1")),
            "availability": raw.get("availability", raw.get("p_available")),
            "role": raw.get("tactical_role_label", raw.get("tactical_role")),
            "price_urgency": raw.get("price_relevance"),
        }

    return {
        "operational_transfer_action": (
            judgement.get("transfer_action")
            or dashboard.get("TRANSFER")
            or s01.get("operational_state")
        ),
        "selected_transfer_route": (
            judgement.get("selected_route_id")
            or s01.get("primary_decision")
        ),
        "xi": xi,
        "bench_gk": _delta_element(
            judgement.get("bench_gk", bench.get("gk"))
        ),
        "bench_order": bench_order,
        "formation": judgement.get("formation", s06.get("formation")),
        "captain": _delta_element(
            judgement.get("final_captain", s06.get("captain"))
        ),
        "vice": _delta_element(
            judgement.get("vice", s06.get("vice_captain"))
        ),
        "player_state": player_state,
        "mini_league": _mini_delta_state(s15b),
        "finance_state": (
            (s17.get("source_health") or {}).get("finance")
        ),
        "chip_state": s09.get("chip"),
    }


def _decision_snapshot_from_current(
    *,
    operational_action: str,
    final_judgement: Mapping[str, Any],
    all15_rows: Sequence[Mapping[str, Any]],
    mini_detail: Mapping[str, Any],
    finance_available: bool,
    chip_state: Any,
    chip_available: bool,
) -> dict[str, Any]:
    player_state: dict[str, dict[str, Any]] = {}
    for raw in all15_rows:
        if not isinstance(raw, Mapping):
            continue
        element = _delta_element(raw)
        if element is None:
            continue
        player_state[str(element)] = {
            "player": raw.get("player") or raw.get("name") or f"element:{element}",
            "p_start": raw.get("p_start"),
            "xmins": raw.get("xmins"),
            "projection_1gw": raw.get("projection_1gw", raw.get("gw_plus_1")),
            "availability": raw.get("availability", raw.get("p_available")),
            "role": raw.get("tactical_role_label", raw.get("tactical_role")),
            "price_urgency": raw.get("price_relevance"),
        }
    return {
        "operational_transfer_action": (
            final_judgement.get("transfer_action") or operational_action
        ),
        "selected_transfer_route": final_judgement.get("selected_route_id"),
        "xi": [
            element
            for element in (
                _delta_element(value)
                for value in final_judgement.get("xi") or []
            )
            if element is not None
        ],
        "bench_gk": _delta_element(final_judgement.get("bench_gk")),
        "bench_order": [
            element
            for element in (
                _delta_element(value)
                for value in final_judgement.get("bench_order") or []
            )
            if element is not None
        ],
        "formation": final_judgement.get("formation"),
        "captain": _delta_element(final_judgement.get("final_captain")),
        "vice": _delta_element(final_judgement.get("vice")),
        "player_state": player_state,
        "mini_league": _mini_delta_state(mini_detail),
        "finance_state": "AVAILABLE" if finance_available else "DEGRADED",
        "chip_state": chip_state if chip_available else "UNAVAILABLE",
    }


def _decision_delta_surface(
    *,
    previous_snapshot: Mapping[str, Any],
    current_snapshot: Mapping[str, Any],
    previous_report_slot: str,
    evidence_time: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    def append_change(
        decision_item: str,
        previous: Any,
        current: Any,
        reason: str,
    ) -> None:
        if previous == current:
            return
        rows.append(
            {
                "decision_item": decision_item,
                "previous": previous,
                "current": current,
                "material_change": True,
                "reason": reason,
                "evidence_time": evidence_time,
            }
        )

    for key, label in (
        ("operational_transfer_action", "OPERATIONAL TRANSFER ACTION"),
        ("selected_transfer_route", "SELECTED TRANSFER ROUTE"),
        ("xi", "XI"),
        ("bench_gk", "BENCH GK"),
        ("bench_order", "BENCH ORDER"),
        ("formation", "FORMATION"),
        ("captain", "CAPTAIN"),
        ("vice", "VICE"),
        ("finance_state", "FINANCE STATE"),
        ("chip_state", "CHIP STATE"),
    ):
        append_change(
            label,
            previous_snapshot.get(key),
            current_snapshot.get(key),
            "previous valid visible DEEP versus current occurrence",
        )

    previous_players = dict(previous_snapshot.get("player_state") or {})
    current_players = dict(current_snapshot.get("player_state") or {})
    for element in sorted(set(previous_players) | set(current_players), key=int):
        previous = dict(previous_players.get(element) or {})
        current = dict(current_players.get(element) or {})
        player = current.get("player") or previous.get("player") or f"element:{element}"
        for key, label in (
            ("p_start", "P(start)"),
            ("xmins", "xMins"),
            ("projection_1gw", "1GW xPts"),
            ("availability", "AVAILABILITY"),
            ("role", "ROLE"),
            ("price_urgency", "PRICE URGENCY"),
        ):
            old = previous.get(key)
            new = current.get(key)
            if key in {"p_start", "xmins", "projection_1gw"} and (
                old is None or new is None
            ):
                continue
            append_change(
                f"{label}: {player} [{element}]",
                old,
                new,
                (
                    "occurrence model recomputation delta"
                    if key in {"p_start", "xmins", "projection_1gw"}
                    else "factual/role/price evidence changed"
                ),
            )

    previous_mini = dict(previous_snapshot.get("mini_league") or {})
    current_mini = dict(current_snapshot.get("mini_league") or {})
    for key, label in (
        ("our_rank", "MINI-LEAGUE RANK"),
        ("our_points", "MINI-LEAGUE POINTS"),
        ("leader_gap", "LEADER GAP"),
        ("top3_gap", "TOP3 GAP"),
        ("top5_gap", "TOP5 GAP"),
        ("nearest_above", "NEAREST ABOVE"),
        ("nearest_below", "NEAREST BELOW"),
    ):
        append_change(
            label,
            previous_mini.get(key),
            current_mini.get(key),
            "submitted standings context changed",
        )

    return {
        "baseline_state": "AVAILABLE",
        "baseline_requirement": "PREVIOUS_VALID_VISIBLE_DEEP",
        "previous_report_slot": previous_report_slot,
        "rows": rows,
        "summary": (
            "NO MATERIAL DECISION CHANGE"
            if not rows
            else f"{len(rows)} material decision/evidence changes versus previous valid visible DEEP"
        ),
        "material_only": True,
        "no_recomputation_no_numeric_delta": True,
        "numeric_delta_policy": (
            "P(start)/xMins/1GW deltas are emitted only when both occurrences "
            "contain recomputed values; no value is fabricated for missing evidence."
        ),
    }


def _serving_sections_as_report(
    sections: Mapping[str, Any],
) -> dict[str, Any]:
    """Rehydrate only the existing presentation contract, never model internals."""
    expected_ids = [section_id for section_id, _ in CANONICAL_DEEP_SECTIONS]
    rows: list[dict[str, Any]] = []
    for section_id in expected_ids:
        raw = sections.get(section_id)
        if not isinstance(raw, Mapping):
            continue
        rows.append(
            {
                "section_id": section_id,
                "label": raw.get("label"),
                "state": raw.get("state"),
                "source_state": raw.get("source_state"),
                "degradation_reason": raw.get("degradation_reason"),
                "available_count": raw.get("available_count"),
                "expected_count": raw.get("expected_count"),
                "content": deepcopy(raw.get("content") or {}),
            }
        )
    return {
        "mode": "DEEP",
        "sections": rows,
        "numbered_headings": 19,
        "rendered_blocks_including_suffix_sections": len(rows),
        "rendered_blocks_including_15B": len(rows),
        "exact_canonical_order": [row["section_id"] for row in rows] == expected_ids,
    }


def _sha256_token_valid(value: Any) -> bool:
    token = str(value or "").strip().lower()
    return len(token) == 64 and all(char in "0123456789abcdef" for char in token)


def _validate_compact_previous_deep(
    payload: Mapping[str, Any],
    *,
    current_report_slot: str,
) -> tuple[list[str], dict[str, Any] | None]:
    expected_ids = [
        section_id
        for section_id, _ in canonical_deep_sections(
            s16b_due=payload.get("s16b_due") is True
        )
    ]
    failures: list[str] = []
    if str(payload.get("artifact_kind") or "") != "V12_PREVIOUS_DEEP_BASELINE":
        failures.append("ARTIFACT_KIND_INVALID")
    if str(payload.get("report_mode") or "").upper() != "DEEP":
        failures.append("REPORT_MODE_NOT_DEEP")
    if str(payload.get("delivery_status") or "").upper() != "READY_FULL":
        failures.append("DELIVERY_STATUS_NOT_FULL")
    if str(payload.get("runner_status") or "").upper() != "PASS":
        failures.append("RUNNER_STATUS_NOT_PASS")
    for key in ("pre_render_status", "post_render_status", "human_facing_status"):
        if str(payload.get(key) or "").upper() != "PASS":
            failures.append(f"{key.upper()}_NOT_PASS")
    if payload.get("math_recomputed") is not False:
        failures.append("MATH_RECOMPUTED")
    if list(payload.get("section_ids") or []) != expected_ids:
        failures.append("SECTION_IDS_INVALID")
    sections = payload.get("sections")
    if not isinstance(sections, Mapping) or list(sections) != expected_ids:
        failures.append("SECTIONS_INVALID")
    for key in ("canonical_bundle_sha256", "canonical_body_sha256"):
        if not _sha256_token_valid(payload.get(key)):
            failures.append(f"{key.upper()}_INVALID")

    previous_slot = str(payload.get("report_slot") or "")
    previous_dt = _iso_datetime(previous_slot)
    current_dt = _iso_datetime(current_report_slot)
    if previous_dt is None or current_dt is None or previous_dt >= current_dt:
        failures.append("PREVIOUS_SLOT_NOT_STRICTLY_OLDER")

    report = (
        _serving_sections_as_report(sections)
        if isinstance(sections, Mapping)
        else None
    )
    if isinstance(report, Mapping):
        if len(report.get("sections") or []) != len(expected_ids):
            failures.append("REPORT_REHYDRATION_INCOMPLETE")
        snapshot = _decision_snapshot_from_report(report)
        if not snapshot.get("operational_transfer_action"):
            failures.append("DECISION_SNAPSHOT_OPERATIONAL_STATE_MISSING")
    return list(dict.fromkeys(failures)), report


def _validate_latest_serving_compat(
    serving: Mapping[str, Any],
    digest: Mapping[str, Any],
    *,
    current_report_slot: str,
) -> tuple[list[str], dict[str, Any] | None]:
    """One-generation bridge until the first governed compact LKG is published."""
    expected_ids = [
        section_id
        for section_id, _ in canonical_deep_sections(
            s16b_due=serving.get("s16b_due") is True
        )
    ]
    failures: list[str] = []
    if str(serving.get("report_mode") or "").upper() != "DEEP":
        failures.append("SERVING_REPORT_MODE_NOT_DEEP")
    if str(serving.get("delivery_status") or "").upper() != "READY_FULL":
        failures.append("SERVING_DELIVERY_NOT_FULL")
    if str(digest.get("report_mode") or "").upper() != "DEEP":
        failures.append("DIGEST_REPORT_MODE_NOT_DEEP")
    if str(digest.get("runner_status") or "").upper() != "PASS":
        failures.append("DIGEST_RUNNER_NOT_PASS")
    for key in ("pre_render_status", "post_render_status", "human_facing_status"):
        if str(digest.get(key) or "").upper() != "PASS":
            failures.append(f"DIGEST_{key.upper()}_NOT_PASS")
    if digest.get("math_recomputed") is not False:
        failures.append("DIGEST_MATH_RECOMPUTED")
    for key in ("canonical_bundle_sha256", "canonical_body_sha256"):
        if not _sha256_token_valid(digest.get(key)):
            failures.append(f"DIGEST_{key.upper()}_INVALID")

    previous_slot = str(serving.get("report_slot") or "")
    if previous_slot != str(digest.get("report_slot") or ""):
        failures.append("SERVING_DIGEST_SLOT_MISMATCH")
    previous_dt = _iso_datetime(previous_slot)
    current_dt = _iso_datetime(current_report_slot)
    if previous_dt is None or current_dt is None or previous_dt >= current_dt:
        failures.append("PREVIOUS_SLOT_NOT_STRICTLY_OLDER")

    sections = serving.get("sections")
    if not isinstance(sections, Mapping) or list(sections) != expected_ids:
        failures.append("SERVING_SECTIONS_INVALID")
    report = (
        _serving_sections_as_report(sections)
        if isinstance(sections, Mapping)
        else None
    )
    if isinstance(report, Mapping):
        snapshot = _decision_snapshot_from_report(report)
        if not snapshot.get("operational_transfer_action"):
            failures.append("DECISION_SNAPSHOT_OPERATIONAL_STATE_MISSING")
    return list(dict.fromkeys(failures)), report


def _load_previous_visible_deep_baseline(
    directory: Path | None,
    *,
    current_report_slot: str,
) -> dict[str, Any]:
    if directory is None:
        return {
            "state": "UNAVAILABLE",
            "reason": "PREVIOUS_DEEP_ARTIFACT_NOT_BOUND",
        }

    compact_path = directory / "previous_deep_baseline.json"
    if compact_path.exists():
        payload = _read_json(compact_path, {}) or {}
        failures, report = _validate_compact_previous_deep(
            payload,
            current_report_slot=current_report_slot,
        )
        previous_slot = str(payload.get("report_slot") or "")
        if not failures and isinstance(report, Mapping):
            return {
                "state": "AVAILABLE",
                "reason": None,
                "report_slot": previous_slot,
                "occurrence_id": payload.get("occurrence_id"),
                "source": "COMPACT_PREVIOUS_DEEP_LKG_CANONICAL_PROJECTION",
                "report": dict(report),
                "canonical_bundle_sha256": payload.get(
                    "canonical_bundle_sha256"
                ),
                "canonical_body_sha256": payload.get(
                    "canonical_body_sha256"
                ),
                "validation_failures": [],
                "math_recomputed": False,
                "s16b_delivery_state": deepcopy(
                    payload.get("s16b_delivery_state") or {}
                ),
            }
        return {
            "state": "UNAVAILABLE",
            "reason": "COMPACT_PREVIOUS_DEEP_VALIDATION_FAILED",
            "candidate_report_slot": previous_slot or None,
            "validation_failures": failures,
        }

    serving_path = directory / "serving_report.json"
    digest_path = directory / "deep.json"
    if serving_path.exists() and digest_path.exists():
        serving = _read_json(serving_path, {}) or {}
        digest = _read_json(digest_path, {}) or {}
        failures, report = _validate_latest_serving_compat(
            serving,
            digest,
            current_report_slot=current_report_slot,
        )
        previous_slot = str(serving.get("report_slot") or "")
        if not failures and isinstance(report, Mapping):
            return {
                "state": "AVAILABLE",
                "reason": None,
                "report_slot": previous_slot,
                "occurrence_id": serving.get("occurrence_id"),
                "source": "LATEST_SERVING_COMPAT_CANONICAL_COPY",
                "report": dict(report),
                "canonical_bundle_sha256": digest.get(
                    "canonical_bundle_sha256"
                ),
                "canonical_body_sha256": digest.get(
                    "canonical_body_sha256"
                ),
                "validation_failures": [],
                "math_recomputed": False,
                "s16b_delivery_state": deepcopy(
                    serving.get("s16b_delivery_state") or {}
                ),
            }
        return {
            "state": "UNAVAILABLE",
            "reason": "LATEST_SERVING_COMPAT_VALIDATION_FAILED",
            "candidate_report_slot": previous_slot or None,
            "validation_failures": failures,
        }

    # Transitional branch-acceptance compatibility only. Production workflow
    # no longer checks out or scans private reports/** history.
    bundle_path = directory / "report_bundle.json"
    if not bundle_path.exists():
        return {
            "state": "UNAVAILABLE",
            "reason": "PREVIOUS_DEEP_BASELINE_MISSING",
        }
    bundle = _read_json(bundle_path, {}) or {}
    if not isinstance(bundle, Mapping):
        return {
            "state": "UNAVAILABLE",
            "reason": "PREVIOUS_DEEP_BUNDLE_INVALID",
        }
    report = bundle.get("report")
    body = (
        (directory / "report_body.md").read_text(encoding="utf-8")
        if (directory / "report_body.md").exists()
        else bundle.get("visible_body")
    )
    previous_slot = str(bundle.get("report_slot") or "")
    previous_dt = _iso_datetime(previous_slot)
    current_dt = _iso_datetime(current_report_slot)
    status_failures: list[str] = []
    if str(bundle.get("report_mode") or "").upper() != "DEEP":
        status_failures.append("REPORT_MODE_NOT_DEEP")
    if str(bundle.get("runner_status") or "").upper() != "PASS":
        status_failures.append("RUNNER_STATUS_NOT_PASS")
    if str((bundle.get("pre_render_qa") or {}).get("status") or "").upper() != "PASS":
        status_failures.append("PRE_RENDER_NOT_PASS")
    if str((bundle.get("post_render_qa") or {}).get("status") or "").upper() != "PASS":
        status_failures.append("POST_RENDER_NOT_PASS")
    if str((bundle.get("human_facing_qa") or {}).get("status") or "").upper() != "PASS":
        status_failures.append("HUMAN_FACING_NOT_PASS")
    if not isinstance(report, Mapping) or not isinstance(body, str) or not body.strip():
        status_failures.append("REPORT_OR_VISIBLE_BODY_MISSING")
    if previous_dt is None or current_dt is None or previous_dt >= current_dt:
        status_failures.append("PREVIOUS_SLOT_NOT_STRICTLY_OLDER")

    semantic_failures: list[str] = []
    if not status_failures:
        manifest = build_deep_human_facing_manifest(report)
        semantic_failures.extend(validate_deep_human_facing_manifest(manifest))
        semantic_failures.extend(validate_human_facing_body(body))
        final_barrier = validate_final_delivery_barrier(
            report_mode="DEEP",
            report=report,
            body=body,
        )
        semantic_failures.extend(final_barrier.get("failures") or [])
    failures = list(dict.fromkeys(status_failures + semantic_failures))
    if failures:
        return {
            "state": "UNAVAILABLE",
            "reason": "PREVIOUS_DEEP_CURRENT_VALIDATION_FAILED",
            "candidate_report_slot": previous_slot or None,
            "validation_failures": failures,
        }
    return {
        "state": "AVAILABLE",
        "reason": None,
        "report_slot": previous_slot,
        "source": "PREVIOUS_SUCCESSFUL_DEEP_ARTIFACT_REVALIDATED_CURRENT",
        "report": dict(report),
        "validation_failures": [],
    }


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


def _refresh_runtime_data_checkout(runtime_root: Path) -> None:
    """Refresh the local runtime-data-v6 checkout without creating authority."""
    git_marker = runtime_root / ".git"
    if not git_marker.exists():
        return
    subprocess.run(
        ["git", "-C", str(runtime_root), "fetch", "--quiet", "origin", "runtime-data-v6"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "-C", str(runtime_root), "reset", "--hard", "origin/runtime-data-v6"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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


def _bound_set_piece_notes(
    runtime_root: Path,
    *,
    prefetch: Mapping[str, Any],
    report_slot: str,
) -> dict[str, Any]:
    artifact = _read_json(
        runtime_root / "data/v6/report_prefetch/set_piece_notes.json",
        {},
    ) or {}
    if not artifact:
        return {
            "status": "UNAVAILABLE",
            "reason": "SET_PIECE_NOTES_ARTIFACT_MISSING",
            "payload": None,
        }

    expected_slot = _parse_aware(report_slot)
    artifact_slot = _parse_aware(artifact.get("target_logical_report_slot"))
    expected_request = str(
        prefetch.get("report_prefetch_run_id")
        or prefetch.get("request_id")
        or ""
    ).strip()
    actual_request = str(artifact.get("report_prefetch_run_id") or "").strip()
    checks = {
        "report_kind": str(artifact.get("report_kind") or "") == "full_master",
        "logical_slot": bool(
            expected_slot is not None
            and artifact_slot is not None
            and artifact_slot.astimezone(expected_slot.tzinfo) == expected_slot
        ),
        "report_prefetch_run_id": bool(
            expected_request and actual_request == expected_request
        ),
        "authority": artifact.get("authority") == "OFFICIAL_FPL",
        "semantic_class": artifact.get("semantic_class") == "FACT",
        "status": artifact.get("status") == "AVAILABLE",
        "payload": isinstance(artifact.get("payload"), Mapping),
    }
    failed = [key for key, value in checks.items() if not value]
    if failed:
        return {
            "status": "DEGRADED",
            "reason": "SET_PIECE_NOTES_OCCURRENCE_MISMATCH:" + ",".join(failed),
            "payload": None,
            "checks": checks,
        }
    return {
        "status": "AVAILABLE",
        "reason": None,
        "payload": dict(artifact.get("payload") or {}),
        "checks": checks,
        "lineage": artifact.get("lineage"),
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
    private_data_root: Path | None = None,
    allow_legacy_private_sources: bool = True,
    require_private_personal: bool = False,
) -> dict[str, Any]:
    candidates = collect_personal_evidence_candidates(
        runtime_root=runtime_root,
        legacy_state=state,
        planning_gw=planning_gw,
        private_root=private_data_root,
        allow_legacy_private_sources=allow_legacy_private_sources,
        require_private_personal=require_private_personal,
        enforce_public_disclosure=not allow_legacy_private_sources,
    )
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


def _watchlist_candidate_universe(
    projections: Mapping[str, Any],
) -> list[dict[str, Any]]:
    canonical = {
        int(row.get("element_id") or 0): dict(row)
        for row in build_canonical_universe(projections).get("players") or []
        if isinstance(row, Mapping) and int(row.get("element_id") or 0) > 0
    }
    pmap = _projection_map(projections)
    out: list[dict[str, Any]] = []
    for element, row in canonical.items():
        player = pmap.get(element) or {}
        mechanism = _visible_position_mechanism(player, action="WATCH") if player else {}
        positional = dict(mechanism.get("position_mechanism") or {})
        position = str(row.get("position") or "").upper()
        if position == "GK":
            evidence = {
                "save_process": positional.get("saves"),
                "shot_stopping": positional.get("shot_stopping"),
                "clean_sheet_environment": positional.get("clean_sheet"),
                "goals_conceded_environment": positional.get("goals_conceded"),
                "penalty_save_evidence": positional.get("penalty_save"),
                "hierarchy_security": {
                    "p_start": mechanism.get("p_start"),
                    "xmins": mechanism.get("xmins"),
                },
            }
        elif position == "DEF":
            attacking = dict(positional.get("attacking_upside") or {})
            evidence = {
                "goal_process": attacking.get("goal_process"),
                "creation_process": attacking.get("creation_process"),
                "clean_sheet_environment": positional.get("clean_sheet"),
                "defcon": positional.get("defcon"),
                "defensive_role": positional.get("defensive_role"),
                "matchup": mechanism.get("dynamic_matchup"),
            }
        elif position == "MID":
            evidence = {
                "goal_process": positional.get("goal_process"),
                "creation_process": positional.get("creation_process"),
                "penalty_process": positional.get("penalty_process"),
                "set_piece_process": positional.get("set_piece_process"),
                "advanced_role": mechanism.get("role"),
                "matchup": mechanism.get("dynamic_matchup"),
            }
        else:
            evidence = {
                "goal_process": positional.get("goal_process"),
                "creation_process": positional.get("creation_process"),
                "penalty_process": positional.get("penalty_process"),
                "set_piece_process": positional.get("set_piece_process"),
                "service_linkup": positional.get("service_linkup"),
                "matchup": mechanism.get("dynamic_matchup"),
            }
        out.append(
            {
                **row,
                "p_available": mechanism.get("p_available"),
                "p_start": mechanism.get("p_start"),
                "p_dnp": mechanism.get("p_dnp"),
                "xmins": mechanism.get("xmins"),
                "position_specific_evidence": evidence,
            }
        )
    return out


def _bgw_propagation_context(
    calendar_context: Mapping[str, Any] | None,
    *,
    owned_ids: set[int],
    lineup: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Project S05 blank-GW truth into downstream decision surfaces only.

    This is context propagation, not a second fixture/xPts/lineup/transfer model.
    """
    calendar = dict(calendar_context or {})
    flags = dict(calendar.get("period_flags") or {})
    blank_team_ids = sorted(
        {
            int(value)
            for value in flags.get("blank_gw_teams") or []
            if value is not None
        }
    )
    workload = [
        dict(row)
        for row in calendar.get("player_workload") or []
        if isinstance(row, Mapping)
    ]
    blank_owned_ids = sorted(
        {
            int(row.get("element_id"))
            for row in workload
            if row.get("element_id") is not None
            and int(row.get("element_id")) in owned_ids
            and str(row.get("gw_state") or "").upper() == "BLANK"
        }
    )
    final_xi_ids = {
        element
        for element in (
            _surface_element(value)
            for value in (lineup or {}).get("starting_xi") or []
        )
        if element is not None
    }
    return {
        "source_section": "S05",
        "planning_gw": calendar.get("planning_gw"),
        "gw_topology": calendar.get("gw_topology"),
        "active": (
            bool(blank_team_ids)
            or str(calendar.get("gw_topology") or "").upper()
            in {"BLANK_GW", "MIXED_DGW_BGW"}
        ),
        "blank_team_ids": blank_team_ids,
        "blank_owned_element_ids": blank_owned_ids,
        "blank_owned_in_final_xi": sorted(set(blank_owned_ids) & final_xi_ids),
        "decision_math_mutated": False,
        "context_only": True,
    }


def _calendar_relevant_players(
    projections: Mapping[str, Any] | None,
    *,
    planning_gw: int,
    element_ids: set[int],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for player in (projections or {}).get("players") or []:
        if not isinstance(player, Mapping):
            continue
        element = int(player.get("element") or player.get("id") or 0)
        if element <= 0 or element not in element_ids:
            continue
        planning_fixture_evidence: list[dict[str, Any]] = []
        for gw_row in player.get("xpts_by_gw") or []:
            if not isinstance(gw_row, Mapping):
                continue
            try:
                gw = int(gw_row.get("gw") or gw_row.get("event") or -1)
            except (TypeError, ValueError):
                continue
            if gw != int(planning_gw):
                continue
            for fixture in gw_row.get("fixtures") or []:
                if not isinstance(fixture, Mapping):
                    continue
                planning_fixture_evidence.append(
                    {
                        "fixture_id": fixture.get("fixture_id", fixture.get("id")),
                        "xpts": fixture.get("mean", fixture.get("expected_points")),
                        "xmins": fixture.get("xmins", fixture.get("expected_minutes")),
                        "p_start": fixture.get("p_start", fixture.get("start_probability")),
                        "matchup": (
                            fixture.get("dynamic_matchup_vector")
                            or fixture.get("matchup")
                            or fixture.get("opponent")
                        ),
                        "rest_from_previous_fixture_hours": fixture.get(
                            "rest_from_previous_fixture_hours"
                        ),
                    }
                )
        out.append(
            {
                "element_id": element,
                "name": player.get("name"),
                "team_id": int(player.get("team_id") or player.get("team") or 0),
                "planning_fixture_evidence": planning_fixture_evidence,
            }
        )
    return out


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
    bootstrap: Mapping[str, Any],
    mini: Mapping[str, Any] | None = None,
    mini_detail: Mapping[str, Any] | None = None,
    calendar_context: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pmap = _projection_map(projections)
    predictor_map = _price_player_map(predictor)
    owned_map = {
        int(row.get("element_id") or 0): dict(row)
        for row in owned
        if int(row.get("element_id") or 0) > 0
    }
    team_map = {
        int(row.get("id")): {
            "name": row.get("name"),
            "short_name": row.get("short_name"),
        }
        for row in bootstrap.get("teams") or []
        if isinstance(row, Mapping) and row.get("id") is not None
    }
    exposures = {
        int(item.get("element_id") or 0): dict(item)
        for item in (mini or {}).get("exposures") or []
        if isinstance(item, Mapping)
        and int(item.get("element_id") or 0) > 0
    }

    def scope_map(key: str) -> dict[int, dict[str, Any]]:
        return {
            int(item.get("element_id") or 0): dict(item)
            for item in (mini_detail or {}).get(key) or []
            if isinstance(item, Mapping)
            and int(item.get("element_id") or 0) > 0
        }

    league_scope = scope_map("league_our15_exposure")
    rivals_scope = scope_map("rivals_our15_exposure")
    competitive_scope = scope_map("competitive_our15_exposure")
    workload_map = {
        int(item.get("element_id") or 0): dict(item)
        for item in (calendar_context or {}).get("player_workload") or []
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
        status = str(player.get("status") or owned_row.get("status") or "a").lower()
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

        direction = str(
            price.get("direction")
            or price.get("change_direction")
            or ""
        ).upper()
        progress = price.get(
            "projected_percent",
            price.get("current_progress_percent"),
        )
        price_relevance = "NONE_MATERIAL"
        if direction in {"RISE", "FALL"}:
            price_relevance = (
                f"{direction}"
                + (f" {progress}%" if progress is not None else "")
            )

        fixture = _first_projection_fixture(player)
        mechanism = (
            _visible_position_mechanism(
                player,
                action=str(row.get("action") or "HOLD"),
            )
            if player
            else {}
        )
        complete = dict(mechanism.get("complete_player_distribution") or {})
        event_prob = dict(complete.get("event_probabilities") or {})
        point_dist = dict(complete.get("point_distribution") or {})
        quantiles = dict(point_dist.get("quantiles") or {})
        exposure = exposures.get(element) or {}
        team_id = int(
            owned_row.get("team_id")
            or player.get("team_id")
            or 0
        )
        team = team_map.get(team_id) or {}
        opponent_raw = mechanism.get("opponent", row.get("opponent"))
        try:
            opponent_id = int(opponent_raw)
        except (TypeError, ValueError):
            opponent_id = 0
        opponent_team = team_map.get(opponent_id) or {}
        opponent_name = (
            opponent_team.get("name")
            or opponent_team.get("short_name")
            or opponent_raw
            or "UNAVAILABLE"
        )
        role_value = (
            player.get("tactical_role")
            or player.get("system_context")
            or row.get("tactical_role")
        )
        if isinstance(role_value, Mapping):
            role_label = (
                role_value.get("profile")
                or role_value.get("role")
                or role_value.get("label")
                or "AVAILABLE_DETAIL"
            )
        else:
            role_label = role_value

        rate = dict(player.get("rates") or {})
        workload = workload_map.get(element) or {}
        league = league_scope.get(element) or {}
        rivals = rivals_scope.get(element) or {}
        competitive = competitive_scope.get(element) or {}
        row.update({
            "position": owned_row.get("position") or player.get("position"),
            "club": team.get("name") or player.get("team") or f"team:{team_id}",
            "team_id": team_id,
            "opponent": opponent_name,
            "opponent_team_id": opponent_id or opponent_raw,
            "home_away": (
                "H" if mechanism.get("home") is True
                else "A" if mechanism.get("home") is False
                else "UNAVAILABLE"
            ),
            "availability": row.get("p_available", xm.get("availability")),
            "projection_1gw": row.get("gw_plus_1", _horizon_mean(player, "1")),
            "projection_3gw": row.get("three_gw", _horizon_mean(player, "3")),
            "projection_5gw": row.get("five_gw", _horizon_mean(player, "5")),
            "tactical_role_label": role_label,
            "tactical_score": (
                ((player.get("tactical_role_component") or {}).get(
                    "canonical_tactical_role_score"
                ))
                if isinstance(player.get("tactical_role_component"), Mapping)
                else row.get("tactical_role")
            ),
            "probabilities": {
                "p_goal": event_prob.get("p_goal_return"),
                "p_assist": event_prob.get("p_assist_return"),
                "p_return": event_prob.get("p_attacking_return"),
                "p_haul": point_dist.get("p_haul_10_plus"),
                "p_blank": point_dist.get("p_fpl_blank"),
                "Q10": quantiles.get("Q10"),
                "Q50": quantiles.get("Q50"),
                "Q90": quantiles.get("Q90"),
            },
            "bayesian_state": {
                "status": (
                    "POSTERIOR_AVAILABLE"
                    if player.get("posterior_rates")
                    else "UNAVAILABLE"
                ),
                "confidence": player.get("projection_confidence"),
            },
            "main_upside": quantiles.get("Q90"),
            "main_risk": {
                "Q10": quantiles.get("Q10"),
                "warning": ", ".join(warnings) if warnings else "NONE_MATERIAL",
            },
            "underlying": {
                "xg90": rate.get("xg90"),
                "npxg90": rate.get("npxg90"),
                "xa90": rate.get("xa90"),
                "xgi90": (
                    round(float(rate.get("xg90") or 0.0) + float(rate.get("xa90") or 0.0), 4)
                    if rate.get("xg90") is not None and rate.get("xa90") is not None
                    else None
                ),
                "shots": None,
                "shots_in_box": None,
                "shots_on_target": None,
                "big_chances": None,
                "box_touches": None,
                "key_passes": None,
                "chances_created": None,
            },
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
                "tactical_role": role_value,
                "set_piece": mechanism.get("set_piece_process"),
                "penalty": mechanism.get("penalty_process"),
            },
            "fixture_detail": {
                "opponent": opponent_name,
                "opponent_team_id": opponent_id or opponent_raw,
                "home": mechanism.get("home"),
                "dynamic_matchup": mechanism.get("dynamic_matchup"),
            },
            "defensive_contribution": (
                mechanism.get("defcon")
                or mechanism.get("defensive_process")
                or "UNAVAILABLE"
            ),
            "workload_context": {
                "load_state": workload.get("load_state"),
                "days_rest": workload.get("days_rest"),
                "cross_border_travel": workload.get("cross_border_travel"),
                "long_haul": workload.get("long_haul"),
                "timezone_shift_hours": workload.get("timezone_shift_hours"),
                "return_to_club_interval_hours": workload.get(
                    "return_to_club_interval_hours"
                ),
            },
            "injury_rotation_warning": (
                ", ".join(warnings) if warnings else "NONE_MATERIAL"
            ),
            "price_relevance": price_relevance,
            "price_optionality": {
                "current_price": owned_row.get(
                    "current_price",
                    player.get("now_cost"),
                ),
                "purchase_price": owned_row.get("purchase_price"),
                "selling_price": owned_row.get("selling_price"),
                "predictor_direction": direction or "NONE",
                "predictor_progress": progress,
            },
            "current_price": owned_row.get(
                "current_price",
                player.get("now_cost"),
            ),
            "purchase_price": owned_row.get("purchase_price"),
            "selling_price": owned_row.get("selling_price"),
            "ownership_source": (
                "P1_8_SUBMITTED_PICKS_BEHAVIOURAL_BASELINE"
                if mini_detail
                else "OFFICIAL_FPL_PUBLIC_SELECTED_BY_PERCENT"
            ),
            "mini_league_relevance": {
                "league": league,
                "rivals": rivals,
                "competitive": competitive,
                "legacy_rivals": {
                    "ownership_pct": exposure.get("ownership_pct"),
                    "starter_pct": exposure.get("starter_pct"),
                    "captain_pct": exposure.get("captain_pct"),
                    "vice_pct": exposure.get("vice_pct"),
                    "eo_pct": exposure.get("eo_pct"),
                },
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
    result["scanner20"] = deepcopy(enriched)
    enriched_by_id = {
        int(row.get("element_id") or 0): row
        for row in enriched
        if int(row.get("element_id") or 0) > 0
    }
    actionable: list[dict[str, Any]] = []
    for raw in result.get("actionable_watchlist") or []:
        if not isinstance(raw, Mapping):
            continue
        element = int(raw.get("element_id") or 0)
        if element <= 0:
            continue
        merged = {
            **dict(raw),
            **dict(enriched_by_id.get(element) or {}),
        }
        merged["admission_gate"] = deepcopy(raw.get("admission_gate") or {})
        merged["position_specific_evidence"] = deepcopy(
            raw.get("position_specific_evidence") or {}
        )
        merged["action"] = "WATCH"
        merged["watchlist_action"] = "ACTIONABLE_MONITOR"
        actionable.append(merged)
    result["actionable_watchlist"] = actionable
    result["actionable_count"] = len(actionable)
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
    calendar_context: Mapping[str, Any] | None = None,
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
    workload = next(
        (
            dict(row)
            for row in (calendar_context or {}).get("player_workload") or []
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
        "q10": one.get("Q10"),
        "q25": one.get("Q25"),
        "q50": one.get("median"),
        "q75": one.get("Q75"),
        "q90": one.get("Q90"),
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
        "workload_context": {
            "gw_state": workload.get("gw_state"),
            "load_state": workload.get("load_state"),
            "days_rest": workload.get("days_rest"),
            "long_haul": workload.get("long_haul"),
            "timezone_shift_hours": workload.get("timezone_shift_hours"),
            "return_to_club_interval_hours": workload.get(
                "return_to_club_interval_hours"
            ),
            "planning_gw_fixtures": workload.get("planning_gw_fixtures"),
        },
        # Legacy P1.8 snapshot exposure is RIVALS-excluding-us. Stage C deep
        # detail adds LEAGUE/RIVALS/DIRECT named scopes separately.
        "rivals_captain_count": exposure.get("captain_count"),
        "rivals_captain_pct": exposure.get("captain_pct"),
        "rivals_eo_pct": exposure.get("eo_pct"),
        "rivals_eo_supported": exposure.get("eo_supported"),
        # Compatibility aliases only. Their scope is explicit and they are
        # not used by Stage-C human-facing denominator rendering.
        "captain_pct": exposure.get("captain_pct"),
        "eo_pct": exposure.get("eo_pct"),
        "legacy_exposure_scope": "RIVALS_EXCLUDING_US",
        "mini_league_upside": (
            "Lower captain/EO can create leverage only when football evidence remains close."
        ),
        "mini_league_downside": (
            "Fading a strong high-EO captain increases relative-rank downside."
        ),
        "mini_league_stance": mini_league_stance,
        "raw_mean_is_not_sole_authority": True,
        "candidate_source": "AUTHORITATIVE_CURRENT15_FINAL_XI",
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
    calendar_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize decision-oriented mini-league evidence without new football math.

    Counts and denominators stay explicit. Current OUR15 comes from the
    occurrence-bound personal resolution, while rival picks remain the latest
    disclosed Official FPL submission and are labelled with that GW.
    """
    snapshot = dict(mini or {})
    context = _mini_context(snapshot)
    report_cfg = dict(load_mini_league_config().get("report") or {})
    threat_n = max(1, int(report_cfg.get("max_competitive_window_threats", 12) or 12))
    captain_n = max(1, int(report_cfg.get("captain_candidates", 5) or 5))

    pmap = _projection_map(projections)
    canonical_map = {
        int(row.get("element_id") or 0): dict(row)
        for row in build_canonical_universe(projections or {}).get("players") or []
        if isinstance(row, Mapping) and int(row.get("element_id") or 0) > 0
    }
    owned_ids = [
        element
        for element in (_surface_element(row) for row in owned)
        if element is not None
    ]
    owned_ids = list(dict.fromkeys(owned_ids))
    owned_set = set(owned_ids)
    final_xi_ids = [
        element
        for element in (
            _surface_element(value)
            for value in (lineup or {}).get("starting_xi") or []
        )
        if element is not None and element in owned_set
    ]
    final_xi_ids = list(dict.fromkeys(final_xi_ids))
    final_xi_set = set(final_xi_ids)
    bench_payload = dict((lineup or {}).get("bench") or {})
    bench_ids = [
        element
        for element in (
            [_surface_element(bench_payload.get("gk"))]
            + [
                _surface_element(value)
                for value in bench_payload.get("order") or []
            ]
        )
        if element is not None and element in owned_set
    ]
    bench_set = set(bench_ids)

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
                    "active_chip": raw.get("active_chip"),
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
    standing_ids = {
        int(row.get("entry_id") or 0)
        for row in standings_rows
        if int(row.get("entry_id") or 0) > 0
    }
    our_entry_id = int(context.get("our_entry_id") or 0)
    league_entries = [
        entry
        for entry_id, entry in entries.items()
        if entry_id in standing_ids
        and str(entry.get("status") or "").upper() == "AVAILABLE"
    ]
    rival_entries = [
        entry
        for entry in league_entries
        if int(entry.get("entry_id") or 0) != our_entry_id
    ]
    league_unique_ids = sorted({
        element
        for entry in league_entries
        for pick in entry.get("picks") or []
        for element in [pick_element(pick)]
        if element is not None
    })
    league_full_composition = exposure_for_entries(
        league_entries,
        league_unique_ids,
        require_complete_eo=True,
    )
    for row in league_full_composition:
        player = canonical_map.get(int(row.get("element_id") or 0)) or {}
        row["position"] = (
            player.get("position")
            or player.get("position_name")
            or player.get("element_type")
            or "UNAVAILABLE"
        )
        row["our15"] = int(row.get("element_id") or 0) in owned_set
    league_full_composition.sort(
        key=lambda row: (
            str(row.get("position") or ""),
            -int(row.get("ownership_count") or 0),
            -int(row.get("starter_count") or 0),
            int(row.get("element_id") or 0),
        )
    )
    league_our15_exposure = exposure_for_entries(
        league_entries,
        owned_ids,
        require_complete_eo=True,
    )
    rivals_our15_exposure = exposure_for_entries(
        rival_entries,
        owned_ids,
        require_complete_eo=True,
    )
    league_exposure_map = {
        int(row["element_id"]): row
        for row in league_our15_exposure
    }
    rivals_exposure_map = {
        int(row["element_id"]): row
        for row in rivals_our15_exposure
    }
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
        if rank <= min(
            10,
            int(context.get("manager_count") or len(standing_ids)),
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

    league_size = int(context.get("manager_count") or len(standing_ids))
    competitive_window = resolve_competitive_window(our_rank_i, league_size)
    competitive_rank_set = set(competitive_window.get("ranks") or [])
    competitive_rows = [
        row
        for row in ordered
        if int(row.get("league_rank") or 0) in competitive_rank_set
    ]
    competitive_entries: list[dict[str, Any]] = []
    competitive_rivals: list[dict[str, Any]] = []
    for row in competitive_rows:
        entry_id = int(row.get("entry_id") or 0)
        entry = entries.get(entry_id)
        picks = list((entry or {}).get("picks") or [])
        if entry is not None and str(entry.get("status") or "").upper() == "AVAILABLE":
            competitive_entries.append(entry)
        else:
            entry = None
            picks = []
        squad = {
            element
            for element in (pick_element(pick) for pick in picks)
            if element is not None
        }
        rival_xi = {
            element
            for pick in picks
            for element in [pick_element(pick)]
            if element is not None
            and (
                (pick_multiplier(pick) is not None and pick_multiplier(pick) > 0)
                or (
                    pick_multiplier(pick) is None
                    and pick_position(pick) is not None
                    and 1 <= int(pick_position(pick) or 0) <= 11
                )
            )
        }
        rival_bench = squad - rival_xi
        overlap = [element for element in owned_ids if element in squad]
        xi_overlap = [element for element in final_xi_ids if element in rival_xi]
        bench_overlap = [element for element in bench_ids if element in rival_bench]
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
        competitive_rivals.append(
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
                "position_vs_us": (
                    "ABOVE"
                    if our_rank_i is not None and int(row.get("league_rank") or 0) < our_rank_i
                    else "BELOW"
                ),
                "gw_score": row.get("gw_score"),
                "overlap_count": len(overlap),
                "overlap_denominator": len(owned_ids),
                "xi_overlap_count": len(xi_overlap),
                "xi_overlap_denominator": len(final_xi_ids),
                "bench_overlap_count": len(bench_overlap),
                "bench_overlap_denominator": len(bench_ids),
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
                "xi_overlap_players": [
                    {"element_id": element, "player": player_name(element)}
                    for element in xi_overlap
                ],
                "bench_overlap_players": [
                    {"element_id": element, "player": player_name(element)}
                    for element in bench_overlap
                ],
                "shields": [
                    {"element_id": element, "player": player_name(element)}
                    for element in xi_overlap
                ],
                "rival_only_threats": [
                    {"element_id": element, "player": player_name(element)}
                    for element in sorted(rival_xi - owned_set)
                ],
                "differential_against_us": [
                    {"element_id": element, "player": player_name(element)}
                    for element in sorted(final_xi_set - rival_xi)
                ],
                "active_chip": (entry or {}).get("active_chip"),
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

    competitive_our15_exposure = exposure_for_entries(
        competitive_entries,
        owned_ids,
        require_complete_eo=True,
    )
    competitive_exposure_map = {
        int(row["element_id"]): row
        for row in competitive_our15_exposure
    }

    threat_totals: dict[int, dict[str, Any]] = {}
    competitive_denominator = len(competitive_entries)
    scope_multiplier_complete = (
        competitive_denominator > 0
        and all(
            len(entry.get("picks") or []) == 15
            and all(
                pick_multiplier(pick) is not None
                for pick in entry.get("picks") or []
            )
            for entry in competitive_entries
        )
    )
    for entry in competitive_entries:
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

    competitive_window_threats: list[dict[str, Any]] = []
    sorted_threats = sorted(
        threat_totals.values(),
        key=lambda row: (
            -float(row.get("effective_multiplier_sum") or 0.0),
            -int(row.get("ownership_count") or 0),
            int(row.get("element_id") or 0),
        ),
    )[:threat_n]
    for raw in sorted_threats:
        denominator = competitive_denominator
        effective = raw.get("effective_multiplier_sum")
        complete = bool(
            scope_multiplier_complete and raw.get("multiplier_complete")
        )
        competitive_window_threats.append(
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
    for element in final_xi_ids:
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
            calendar_context=calendar_context,
        )
        league_row = league_exposure_map.get(element) or {}
        rivals_row = rivals_exposure_map.get(element) or {}
        competitive_row = competitive_exposure_map.get(element) or {}
        competitive_eo = competitive_row.get("eo_pct")
        if competitive_eo is None:
            leverage_class = "UNAVAILABLE"
        elif float(competitive_eo) >= 120.0:
            leverage_class = "PROTECTION_HEAVY"
        elif float(competitive_eo) >= 75.0:
            leverage_class = "PROTECTION"
        elif float(competitive_eo) <= 20.0:
            leverage_class = "HIGH_LEVERAGE"
        elif float(competitive_eo) <= 50.0:
            leverage_class = "LEVERAGE"
        else:
            leverage_class = "BALANCED"
        candidate_reviews.append(
            {
                **review,
                "league_scope": league_row,
                "rivals_scope": rivals_row,
                "competitive_scope": competitive_row,
                "football_score": (canonical_map.get(element) or {}).get("football_score"),
                "exposure_leverage_class": leverage_class,
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
    for football_rank, row in enumerate(candidate_reviews, start=1):
        row["football_rank"] = football_rank
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
    human_posture = (
        "PROTECT"
        if model_posture == "PROTECT"
        else "CHASE_MODERATE"
        if model_posture == "CHASE"
        else "BALANCED"
    )
    return {
        "disclosed_picks_gw": int(disclosed_gw),
        "disclosed_picks_are_baseline_not_gw_forecast": True,
        "disclosed_picks_label": "BEHAVIOURAL BASELINE",
        "rank_battle": rank_battle,
        "denominator_scopes": {
            "LEAGUE": {
                "label": f"LEAGUE{int(context.get('manager_count') or len(standing_ids))}_INCL_US",
                "expected": int(context.get("manager_count") or len(standing_ids)),
                "collected": len(league_entries),
                "denominator": len(league_entries),
                "includes_us": True,
            },
            "RIVALS": {
                "label": f"RIVALS{max(0, int(context.get('manager_count') or len(standing_ids)) - 1)}_EXCL_US",
                "expected": max(0, int(context.get("manager_count") or len(standing_ids)) - 1),
                "collected": len(rival_entries),
                "denominator": len(rival_entries),
                "includes_us": False,
            },
            "COMPETITIVE": {
                "label": "COMPETITIVE_WINDOW",
                "definition": str(competitive_window.get("window_mode") or "UNAVAILABLE"),
                "expected": int(competitive_window.get("rival_count") or 0),
                "collected": len(competitive_entries),
                "denominator": len(competitive_entries),
                "includes_us": False,
                "coverage_pct": (
                    round(
                        100.0 * len(competitive_entries)
                        / int(competitive_window.get("rival_count") or 0),
                        1,
                    )
                    if int(competitive_window.get("rival_count") or 0) > 0
                    else None
                ),
            },
        },
        "league_full_composition": league_full_composition,
        "league_full_composition_complete": bool(
            league_entries
            and all(len(entry.get("picks") or []) == 15 for entry in league_entries)
        ),
        "league_unique_player_count": len(league_unique_ids),
        "league_our15_exposure": league_our15_exposure,
        "rivals_our15_exposure": rivals_our15_exposure,
        "our15_rival_exposure": rivals_our15_exposure,
        "competitive_window": {
            **competitive_window,
            "standings_rival_count": len(competitive_rows),
            "picks_available_count": len(competitive_entries),
            "denominator": len(competitive_entries),
            "coverage": {
                "collected": len(competitive_entries),
                "expected": int(competitive_window.get("rival_count") or 0),
                "percentage": (
                    round(
                        100.0 * len(competitive_entries)
                        / int(competitive_window.get("rival_count") or 0),
                        1,
                    )
                    if int(competitive_window.get("rival_count") or 0) > 0
                    else None
                ),
            },
            "complete": (
                len(competitive_rows) == int(competitive_window.get("rival_count") or 0)
                and len(competitive_entries) == int(competitive_window.get("rival_count") or 0)
            ),
        },
        "competitive_rivals": competitive_rivals,
        "competitive_our15_exposure": competitive_our15_exposure,
        "competitive_window_threats": competitive_window_threats,
        "captain_leverage": captain_leverage,
        "strategy_implication": {
            "human_posture": human_posture,
            "model_posture": model_posture,
            "transfer_action": operational_action,
            "xi_rule": "FOOTBALL_BASELINE_FIRST_MINI_LEAGUE_ONLY_BREAKS_NEAR_TIES",
            "captain_rule": (
                "FOOTBALL_BASELINE_FIRST; COMPARE_XPTS_P_HAUL_LEAGUE_RIVALS_COMPETITIVE_EO_AND_EXPOSURE_LEVERAGE_CLASS"
            ),
            "transfer_rule": (
                "DO_NOT_BUY_OR_SELL_FOR_OWNERSHIP_ALONE; REQUIRE_FOOTBALL_GATE"
            ),
        },
        "report_contract": {
            "raw_count_denominator_percentage_required": True,
            "ownership_starter_bench_captain_vice_required": True,
            "eo_requires_multiplier_evidence": True,
            "competitive_rivals_required": True,
            "overlap_required": True,
            "competitive_window_threats_required": True,
            "captain_leverage_required": True,
            "three_denominator_scopes_required": True,
            "behavioural_baseline_label_required": True,
            "categorical_rank_utility_forbidden": True,
            "strategy_implication_required": True,
        },
    }



def _captain_decision_surface(
    *,
    owned: Sequence[Mapping[str, Any]],
    lineup: Mapping[str, Any] | None,
    lineup_state: str,
    mini_detail: Mapping[str, Any],
    projections: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One canonical C/VC decision surface.

    P1.7 remains the legal football baseline.  P1.3B one-GW PMFs establish a
    position-neutral football frontier.  P1.8 exposure may resolve only a
    CLOSE frontier; it never promotes a dominated football candidate.
    """
    current15_ids = [
        element
        for element in (_surface_element(row) for row in owned)
        if element is not None
    ]
    current15_ids = list(dict.fromkeys(current15_ids))
    current15_set = set(current15_ids)
    final_xi_ids = [
        element
        for element in (
            _surface_element(row)
            for row in (lineup or {}).get("starting_xi") or []
        )
        if element is not None
    ]
    final_xi_ids = list(dict.fromkeys(final_xi_ids))
    final_xi_set = set(final_xi_ids)
    baseline_captain_id = _surface_element((lineup or {}).get("captain"))
    baseline_vice_id = _surface_element((lineup or {}).get("vice_captain"))

    leverage_rows = [
        dict(row)
        for row in mini_detail.get("captain_leverage") or []
        if isinstance(row, Mapping)
        and int(row.get("element_id") or 0) in final_xi_set
    ]
    leverage_map = {
        int(row.get("element_id") or 0): row
        for row in leverage_rows
        if int(row.get("element_id") or 0) > 0
    }
    pmap = _projection_map(projections)

    decision_candidates: list[dict[str, Any]] = []
    for element in final_xi_ids:
        player = pmap.get(element) or {}
        mechanism = (
            _visible_position_mechanism(player, action="HOLD")
            if player else {}
        )
        complete = dict(mechanism.get("complete_player_distribution") or {})
        horizon = dict((player.get("horizons") or {}).get("1") or {})
        point_distribution = dict(horizon.get("point_distribution") or {})
        if not point_distribution.get("probabilities"):
            point_distribution = dict(complete.get("point_distribution") or {})
        visible = leverage_map.get(element) or {}
        decision_candidates.append(
            {
                **visible,
                "element_id": element,
                "player": (
                    visible.get("player")
                    or player.get("name")
                    or f"element:{element}"
                ),
                "position": player.get("position"),
                "team_id": player.get("team_id"),
                "expected_points": (
                    visible.get("expected_points")
                    if visible.get("expected_points") is not None
                    else horizon.get("mean")
                    if horizon.get("mean") is not None
                    else point_distribution.get("adjusted_expected_total")
                    if point_distribution.get("adjusted_expected_total") is not None
                    else point_distribution.get("expected_points")
                ),
                "p_start": mechanism.get("p_start", visible.get("p_start")),
                "xmins": mechanism.get("xmins", visible.get("xmins")),
                "p_dnp": mechanism.get("p_dnp"),
                "point_distribution": point_distribution,
                "league_scope": dict(visible.get("league_scope") or {}),
                "competitive_scope": dict(
                    visible.get("competitive_scope") or {}
                ),
            }
        )

    scopes = dict(mini_detail.get("denominator_scopes") or {})
    league_scope = dict(scopes.get("LEAGUE") or {})
    competitive_scope = dict(scopes.get("COMPETITIVE") or {})
    league_complete = bool(
        int(league_scope.get("expected") or 0) > 0
        and int(league_scope.get("collected") or 0)
        == int(league_scope.get("expected") or 0)
    )
    competitive_complete = bool(
        (mini_detail.get("competitive_window") or {}).get("complete") is True
        and int(competitive_scope.get("expected") or 0) > 0
        and int(competitive_scope.get("collected") or 0)
        == int(competitive_scope.get("expected") or 0)
    )
    risk_posture = str(
        (mini_detail.get("strategy_implication") or {}).get("model_posture")
        or "BALANCED"
    ).upper()

    decision = decide_captain_vice(
        decision_candidates,
        baseline_captain_id=baseline_captain_id,
        baseline_vice_id=baseline_vice_id,
        risk_posture=risk_posture,
        league_complete=league_complete,
        competitive_complete=competitive_complete,
    )

    profiles = [
        dict(row)
        for row in decision.get("profiles") or []
        if isinstance(row, Mapping)
    ]
    profiles_by_id = {
        int(row.get("element_id") or 0): row
        for row in profiles
        if int(row.get("element_id") or 0) > 0
    }
    mean_rank = {
        int(row.get("element_id") or 0): rank
        for rank, row in enumerate(
            sorted(
                profiles,
                key=lambda item: (
                    -float(item.get("expected_points"))
                    if item.get("expected_points") is not None
                    else float("inf"),
                    int(item.get("element_id") or 10**9),
                ),
            ),
            start=1,
        )
    }

    def decorate(raw: Mapping[str, Any] | None) -> dict[str, Any]:
        row = dict(raw or {})
        element = int(row.get("element_id") or 0)
        merged = {
            **dict(leverage_map.get(element) or {}),
            **row,
        }
        merged["football_rank"] = mean_rank.get(element)
        merged["p_haul"] = merged.get("p_haul", merged.get("p_ge_10"))
        merged["blank_probability"] = merged.get("p_blank")
        merged["haul_probability"] = merged.get("p_haul")
        merged["ceiling_q90"] = merged.get("q90")
        return merged

    decorated_frontier = [
        decorate(row)
        for row in decision.get("frontier") or []
        if isinstance(row, Mapping)
    ]
    decorated_profiles = [decorate(row) for row in profiles]
    captain = decorate(decision.get("captain"))
    vice = decorate(decision.get("vice_captain"))
    football_leader = decorate(decision.get("football_leader"))

    safe_pool_ids = [
        element
        for element in (
            _surface_element(row)
            for row in (lineup or {}).get("captain_safe_pool") or []
        )
        if element is not None and element in final_xi_set
    ]
    safe_pool_ids = list(dict.fromkeys(safe_pool_ids))

    captain_id = _surface_element(captain)
    vice_id = _surface_element(vice)
    legal = bool(
        captain_id is not None
        and vice_id is not None
        and captain_id != vice_id
        and captain_id in current15_set
        and vice_id in current15_set
        and captain_id in final_xi_set
        and vice_id in final_xi_set
    )
    decision_state = (
        "WAIT"
        if not legal or str(lineup_state or "").upper() != "COMPLETE"
        else str(decision.get("decision_state") or "PREPARE").upper()
    )
    if decision_state not in {"WAIT", "PREPARE", "LOCK"}:
        decision_state = "PREPARE"

    classification = str(decision.get("classification") or "FRAGILE").upper()
    mini_override = bool(decision.get("mini_league_override_applied"))
    reconciliation = str(decision.get("reason") or "")
    if mini_override:
        reconciliation += (
            " Competitive Window/league exposure resolved the CLOSE football "
            "frontier under the current risk posture."
        )
    elif classification == "CLOSE":
        reconciliation += (
            " Competitive evidence did not force a switch; no exposure-only "
            "candidate is allowed outside the football frontier."
        )

    return {
        "decision_state": decision_state,
        "captain": captain,
        "vice_captain": vice,
        "football_leader": football_leader,
        "football_frontier_classification": classification,
        "captain_frontier": decorated_frontier,
        "captain_profiles": decorated_profiles,
        "pairwise_captain_comparison": list(decision.get("pairwise") or []),
        "competitive_context": dict(
            decision.get("competitive_context") or {}
        ),
        "risk_posture": risk_posture,
        "vice_fallback_reason": decision.get("vice_reason"),
        # Compatibility-only P1.7 surface retained for existing health consumers.
        # It is no longer interpreted as proof of a football near-tie.
        "captain_safe_pool": safe_pool_ids,
        "captain_safe_pool_semantics": "P1_7_COMPATIBILITY_ONLY_NOT_FRONTIER",
        "candidate_universe_proof": {
            "current15_ids": current15_ids,
            "final_xi_ids": final_xi_ids,
            "captain_id": captain_id,
            "vice_id": vice_id,
            "captain_in_current15": captain_id in current15_set if captain_id is not None else False,
            "vice_in_current15": vice_id in current15_set if vice_id is not None else False,
            "captain_in_final_xi": captain_id in final_xi_set if captain_id is not None else False,
            "vice_in_final_xi": vice_id in final_xi_set if vice_id is not None else False,
            "captain_vice_distinct": captain_id != vice_id if captain_id is not None and vice_id is not None else False,
            "frontier_subset_of_final_xi": all(
                int(row.get("element_id") or 0) in final_xi_set
                for row in decorated_frontier
            ),
        },
        "football_baseline_first": True,
        "mini_league_overlay_second": True,
        "mini_league_override_applied": mini_override,
        "near_tie_authority": {
            "source": "V12_CAPTAIN_FRONTIER_P1_3B_PMF",
            "classification": classification,
            "frontier_candidate_count": len(decorated_frontier),
        },
        "reconciliation_reason": reconciliation,
        "authority": (
            "P1.7 final-XI legality + P1.3B canonical one-GW return distributions "
            "+ P1.8 LEAGUE/COMPETITIVE context; no second football optimizer"
        ),
        "raw_mean_is_not_sole_authority": True,
        "governance": dict(decision.get("governance") or {}),
    }


def _final_judgement_surface(
    *,
    operational_action: str,
    stage3_decision: Mapping[str, Any] | None,
    stage3_visible: Mapping[str, Any],
    lineup: Mapping[str, Any] | None,
    captain_surface: Mapping[str, Any],
    mini_detail: Mapping[str, Any],
    staging: Mapping[str, Any],
    chip_state: Any,
) -> dict[str, Any]:
    selected_route = str(
        (stage3_decision or {}).get("selected_route_id") or "HOLD"
    )
    route = next(
        (
            dict(row)
            for row in stage3_visible.get("package_routes") or []
            if isinstance(row, Mapping)
            and str(row.get("route") or "") == selected_route
        ),
        {},
    )
    bench = dict((lineup or {}).get("bench") or {})
    captain = dict(captain_surface.get("captain") or {})
    football_captain = dict(
        captain_surface.get("football_leader") or captain
    )
    vice = dict(captain_surface.get("vice_captain") or {})
    competitive_context = dict(mini_detail.get("competitive_window") or {})
    return {
        "consumed_sections": ["S08", "S15B"],
        "decision": str(operational_action or "WAIT").upper(),
        "transfer_action": (
            "NO TRANSFER NOW"
            if str(operational_action).upper() == "WAIT"
            else operational_action
        ),
        "selected_route_id": selected_route,
        "selected_route_executable": (
            True
            if selected_route.upper() == "HOLD"
            else route.get("executable")
        ),
        "xi": [
            _surface_element(value)
            for value in (lineup or {}).get("starting_xi") or []
        ],
        "formation": (lineup or {}).get("formation"),
        "bench_gk": _surface_element(bench.get("gk")),
        "bench_order": [
            _surface_element(value)
            for value in bench.get("order") or []
        ],
        "football_optimal_captain": {
            "element_id": football_captain.get("element_id"),
            "player": football_captain.get("player"),
            "football_rank": football_captain.get("football_rank"),
            "xpts": football_captain.get("expected_points"),
            "frontier_classification": captain_surface.get(
                "football_frontier_classification"
            ),
        },
        "mini_league_captain_context": {
            "league_scope": captain.get("league_scope"),
            "rivals_scope": captain.get("rivals_scope"),
            "competitive_scope": captain.get("competitive_scope"),
            "exposure_leverage_class": captain.get(
                "exposure_leverage_class"
            ),
            "competitive_window": competitive_context,
            "behavioural_baseline_gw": mini_detail.get(
                "disclosed_picks_gw"
            ),
            "label": mini_detail.get("disclosed_picks_label"),
        },
        "final_captain": {
            "element_id": captain.get("element_id"),
            "player": captain.get("player"),
        },
        "captain_state": captain_surface.get("decision_state"),
        "vice": {
            "element_id": vice.get("element_id"),
            "player": vice.get("player"),
        },
        "chip": chip_state if chip_state not in (None, {}, []) else "UNAVAILABLE",
        "mini_league_posture": (
            (mini_detail.get("strategy_implication") or {}).get(
                "human_posture"
            )
            or "BALANCED"
        ),
        "immediate_watch": staging.get("contingency"),
        "three_gw_direction": staging.get("staging_rows"),
        "next_trigger": (
            (stage3_decision or {}).get("action_contract")
            or "NEXT_FRESH_DECISION_OCCURRENCE"
        ),
        "reversal_trigger": (
            "fresh role/injury/lineup/economics/price/workload/fixture evidence "
            "invalidates the selected football baseline"
        ),
        "reconciliation_reason": captain_surface.get(
            "reconciliation_reason"
        ),
        "football_baseline_preserved": (
            captain_surface.get("mini_league_override_applied") is False
        ),
    }

def _decision_dashboard(
    *,
    operational_action: str,
    planning_gw: int,
    stage3_decision: Mapping[str, Any] | None,
    lineup_state: str,
    lineup: Mapping[str, Any] | None,
    captain_surface: Mapping[str, Any],
    chip_available: bool,
    price_radar: Mapping[str, Any] | None,
    auth_state: str,
    finance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    battle = dict((lineup or {}).get("main_starting_xi_battle") or {})
    xi_state = (
        "WAIT"
        if str(lineup_state).upper() != "COMPLETE"
        else "PREPARE"
        if battle and str(battle.get("status") or "").upper()
        not in {"", "NONE", "NO_MATERIAL_BATTLE", "CLEAR"}
        else "LOCK"
    )
    captain_state = str(
        captain_surface.get("decision_state") or "WAIT"
    ).upper()
    if captain_state not in {"WAIT", "PREPARE", "LOCK"}:
        captain_state = "WAIT"

    price_rows = [
        dict(row)
        for row in (price_radar or {}).get("rows") or []
        if isinstance(row, Mapping)
    ]
    fresh_rows = [
        row
        for row in price_rows
        if str(row.get("freshness") or "").upper() == "FRESH"
    ]
    explicit_material = any(
        str(row.get("decision_implication") or "").upper() == "MATERIAL"
        for row in fresh_rows
    )
    expected_change = any(
        str(row.get("date_state") or "").upper() == "EXPECTED_CHANGE_DATE"
        for row in fresh_rows
    )
    price_state = (
        "MATERIAL"
        if explicit_material
        else "PREPARE"
        if expected_change
        else "MONITOR"
    )

    auth = str(auth_state or "UNAVAILABLE").upper()
    personal_auth = (
        "AVAILABLE"
        if auth == "AUTH_AVAILABLE"
        else "DEGRADED"
        if auth in {"AUTH_EXPIRED", "EXPIRED", "DEGRADED"}
        else "UNAVAILABLE"
    )
    finance_available = _execution_finance_available(finance)
    blockers: list[str] = []
    if personal_auth != "AVAILABLE":
        blockers.append(f"PERSONAL_AUTH_{personal_auth}")
    if not finance_available:
        blockers.append("EXECUTION_FINANCE_DEGRADED")
    if not chip_available:
        blockers.append("CHIP_AUTHORITY_UNAVAILABLE")
    if captain_state == "PREPARE":
        blockers.append("CAPTAIN_NEAR_TIE_OR_FRESH_EVIDENCE_PENDING")
    if price_rows and not fresh_rows:
        blockers.append("PRICE_PREDICTOR_STALE")

    return {
        "TRANSFER": str(operational_action).upper(),
        "XI": xi_state,
        "CAPTAIN": captain_state,
        "CHIP": "WAIT" if chip_available else "DEGRADED",
        "PRICE": price_state,
        "PERSONAL_AUTH": personal_auth,
        "PLANNING_GW": int(planning_gw),
        "PRIMARY_REASON": (
            (stage3_decision or {}).get("reason")
            or "No material route cleared the current decision gate."
        ),
        "KEY_DRIVER": (
            "P1.2 package utility + canonical P1.4 MC + P1.8 bounded mini-league overlay"
        ),
        "CURRENT_BLOCKERS": blockers,
        "finance_available": finance_available,
        "price_fresh_count": len(fresh_rows),
        "price_row_count": len(price_rows),
    }


def _weather_contract_state_from_calendar(
    calendar_context: Mapping[str, Any] | None,
) -> str:
    return (
        "REPORT_TIME_BOUND"
        if any(
            str(row.get("fpl_impact") or "UNAVAILABLE").upper()
            in {"NORMAL", "LOW", "MATERIAL"}
            for row in (calendar_context or {}).get("weather") or []
            if isinstance(row, Mapping)
        )
        else "SOURCE_DEGRADED"
    )


def _evidence_quality_surface(
    *,
    official: Mapping[str, Any] | None,
    personal_resolution: Mapping[str, Any] | None,
    finance: Mapping[str, Any] | None,
    chip_available: bool,
    calendar_context: Mapping[str, Any] | None,
    projections: Mapping[str, Any] | None,
    post_match_review: Mapping[str, Any] | None,
    rise: Mapping[str, Any] | None,
    mini: Mapping[str, Any] | None,
    private_auth_state: str,
    report_slot: str,
) -> dict[str, Any]:
    price_rows = [
        dict(row)
        for row in (rise or {}).get("rows") or []
        if isinstance(row, Mapping)
    ]
    price_freshness = next(
        (str(row.get("freshness") or "").upper() for row in price_rows),
        "UNAVAILABLE",
    )
    calendar = dict(calendar_context or {})
    coverage = dict(calendar.get("competition_coverage") or {})
    weather_rows = [
        dict(row)
        for row in calendar.get("weather") or []
        if isinstance(row, Mapping)
    ]
    weather_bound = any(
        str(row.get("fpl_impact") or "UNAVAILABLE").upper()
        in {"NORMAL", "LOW", "MATERIAL"}
        for row in weather_rows
    )
    identity_status = str(
        (personal_resolution or {}).get("resolution_status")
        or "UNAVAILABLE"
    ).upper()
    auth = str(private_auth_state or "UNAVAILABLE").upper()
    finance_state = (
        "AVAILABLE" if _execution_finance_available(finance) else "DEGRADED"
    )
    return {
        "Official public FPL": {
            "state": "CURRENT" if official else "UNAVAILABLE",
            "source": "OFFICIAL_FPL_PUBLIC",
        },
        "CURRENT15 identity": {
            "state": identity_status,
            "source": (personal_resolution or {}).get("source"),
            "observed_at": (personal_resolution or {}).get("observed_at"),
        },
        "authenticated personal auth": {
            "state": auth,
            "source": "data/v6/personal/current_team.json:auth_state",
        },
        "authenticated finance": {
            "state": finance_state,
            "bank_status": (finance or {}).get("bank_status"),
            "sell_value_status": (finance or {}).get("sell_value_status"),
            "free_transfers_status": (finance or {}).get("free_transfers_status"),
        },
        "chips": {
            "state": "AVAILABLE" if chip_available else "UNAVAILABLE",
            "source": (finance or {}).get("personal_evidence_source"),
        },
        "fixtures/calendar": {
            "state": str(calendar.get("state") or "UNAVAILABLE"),
            "non_pl_schedule_bound": coverage.get(
                "verified_non_pl_schedule_bound"
            ),
        },
        "workload/travel": {
            "state": (
                "COMPLETE"
                if coverage.get("verified_non_pl_schedule_bound") is True
                and str(coverage.get("player_observation_status") or "").upper()
                == "VALIDATED"
                else "CLUB_SCHEDULE_COMPLETE_PLAYER_OBSERVATIONS_UNAVAILABLE"
                if coverage.get("verified_non_pl_schedule_bound") is True
                else "PL_ONLY_DEGRADED"
            ),
            "club_schedule_status": coverage.get("club_schedule_status"),
            "player_observation_status": coverage.get("player_observation_status"),
            "static_fatigue_penalty": False,
        },
        "tactical": {
            "state": "CURRENT_MODEL_OUTPUT" if projections else "UNAVAILABLE",
        },
        "post-match underlying": {
            "state": (
                "AVAILABLE"
                if (post_match_review or {}).get("our15")
                else "UNAVAILABLE"
            ),
        },
        "price factual": {
            "state": "CURRENT" if official else "UNAVAILABLE",
            "source": "OFFICIAL_FPL_PUBLIC",
        },
        "price predictor freshness": {
            "state": price_freshness,
            "health": (rise or {}).get("predictor_health"),
            "observed_at": (
                price_rows[0].get("evidence_timestamp")
                if price_rows else None
            ),
        },
        "mini-league submitted picks": {
            "state": (mini or {}).get("coverage_state") or "UNAVAILABLE",
            "semantic": "BEHAVIOURAL BASELINE",
        },
        "mini-league standings/live": {
            "state": (mini or {}).get("coverage_state") or "UNAVAILABLE",
        },
        "weather": {
            "state": (
                "REPORT_TIME_BOUND"
                if weather_bound
                else "DEGRADED_OR_OUTSIDE_FORECAST_HORIZON"
            ),
            "mutates_football_model": False,
        },
        "model snapshot": {
            "state": "CURRENT" if projections else "UNAVAILABLE",
            "timestamp": report_slot,
        },
        "data_timestamp": report_slot,
    }


def _action_board_surface(
    *,
    dashboard: Mapping[str, Any],
    stage3_decision: Mapping[str, Any] | None,
    stage3_visible: Mapping[str, Any],
    all15_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected_id = str(
        (stage3_decision or {}).get("selected_route_id") or "HOLD"
    )
    routes = [
        dict(row)
        for row in stage3_visible.get("package_routes") or []
        if isinstance(row, Mapping)
    ]
    alternative = next(
        (
            row for row in routes
            if str(row.get("route") or "").upper() != "HOLD"
        ),
        None,
    )
    injury_watch = [
        {
            "element_id": row.get("element_id"),
            "player": row.get("player") or row.get("name"),
            "warning": row.get("injury_rotation_warning"),
        }
        for row in all15_rows
        if str(row.get("injury_rotation_warning") or "NONE_MATERIAL")
        != "NONE_MATERIAL"
    ]
    rows = [
        {
            "axis": "TRANSFER",
            "NOW": dashboard.get("TRANSFER"),
            "NEXT": "re-evaluate selected route at next fresh occurrence",
            "TRIGGER TO ACT": (
                (stage3_decision or {}).get("action_contract")
                or "CURRENT_TRANSFER_GATE"
            ),
            "LATEST SAFE DECISION POINT": "NEXT_CANONICAL_PRE_DEADLINE_OCCURRENCE",
            "COST OF WAITING": next(
                (
                    row.get("voi_vs_cost_of_waiting")
                    for row in (stage3_decision or {}).get("routes") or []
                    if str(row.get("route_id") or "") == selected_id
                ),
                None,
            ),
            "ABORT / REVERSAL": "fresh role/injury/economics/fixture evidence invalidates route",
        },
        {
            "axis": "XI",
            "NOW": dashboard.get("XI"),
            "NEXT": "refresh availability, workload and final team news",
            "TRIGGER TO ACT": "P1.7 legal XI remains supportable",
            "LATEST SAFE DECISION POINT": "FINAL_PRE_DEADLINE_XI_CHECK",
            "COST OF WAITING": "late lineup information may improve security",
            "ABORT / REVERSAL": "starter probability or role materially changes",
        },
        {
            "axis": "CAPTAIN",
            "NOW": dashboard.get("CAPTAIN"),
            "NEXT": "refresh S08 frontier and Competitive Window exposure",
            "TRIGGER TO ACT": "captain frontier resolves under fresh supportable evidence",
            "LATEST SAFE DECISION POINT": "FINAL_PRE_DEADLINE_CAPTAIN_CHECK",
            "COST OF WAITING": "none unless new team news or role evidence arrives",
            "ABORT / REVERSAL": "captain leaves legal final XI or football baseline changes",
        },
        {
            "axis": "PRICE",
            "NOW": dashboard.get("PRICE"),
            "NEXT": "refresh governed predictor evidence",
            "TRIGGER TO ACT": "price only affects execution timing after football route is supportable",
            "LATEST SAFE DECISION POINT": "BEFORE_SUPPORTABLE_OFFICIAL_PRICE_CYCLE",
            "COST OF WAITING": "possible affordability/optionality change",
            "ABORT / REVERSAL": "stale predictor or football route no longer supportable",
        },
        {
            "axis": "AUTH/FINANCE",
            "NOW": (
                "AVAILABLE"
                if dashboard.get("PERSONAL_AUTH") == "AVAILABLE"
                and dashboard.get("finance_available") is True
                else "DEGRADED"
            ),
            "NEXT": "refresh authenticated current-team evidence",
            "TRIGGER TO ACT": "current bank/sell-value/FT authority available",
            "LATEST SAFE DECISION POINT": "BEFORE_ANY_EXECUTABLE_TRANSFER",
            "COST OF WAITING": "execution economics remain unresolved",
            "ABORT / REVERSAL": "auth expires or finance becomes stale",
        },
        {
            "axis": "INJURY/TEAM NEWS",
            "NOW": "MONITOR" if injury_watch else "CLEAR",
            "NEXT": injury_watch or "refresh official team news",
            "TRIGGER TO ACT": "new availability evidence changes P1.1/P1.7 decision",
            "LATEST SAFE DECISION POINT": "FINAL_PRE_DEADLINE_TEAM_NEWS_CHECK",
            "COST OF WAITING": "uncertainty versus information value",
            "ABORT / REVERSAL": "new official availability evidence supersedes prior state",
        },
    ]
    return {
        "axes": rows,
        "best_alternative": alternative,
        "best_alternative_executable": (
            alternative.get("executable") if alternative else None
        ),
        "finance_unresolved_hides_execution_readiness": True,
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
        stance = "CHASE_MODERATE"
    elif changed:
        stance = "CHASE_MODERATE"
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
    mini_detail: Mapping[str, Any] | None = None,
    calendar_context: Mapping[str, Any] | None = None,
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
    competitive = {
        int(row.get("element_id") or 0): dict(row)
        for row in (mini_detail or {}).get("competitive_our15_exposure") or []
        if isinstance(row, Mapping) and int(row.get("element_id") or 0) > 0
    }
    workload = {
        int(row.get("element_id") or 0): dict(row)
        for row in (calendar_context or {}).get("player_workload") or []
        if isinstance(row, Mapping) and int(row.get("element_id") or 0) > 0
    }

    def onegw(player: Mapping[str, Any]) -> dict[str, Any]:
        mechanism = _visible_position_mechanism(player, action="HOLD") if player else {}
        return dict(mechanism.get("1GW") or {})

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
        da = competitive.get(aid) or {}
        db = competitive.get(bid) or {}
        wa = workload.get(aid) or {}
        wb = workload.get(bid) or {}
        one_a = onegw(pa)
        one_b = onegw(pb)
        out.append({
            "player_a": pa.get("name") or a.get("name") or aid,
            "player_b": pb.get("name") or b.get("name") or bid,
            "xmins_a": xa.get("expected_minutes"),
            "xmins_b": xb.get("expected_minutes"),
            "p_start_a": xa.get("start_probability"),
            "p_start_b": xb.get("start_probability"),
            "projection_1gw_a": _horizon_mean(pa, "1"),
            "projection_1gw_b": _horizon_mean(pb, "1"),
            "p_haul_a": one_a.get("p_haul"),
            "p_haul_b": one_b.get("p_haul"),
            "ceiling_a": one_a.get("Q90"),
            "ceiling_b": one_b.get("Q90"),
            "fixture_a": ((pa.get("xpts_by_gw") or [{}])[0].get("fixtures") or [{}])[0].get("opponent") if pa.get("xpts_by_gw") else None,
            "fixture_b": ((pb.get("xpts_by_gw") or [{}])[0].get("fixtures") or [{}])[0].get("opponent") if pb.get("xpts_by_gw") else None,
            "workload_a": {
                "load_state": wa.get("load_state"),
                "days_rest": wa.get("days_rest"),
                "long_haul": wa.get("long_haul"),
            },
            "workload_b": {
                "load_state": wb.get("load_state"),
                "days_rest": wb.get("days_rest"),
                "long_haul": wb.get("long_haul"),
            },
            "role_a": pa.get("tactical_role") or pa.get("system_context"),
            "role_b": pb.get("tactical_role") or pb.get("system_context"),
            "eo_a": ea.get("eo_pct"),
            "eo_b": eb.get("eo_pct"),
            "competitive_eo_a": da.get("eo_pct"),
            "competitive_eo_b": db.get("eo_pct"),
            "tactical_reason": proof.get("status"),
            "final_starter": pa.get("name") or a.get("name") or aid,
            "utility_margin": proof.get("margin"),
        })
    return out


def _display_player(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(
            value.get("name")
            or value.get("player")
            or value.get("element")
            or value.get("element_id")
            or "UNAVAILABLE"
        )
    return str(value if value not in (None, "") else "UNAVAILABLE")


def _xi_battle_presentation(
    *,
    battles: Sequence[Mapping[str, Any]],
    battle_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Presentation-only projection of the governed P1.7 XI battle."""
    rows = [dict(row) for row in battles if isinstance(row, Mapping)]
    primary = rows[0] if rows else {}
    table_rows: list[dict[str, Any]] = []
    if primary:
        table_rows = [
            {
                "player": primary.get("player_a"),
                "p_start": primary.get("p_start_a"),
                "xmins": primary.get("xmins_a"),
                "projection_1gw": primary.get("projection_1gw_a"),
            },
            {
                "player": primary.get("player_b"),
                "p_start": primary.get("p_start_b"),
                "xmins": primary.get("xmins_b"),
                "projection_1gw": primary.get("projection_1gw_b"),
            },
        ]
    summary = dict(battle_summary or {})
    return {
        "battle_rows": table_rows,
        "battles": rows,
        "empty_is_truthful": not bool(rows),
        "current_winner": primary.get("final_starter") or summary.get("winner"),
        "battle_classification": summary.get("status") or ("NO_MATERIAL_BATTLE" if not rows else "MATERIAL"),
        "primary_alternative": primary.get("player_b"),
        "reason": primary.get("tactical_reason") or summary.get("reason") or summary.get("status"),
        "battle_summary": summary,
    }


def _lineup_risk_presentation(
    *,
    lineup: Mapping[str, Any] | None,
    battles: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Presentation-only lineup risk/autosub surface; no new lineup decision math."""
    lineup_map = dict(lineup or {})
    bench = lineup_map.get("bench")
    bench_map = dict(bench) if isinstance(bench, Mapping) else {}
    bench_gk = (
        bench_map.get("bench_gk")
        or bench_map.get("gk")
        or bench_map.get("goalkeeper")
    )
    outfield = (
        bench_map.get("outfield_autosub_priority")
        or bench_map.get("order")
        or bench_map.get("outfield")
        or []
    )
    if not isinstance(outfield, Sequence) or isinstance(outfield, (str, bytes)):
        outfield = []
    risk_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in battles:
        battle = dict(raw)
        for suffix in ("a", "b"):
            player = str(battle.get(f"player_{suffix}") or "").strip()
            if not player or player in seen:
                continue
            seen.add(player)
            workload = dict(battle.get(f"workload_{suffix}") or {})
            flags = [
                str(value)
                for value in (
                    workload.get("load_state"),
                    "LONG HAUL" if workload.get("long_haul") is True else None,
                    battle.get(f"role_{suffix}"),
                )
                if value not in (None, "", "NORMAL", "AVAILABLE")
            ]
            risk_rows.append({
                "player": player,
                "p_start": battle.get(f"p_start_{suffix}"),
                "xmins": battle.get(f"xmins_{suffix}"),
                "flags": flags,
                "implication": (
                    "Current starter"
                    if player == str(battle.get("final_starter") or "")
                    else "Primary alternative"
                ),
            })
    return {
        "risk_rows": risk_rows,
        "lineup_implication": (
            "Keep the governed P1.7 XI; autosub order protects material start/minutes uncertainty."
            if risk_rows
            else "No material XI battle risk is currently identified."
        ),
        "bench_gk": _display_player(bench_gk),
        "autosub_order": [_display_player(value) for value in list(outfield)[:3]],
        "empty_is_truthful": not bool(risk_rows),
    }


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
    fixtures: Sequence[Mapping[str, Any]],
    bootstrap: Mapping[str, Any],
    owned_ids: set[int],
    completed_gw: int,
    watchlist: Mapping[str, Any] | None,
    previous_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build the due S16B package from existing factual/model authorities only."""
    if not projections or not foundation:
        raise IntegratedRunnerError("S16B due but post-match analytical foundation unavailable")

    match_rows = [
        dict(row)
        for row in foundation.get("player_match_rows") or []
        if isinstance(row, Mapping)
    ]
    pmap = _projection_map(projections)
    scan = build_post_match_universe_scan(
        current_projection_players=list(pmap.values()),
        previous_projection_players=None,
        player_match_rows=match_rows,
        current_gw=completed_gw,
        owned_element_ids=sorted(owned_ids),
    )

    def row_player_id(row: Mapping[str, Any]) -> int:
        try:
            return int(row.get("player_id") or row.get("element") or 0)
        except (TypeError, ValueError):
            return 0

    def row_fixture_id(row: Mapping[str, Any]) -> str:
        return str(
            row.get("fixture_id")
            or row.get("fixture")
            or row.get("match_id")
            or row.get("id")
            or ""
        )

    def row_gw(row: Mapping[str, Any]) -> int:
        try:
            return int(
                row.get("gw")
                or row.get("event")
                or row.get("gameweek")
                or row.get("round")
                or 0
            )
        except (TypeError, ValueError):
            return 0

    def first_supported(rows: Sequence[Mapping[str, Any]], *keys: str) -> Any:
        for row in rows:
            for key in keys:
                value = row.get(key)
                if value not in (None, ""):
                    return value
        return "UNAVAILABLE"

    def metric(row: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            if row.get(key) is not None:
                return row.get(key)
        return "UNAVAILABLE"

    team_names = {
        int(row.get("id") or 0): str(row.get("name") or row.get("short_name") or row.get("id"))
        for row in bootstrap.get("teams") or []
        if isinstance(row, Mapping) and int(row.get("id") or 0) > 0
    }
    element_names = {
        int(row.get("id") or 0): str(
            row.get("web_name") or row.get("first_name") or row.get("id")
        )
        for row in bootstrap.get("elements") or []
        if isinstance(row, Mapping) and int(row.get("id") or 0) > 0
    }

    gw_fixtures = [
        dict(row)
        for row in fixtures or []
        if isinstance(row, Mapping)
        and int(row.get("event") or row.get("gw") or 0) == int(completed_gw)
    ]
    gw_fixtures.sort(key=lambda row: int(row.get("id") or 0))
    fixture_ids = [str(row.get("id") or row.get("fixture_id") or "") for row in gw_fixtures]

    rows_by_fixture: dict[str, list[dict[str, Any]]] = {}
    rows_by_player: dict[int, list[dict[str, Any]]] = {}
    for row in match_rows:
        if row_gw(row) != int(completed_gw):
            continue
        fixture_id = row_fixture_id(row)
        if fixture_id:
            rows_by_fixture.setdefault(fixture_id, []).append(row)
        player_id = row_player_id(row)
        if player_id > 0:
            rows_by_player.setdefault(player_id, []).append(row)

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
        current_gw=completed_gw,
        maximum_material_deep_players=20,
    )
    material_details = [
        dict(row)
        for row in deep.get("details") or []
        if isinstance(row, Mapping)
    ]
    detail_by_id = {
        int(row.get("element_id") or row.get("player_id") or 0): row
        for row in material_details
        if int(row.get("element_id") or row.get("player_id") or 0) > 0
    }

    owned_reassessment: list[dict[str, Any]] = []
    previous_s16 = {
        int(row.get("element_id") or 0): dict(row)
        for row in _section_content_from_report(previous_report, "S16").get("rows") or []
        if isinstance(row, Mapping) and int(row.get("element_id") or 0) > 0
    }
    owned_match_detail: dict[int, dict[str, Any]] = {}
    upgrade_count = 0
    downgrade_count = 0
    stable_count = 0

    for element in sorted(owned_ids):
        player = pmap.get(element) or {}
        trajectory = build_player_trajectory(
            match_rows,
            player_id=element,
            current_gw=completed_gw,
        )
        latest = next(
            (
                dict(row)
                for row in reversed(trajectory.get("matches") or [])
                if isinstance(row, Mapping)
                and int(row.get("gw") or 0) == int(completed_gw)
            ),
            {},
        )
        mechanism = _visible_position_mechanism(player, action="HOLD") if player else {}
        classification = str(
            trajectory.get("trajectory_classification") or "STABLE_OR_NOISY"
        ).upper()
        if classification in {"IMPROVING", "MINUTES_ROLE_IMPROVING", "ROLE_TRANSITION"}:
            change = "UPGRADE"
            upgrade_count += 1
        elif classification in {"DECLINING", "MINUTES_ROLE_DECLINING"}:
            change = "DOWNGRADE"
            downgrade_count += 1
        else:
            change = "STABLE"
            stable_count += 1
        if classification == "MINUTES_ROLE_DECLINING":
            consequence = "PREPARE OUT"
        elif change == "DOWNGRADE":
            consequence = "WATCH"
        elif str(mechanism.get("recommended_or_locked_role") or "").upper() == "BENCH":
            consequence = "BENCH"
        else:
            consequence = "HOLD"

        prior = previous_s16.get(element) or {}
        row = {
            "element_id": element,
            "player": player.get("name") or element_names.get(element) or f"element:{element}",
            "pre_gw": {
                "p_start": prior.get("p_start", "UNAVAILABLE"),
                "xmins": prior.get("xmins", "UNAVAILABLE"),
                "bayesian_underlying": prior.get(
                    "bayesian_state",
                    prior.get("posterior_signal", "UNAVAILABLE"),
                ),
                "projection_1gw": prior.get("gw_plus_1", "UNAVAILABLE"),
                "projection_3gw": prior.get("three_gw", "UNAVAILABLE"),
                "projection_5gw": prior.get("five_gw", "UNAVAILABLE"),
            },
            "gw_evidence": latest or {"state": "NO_APPEARANCE_OR_ROW_UNAVAILABLE"},
            "post_gw": {
                "p_start": mechanism.get("p_start", "UNAVAILABLE"),
                "xmins": mechanism.get("xmins", "UNAVAILABLE"),
                "bayesian_underlying": player.get("posterior_rates", "UNAVAILABLE"),
                "projection_1gw": mechanism.get("gw_plus_1", "UNAVAILABLE"),
                "projection_3gw": mechanism.get("three_gw", "UNAVAILABLE"),
                "projection_5gw": mechanism.get("five_gw", "UNAVAILABLE"),
                "uncertainty": mechanism.get("uncertainty", "UNAVAILABLE"),
            },
            "classification": change,
            "evidence_classification": classification,
            "role_change": (
                "ROLE_GAIN"
                if classification == "ROLE_TRANSITION"
                else "ROLE_STABLE"
                if classification == "STABLE_OR_NOISY"
                else "UNAVAILABLE"
            ),
            "minutes_change": (
                "MINUTES_GAIN"
                if classification == "MINUTES_ROLE_IMPROVING"
                else "MINUTES_RISK"
                if classification == "MINUTES_ROLE_DECLINING"
                else "UNAVAILABLE"
            ),
            "consequence": consequence,
            "act_authority": False,
        }
        owned_reassessment.append(row)
        owned_match_detail[element] = row

    previous_watch_rows = [
        dict(row)
        for row in _section_content_from_report(previous_report, "S11").get("rows") or []
        if isinstance(row, Mapping)
    ]
    current_watch_rows = [
        dict(row)
        for row in (watchlist or {}).get("rows") or []
        if isinstance(row, Mapping)
    ]
    prev_rank = {
        int(row.get("element_id") or 0): index
        for index, row in enumerate(previous_watch_rows, start=1)
        if int(row.get("element_id") or 0) > 0
    }
    current_rank = {
        int(row.get("element_id") or 0): index
        for index, row in enumerate(current_watch_rows, start=1)
        if int(row.get("element_id") or 0) > 0
    }
    actionable_ids = {
        int(row.get("element_id") or 0)
        for row in (watchlist or {}).get("actionable_watchlist") or []
        if isinstance(row, Mapping) and int(row.get("element_id") or 0) > 0
    }
    watch_delta: list[dict[str, Any]] = []
    for element, rank in current_rank.items():
        old = prev_rank.get(element)
        movement = (
            "NEW"
            if old is None
            else "↑"
            if rank < old
            else "↓"
            if rank > old
            else "UNCHANGED"
        )
        watch_delta.append({
            "element_id": element,
            "player": element_names.get(element)
            or (pmap.get(element) or {}).get("name")
            or f"element:{element}",
            "previous_rank": old,
            "current_rank": rank,
            "movement_state": movement,
            "state": "ACTIONABLE" if element in actionable_ids else movement,
        })
    for element, old in prev_rank.items():
        if element not in current_rank:
            watch_delta.append({
                "element_id": element,
                "player": element_names.get(element) or f"element:{element}",
                "previous_rank": old,
                "current_rank": None,
                "movement_state": "OUT",
                "state": "OUT",
            })

    matches: list[dict[str, Any]] = []
    candidate_trace: list[dict[str, Any]] = []
    for fixture in gw_fixtures:
        fixture_id = str(fixture.get("id") or fixture.get("fixture_id") or "")
        frows = rows_by_fixture.get(fixture_id, [])
        home_id = int(fixture.get("team_h") or fixture.get("home_team") or 0)
        away_id = int(fixture.get("team_a") or fixture.get("away_team") or 0)
        home_score = fixture.get("team_h_score")
        away_score = fixture.get("team_a_score")
        result = (
            f"{team_names.get(home_id, home_id)} {home_score}–{away_score} "
            f"{team_names.get(away_id, away_id)}"
            if home_score is not None and away_score is not None
            else "UNAVAILABLE"
        )

        owned_players: list[dict[str, Any]] = []
        for element in sorted(owned_ids):
            rows = [row for row in frows if row_player_id(row) == element]
            if not rows:
                continue
            raw = rows[0]
            evidence = dict(owned_match_detail.get(element) or {})
            gw_ev = dict(evidence.get("gw_evidence") or {})
            owned_players.append({
                "element_id": element,
                "player": evidence.get("player"),
                "starter_sub_unused": (
                    "STARTER"
                    if raw.get("starter") is True or raw.get("started") is True
                    else "SUB"
                    if float(raw.get("minutes") or 0) > 0
                    else "UNUSED"
                ),
                "minutes": metric(raw, "minutes"),
                "fpl_points": metric(raw, "fpl_points", "total_points", "points"),
                "position_role": first_supported(rows, "role", "role_label", "position"),
                "xg": metric(raw, "xg", "expected_goals"),
                "xa": metric(raw, "xa", "expected_assists"),
                "xgi": metric(raw, "xgi", "expected_goal_involvements"),
                "shots": metric(raw, "shots", "total_shots"),
                "shots_on_target": metric(raw, "shots_on_target", "sot"),
                "box_touches": metric(raw, "box_touches", "touches_opposition_box"),
                "key_passes": metric(raw, "key_passes"),
                "chances_created": metric(raw, "chances_created"),
                "big_chances": metric(raw, "big_chances"),
                "set_pieces": first_supported(rows, "set_piece_role", "set_piece_duty"),
                "penalties": first_supported(rows, "penalty_role", "penalty_duty"),
                "defensive_contribution": metric(
                    raw, "defensive_contribution", "defensive_contributions"
                ),
                "substitution_timing": first_supported(
                    rows, "substitution_timing", "subbed_at", "substitution_minute"
                ),
                "analytical_read": {
                    "role_change": evidence.get("role_change"),
                    "minutes_change": evidence.get("minutes_change"),
                    "underlying_change": evidence.get("classification"),
                    "start_security": (
                        (evidence.get("post_gw") or {}).get("p_start")
                    ),
                    "sustainability": evidence.get("evidence_classification"),
                    "one_match_noise": (
                        evidence.get("evidence_classification") == "STABLE_OR_NOISY"
                    ),
                    "next_gw_implication": evidence.get("consequence"),
                },
                "trajectory_match": gw_ev,
            })

        watch_candidates: list[dict[str, Any]] = []
        material_ids = set(material_non_owned)
        for element in sorted(material_ids):
            rows = [row for row in frows if row_player_id(row) == element]
            if not rows:
                continue
            detail = detail_by_id.get(element) or {}
            reason = str(
                detail.get("primary_classification")
                or detail.get("classification")
                or "MATERIAL_POST_MATCH_SIGNAL"
            )
            trace = {
                "fixture_id": fixture_id,
                "player_id": element,
                "player": element_names.get(element)
                or (pmap.get(element) or {}).get("name")
                or f"element:{element}",
                "evidence_reason": reason,
                "role_observation": first_supported(
                    rows, "role", "role_label", "position"
                ),
                "underlying_observation": {
                    "xg": metric(rows[0], "xg", "expected_goals"),
                    "xa": metric(rows[0], "xa", "expected_assists"),
                    "shots": metric(rows[0], "shots", "total_shots"),
                },
                "minutes_evidence": metric(rows[0], "minutes"),
                "classification": "POST_MATCH_CANDIDATE",
            }
            candidate_trace.append(trace)
            watch_candidates.append(trace)

        matches.append({
            "fixture_id": fixture_id,
            "result": result,
            "venue": first_supported(frows, "venue"),
            "home_team": team_names.get(home_id, home_id),
            "away_team": team_names.get(away_id, away_id),
            "formation_system": {
                "home": first_supported(
                    [row for row in frows if int(row.get("team_id") or 0) == home_id],
                    "team_formation", "formation",
                ),
                "away": first_supported(
                    [row for row in frows if int(row.get("team_id") or 0) == away_id],
                    "team_formation", "formation",
                ),
            },
            "coach_pattern": {
                "tactical_approach": first_supported(frows, "tactical_approach"),
                "build_up_pattern": first_supported(frows, "build_up_pattern"),
                "press_block": first_supported(frows, "press_block"),
                "attacking_channels": first_supported(frows, "attacking_channels"),
                "substitution_pattern": first_supported(frows, "substitution_pattern"),
                "major_tactical_adjustment": first_supported(
                    frows, "major_tactical_adjustment"
                ),
            },
            "our_players": owned_players,
            "watch_candidates": watch_candidates,
            "tactical_takeaways": {
                "what_worked": first_supported(frows, "what_worked"),
                "what_changed": first_supported(frows, "what_changed"),
                "who_benefited": first_supported(frows, "who_benefited"),
                "who_lost_role_minutes": first_supported(
                    frows, "who_lost_role_minutes"
                ),
                "sustainable_vs_noisy": first_supported(
                    frows, "sustainable_vs_noisy"
                ),
                "our15_implication": [
                    row.get("analytical_read") for row in owned_players
                ],
                "future_opponent_implication": first_supported(
                    frows, "opponent_channels", "future_opponent_implication"
                ),
            },
        })

    current_watch_ids = set(current_rank)
    candidate_outcomes = []
    for candidate in candidate_trace:
        element = int(candidate.get("player_id") or 0)
        candidate_outcomes.append({
            **candidate,
            "full_universe_outcome": (
                "ADMITTED"
                if element in current_watch_ids
                else "DEFERRED"
                if element in set(material_non_owned)
                else "REJECTED"
            ),
        })

    movement_counts = {
        "NEW": sum(1 for row in watch_delta if row.get("movement_state") == "NEW"),
        "UP": sum(1 for row in watch_delta if row.get("movement_state") == "↑"),
        "DOWN": sum(1 for row in watch_delta if row.get("movement_state") == "↓"),
        "OUT": sum(1 for row in watch_delta if row.get("movement_state") == "OUT"),
        "ACTIONABLE": sum(1 for row in watch_delta if row.get("state") == "ACTIONABLE"),
    }
    unique_fixture_ids = {str(row.get("fixture_id") or "") for row in matches}
    return {
        "gw": int(completed_gw),
        "fixtures_expected": len(gw_fixtures),
        "fixtures_reviewed": len(matches),
        "unique_fixture_count": len(unique_fixture_ids),
        "duplicate_fixture_count": len(matches) - len(unique_fixture_ids),
        "match_by_match_review": matches,
        "after_gw_reassessment": {
            "summary": {
                "our15_upgrades": upgrade_count,
                "our15_downgrades": downgrade_count,
                "our15_stable": stable_count,
                "watchlist_new": movement_counts["NEW"],
                "watchlist_up": movement_counts["UP"],
                "watchlist_down": movement_counts["DOWN"],
                "watchlist_out": movement_counts["OUT"],
                "actionable": movement_counts["ACTIONABLE"],
            },
            "owned15_review": owned_reassessment,
            "watchlist_delta": watch_delta,
            "new_watch_candidates": candidate_outcomes,
            "material_universe_movers": material_details,
            "full_universe_scan": {
                "eligible_count": scan.get("eligible_count"),
                "scanned_count": scan.get("scanned_count"),
                "material_count": scan.get("material_count"),
                "scope": scan.get("scope"),
            },
            "decision_implications": {
                "act_authority": False,
                "allowed_states": ["HOLD", "START", "BENCH", "WATCH", "PREPARE OUT"],
                "canonical_transfer_decision_owner": "S14/P1.7/STAGE3",
            },
        },
        "full_universe_denominator": (
            scan.get("eligible_count")
            if scan.get("eligible_count") is not None
            else scan.get("scanned_count")
        ),
        # Compatibility aliases for existing evidence-quality consumers only.
        "our15": owned_reassessment,
        "material_universe_candidates": material_details,
        "full_universe_scan": {
            "eligible_count": scan.get("eligible_count"),
            "scanned_count": scan.get("scanned_count"),
            "material_count": scan.get("material_count"),
            "scope": scan.get("scope"),
        },
        "recency_weighting": "EXPONENTIAL_HALF_LIFE_GW",
        "bayesian_update": "ONLY_WHERE_EXISTING_POSTERIOR_RECOMPUTED",
        "candidate_traceability": candidate_outcomes,
        "fixture_ids_expected": fixture_ids,
        "fixture_ids_reviewed": [row.get("fixture_id") for row in matches],
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
    # The governed occurrence authority is the exact report slot. DEEP slots
    # are intentionally scheduled at :30, so rounding to the hour turns a
    # valid 21:30 publication into a false CORE_SLOT_MISMATCH.
    expected = requested
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



def refresh_price_only_state(
    *,
    runtime_data_root: Path,
    state: Mapping[str, Any],
    report_slot: str,
) -> dict[str, Any]:
    """Refresh price-dependent downstream surfaces without recomputing football math.

    PRICE_ONLY preserves Stage2 and exact P1.7. The predictor-derived price
    surfaces and their downstream presentation/stability surfaces are rebuilt
    from the frozen warm state, then canonical render/QA barriers are rerun.
    MC/scenario cache state is reported by the caller as PARTIAL_INVALIDATION;
    this executor does not pretend that unchanged football-return math was
    recomputed.
    """
    # Copy-on-write: PRICE_ONLY touches predictor-dependent/report surfaces only.
    # Keep frozen canonical football/model payloads by reference and copy only
    # containers that are actually mutated below.
    refreshed = dict(state)
    bundle_source = refreshed.get("bundle")
    warm_source = refreshed.get("warm_state")
    if not isinstance(bundle_source, Mapping) or not isinstance(warm_source, Mapping):
        raise IntegratedRunnerError(
            "PRICE_ONLY requires canonical bundle and warm state"
        )
    bundle = dict(bundle_source)
    warm = dict(warm_source)
    if str(bundle.get("report_mode") or "").upper() != "DEEP":
        raise IntegratedRunnerError("PRICE_ONLY partial refresh requires DEEP state")
    if not warm or not isinstance(bundle.get("report"), Mapping):
        raise IntegratedRunnerError("PRICE_ONLY requires frozen private warm state")

    projections = dict(warm.get("projections") or {})
    owned = [
        dict(row) for row in warm.get("owned") or [] if isinstance(row, Mapping)
    ]
    lineup = dict(warm.get("lineup") or {})
    finance = dict(warm.get("finance") or {})
    stage3_decision = dict(warm.get("stage3_decision") or {})
    calendar_context = dict(warm.get("calendar_context") or {})
    mini = dict(warm.get("mini") or {})
    package_with_stage3 = dict(warm.get("package_with_stage3") or {})
    monte_carlo = dict(warm.get("monte_carlo") or {})
    if (
        not projections
        or not owned
        or not lineup
        or not stage3_decision
        or not package_with_stage3
        or not monte_carlo
    ):
        raise IntegratedRunnerError(
            "PRICE_ONLY frozen decision prerequisites are incomplete"
        )

    # PRICE_ONLY does not recompute football math, but P1.8 carries a
    # deterministic proof of its upstream package/MC baseline. Rebuild that
    # downstream overlay from the frozen canonical football package so the
    # selective path is byte-semantic equivalent to a canonical cold run.
    package_for_overlay = dict(package_with_stage3)
    package_for_overlay.pop("mini_league_overlay", None)
    package_governance = package_for_overlay.get("governance")
    if isinstance(package_governance, Mapping):
        package_governance = dict(package_governance)
        package_governance.pop("mini_league_overlay_owner", None)
        package_governance.pop("mini_league_overlay_downstream_only", None)
        package_for_overlay["governance"] = package_governance
    mini_overlay = evaluate_mini_league_overlay(
        package_for_overlay,
        mini,
        monte_carlo=monte_carlo,
        relative_mc=None,
        input_snapshot_id="STAGE3_MINI:" + _fingerprint(mini)[:24],
        generated_at=report_slot,
    )
    package_with_stage3 = attach_mini_league_overlay(
        package_for_overlay,
        mini_overlay,
    )

    report = dict(bundle.get("report") or {})
    section_payloads: dict[str, dict[str, Any]] = {}
    for raw in report.get("sections") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("section_id") or "")
        if not sid:
            continue
        section_payloads[sid] = {
            "state": raw.get("state"),
            "content": raw.get("content"),
            "degradation_reason": raw.get("degradation_reason"),
            "available_count": raw.get("available_count"),
            "expected_count": raw.get("expected_count"),
        }
    required_sections = {
        "S01", "S02", "S03", "S08", "S10", "S11", "S12", "S13",
        "S14", "S15", "S15B", "S16", "S17", "S18", "S19",
    }
    missing = sorted(required_sections - set(section_payloads))
    if missing:
        raise IntegratedRunnerError(
            "PRICE_ONLY missing baseline sections: " + ",".join(missing)
        )

    predictor = _read_json(
        runtime_data_root / "data/v6/current/official_price_predictor.json",
        {},
    ) or {}
    owned_ids = sorted(
        int(row.get("element_id") or 0)
        for row in owned
        if int(row.get("element_id") or 0) > 0
    )
    rise = build_price20(
        predictor_artifact=predictor,
        direction="RISE",
        owned_element_ids=owned_ids,
        report_timestamp=report_slot,
    )
    fall = build_price20(
        predictor_artifact=predictor,
        direction="FALL",
        owned_element_ids=owned_ids,
        report_timestamp=report_slot,
    )
    price_radar = build_actionable_price_radar(
        owned15=owned,
        predictor_artifact=predictor,
        report_timestamp=report_slot,
    )
    watchlist = _enrich_watchlist_rows(
        dict(warm.get("watchlist") or {}),
        projections=projections,
        predictor=predictor,
    )

    official = _official_payload(runtime_data_root)
    s15b_content = dict(section_payloads["S15B"].get("content") or {})
    s15b_content["downstream_overlay"] = mini_overlay
    all15_rows = _enrich_all15_rows(
        all15=dict(warm.get("all15") or {}),
        projections=projections,
        predictor=predictor,
        owned=owned,
        bootstrap=official["bootstrap"],
        mini=mini,
        mini_detail=s15b_content,
        calendar_context=calendar_context,
    )

    s01_existing = dict(section_payloads["S01"].get("content") or {})
    old_dashboard = dict(s01_existing.get("decision_dashboard") or {})
    personal_auth = str(old_dashboard.get("PERSONAL_AUTH") or "UNAVAILABLE")
    auth_state = (
        "AUTH_AVAILABLE"
        if personal_auth == "AVAILABLE"
        else "AUTH_EXPIRED"
        if personal_auth == "DEGRADED"
        else "UNAVAILABLE"
    )
    captain_surface = dict(section_payloads["S08"].get("content") or {})
    captain_surface.pop("authoritative_binding", None)
    operational_action = str(
        stage3_decision.get("operational_action") or "WAIT"
    ).upper()
    decision_dashboard = _decision_dashboard(
        operational_action=operational_action,
        planning_gw=int(
            warm.get("planning_gw")
            or bundle.get("planning_gw")
            or 1
        ),
        stage3_decision=stage3_decision,
        lineup_state="COMPLETE",
        lineup=lineup,
        captain_surface=captain_surface,
        chip_available=(
            finance.get("chips") not in (None, {}, [])
            and finance.get("chips_status") == "AVAILABLE"
        ),
        price_radar=price_radar,
        auth_state=auth_state,
        finance=finance,
    )
    stage3_visible = dict(section_payloads["S14"].get("content") or {})
    stage3_visible.pop("authoritative_binding", None)
    stage3_visible["mini_league_overlay"] = dict(mini_overlay)
    action_board = _action_board_surface(
        dashboard=decision_dashboard,
        stage3_decision=stage3_decision,
        stage3_visible=stage3_visible,
        all15_rows=all15_rows,
    )
    action_board["captain_decision"] = {
        "captain": dict(captain_surface.get("captain") or {}),
        "vice_captain": dict(captain_surface.get("vice_captain") or {}),
        "football_leader": dict(captain_surface.get("football_leader") or {}),
        "frontier_classification": captain_surface.get(
            "football_frontier_classification"
        ),
        "risk_posture": captain_surface.get("risk_posture"),
        "source": "S08_CANONICAL_CAPTAIN_DECISION",
    }

    bindings = {
        "S01": "STAGE3_DECISION+S08+S09+S10+S17",
        "S02": "CURRENT15_RESOLUTION+P1_1_P1_3+S05+S15B",
        "S10": "OFFICIAL_FPL_PRICE_FACT+PRICE_PREDICTOR",
        "S11": "WATCHLIST20",
        "S12": "OFFICIAL_FPL_PREDICTOR_RISE20",
        "S13": "OFFICIAL_FPL_PREDICTOR_FALL20",
        "S15": "BOUND_SOURCE_HEALTH+MODEL_EXECUTION",
        "S15B": "P1_8_MINI_LEAGUE_SNAPSHOT+P1_8_MINI_LEAGUE_OVERLAY",
        "S16": "P1_1_P1_3_FULL_UNIVERSE+P1_6_TACTICAL_ROLE",
        "S18": "S01+S08+S10+S14+TEAM_NEWS",
    }

    def bound(sid: str, content: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(content)
        producer = bindings.get(sid)
        if producer:
            out["authoritative_binding"] = {
                "status": "BOUND",
                "producer": producer,
                "payload_fingerprint": _fingerprint(
                    {
                        key: value
                        for key, value in out.items()
                        if key != "authoritative_binding"
                    }
                ),
                "report_slot": report_slot,
            }
        return out

    section_payloads["S15B"]["content"] = bound("S15B", s15b_content)

    s01_existing.update(
        {
            "decision_dashboard": decision_dashboard,
            "operational_state": operational_action,
            "reason": decision_dashboard.get("PRIMARY_REASON"),
            "key_decision_driver": decision_dashboard.get("KEY_DRIVER"),
            "current_blockers": decision_dashboard.get("CURRENT_BLOCKERS"),
        }
    )
    section_payloads["S01"]["content"] = bound("S01", s01_existing)

    s02 = dict(section_payloads["S02"].get("content") or {})
    s02["rows"] = all15_rows
    section_payloads["S02"]["content"] = bound("S02", s02)

    s03 = dict(section_payloads["S03"].get("content") or {})
    decision_delta = dict(s03.get("decision_delta") or {})
    current_snapshot = dict(decision_delta.get("current_snapshot") or {})
    player_state = dict(current_snapshot.get("player_state") or {})
    price_by_element = {
        str(int(row.get("element_id") or 0)): row.get("price_relevance")
        for row in all15_rows
        if int(row.get("element_id") or 0) > 0
    }
    for element, price_relevance in price_by_element.items():
        if element in player_state and isinstance(player_state[element], Mapping):
            row = dict(player_state[element])
            row["price_urgency"] = price_relevance
            player_state[element] = row
    if current_snapshot:
        current_snapshot["player_state"] = player_state
        decision_delta["current_snapshot"] = current_snapshot
        s03["decision_delta"] = decision_delta
        section_payloads["S03"]["content"] = s03

    s10 = {
        **price_radar,
        "bank": finance.get("bank"),
        "bank_status": finance.get("bank_status"),
        "sell_value_status": finance.get("sell_value_status"),
    }
    section_payloads["S10"] = _section(
        "COMPLETE" if price_radar else "DEGRADED",
        bound("S10", s10) if price_radar else s10,
        None if price_radar else "Official FPL predictor radar unavailable",
    )

    s11 = dict(section_payloads["S11"].get("content") or {})
    s11.update(watchlist)
    section_payloads["S11"]["content"] = bound("S11", s11)

    section_payloads["S12"] = _section(
        str(rise.get("state") or "UNAVAILABLE"),
        bound("S12", rise),
        rise.get("degradation_reason"),
        available_count=rise.get("available_count", 0),
        expected_count=20,
    )
    section_payloads["S13"] = _section(
        str(fall.get("state") or "UNAVAILABLE"),
        bound("S13", fall),
        fall.get("degradation_reason"),
        available_count=fall.get("available_count", 0),
        expected_count=20,
    )

    s15 = dict(section_payloads["S15"].get("content") or {})
    evidence_quality = dict(s15.get("evidence_quality") or {})
    price_rows = [
        dict(row)
        for row in rise.get("rows") or []
        if isinstance(row, Mapping)
    ]
    evidence_quality["price predictor freshness"] = {
        "state": next(
            (
                str(row.get("freshness") or "").upper()
                for row in price_rows
            ),
            "UNAVAILABLE",
        ),
        "health": rise.get("predictor_health"),
        "observed_at": (
            price_rows[0].get("evidence_timestamp")
            if price_rows else None
        ),
    }
    s15["evidence_quality"] = evidence_quality
    section_payloads["S15"]["content"] = bound("S15", s15)

    s16 = dict(section_payloads["S16"].get("content") or {})
    s16["rows"] = all15_rows
    section_payloads["S16"]["content"] = bound("S16", s16)

    s17 = dict(section_payloads["S17"].get("content") or {})
    source_health = dict(s17.get("source_health") or {})
    source_health.update(
        {
            "price_predictor": rise.get("predictor_health") or "UNAVAILABLE",
            "price_predictor_freshness": next(
                (
                    str(row.get("freshness") or "UNKNOWN").upper()
                    for row in price_rows
                ),
                "UNAVAILABLE",
            ),
            "price_predictor_source_age_minutes": next(
                (
                    row.get("source_age_minutes")
                    for row in price_rows
                ),
                None,
            ),
        }
    )
    s17["source_health"] = source_health
    section_payloads["S17"]["content"] = s17

    s18 = dict(section_payloads["S18"].get("content") or {})
    s18.update(
        {
            "action_board": action_board,
            "NOW": {
                row.get("axis"): row.get("NOW")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "NEXT": {
                row.get("axis"): row.get("NEXT")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "TRIGGER TO ACT": {
                row.get("axis"): row.get("TRIGGER TO ACT")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "LATEST SAFE DECISION POINT": {
                row.get("axis"): row.get("LATEST SAFE DECISION_POINT")
                for row in []
            },
            "COST OF WAITING": {
                row.get("axis"): row.get("COST OF WAITING")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "ABORT / REVERSAL": {
                row.get("axis"): row.get("ABORT / REVERSAL")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "BEST ALTERNATIVE": action_board.get("best_alternative"),
        }
    )
    s18["LATEST SAFE DECISION POINT"] = {
        row.get("axis"): row.get("LATEST SAFE DECISION POINT")
        for row in action_board.get("axes") or []
        if isinstance(row, Mapping)
    }
    section_payloads["S18"]["content"] = bound("S18", s18)

    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    new_report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads=section_payloads,
    )
    section_manifest = [
        {
            "section_id": str(row.get("section_id") or ""),
            "status": str(row.get("state") or ""),
        }
        for row in new_report.get("sections") or []
    ]
    human_manifest = build_deep_human_facing_manifest(new_report)
    compute_contract = _qa_compute_contract(
        owned=owned,
        lineup=lineup,
        watchlist=watchlist,
        rise=rise,
        fall=fall,
        sections=section_payloads,
        human_manifest=human_manifest,
    )
    mini_complete = bool(
        mini and str(mini.get("coverage_state") or "").upper() == "FULL"
    )
    weather_contract_state = _weather_contract_state_from_calendar(
        calendar_context
    )
    pre_render_qa = validate_pre_render_qa(
        compute_contract=compute_contract,
        section_manifest=section_manifest,
        mini_league_denominator_complete=mini_complete,
        report_mode="DEEP",
        weather_contract_state=weather_contract_state,
    )
    body = render_deep_text(new_report)
    final_delivery_barrier = validate_final_delivery_barrier(
        report_mode="DEEP",
        report=new_report,
        body=body,
    )
    human_failures = list(
        dict.fromkeys(
            validate_human_facing_body(body)
            + validate_deep_human_facing_manifest(human_manifest)
            + list(final_delivery_barrier.get("failures") or [])
        )
    )
    parsed_ids, _, _ = _parse_sections(body)
    rendered_states = {
        str(row.get("section_id") or ""): str(row.get("state") or "")
        for row in new_report.get("sections") or []
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
        rendered_weather_contract_state=weather_contract_state,
        truncated=False,
    )
    if (
        str(pre_render_qa.get("status") or "").upper() != "PASS"
        or str(post_render_qa.get("status") or "").upper() != "PASS"
        or human_failures
        or str(final_delivery_barrier.get("status") or "").upper() != "PASS"
    ):
        raise IntegratedRunnerError(
            "PRICE_ONLY partial refresh failed canonical delivery QA: "
            + json.dumps(
                {
                    "pre_render": pre_render_qa.get("status"),
                    "post_render": post_render_qa.get("status"),
                    "human_facing_failures": human_failures,
                    "final_delivery": {
                        "status": final_delivery_barrier.get("status"),
                        "failures": final_delivery_barrier.get("failures") or [],
                    },
                },
                sort_keys=True,
                ensure_ascii=True,
            )
        )

    ledger = [
        dict(row)
        for row in bundle.get("stage_ledger") or []
        if isinstance(row, Mapping)
    ]
    ledger.append(
        {
            "stage": "P6_PRICE_ONLY_PARTIAL_REFRESH",
            "status": "PASS",
            "required": True,
            "reason": None,
            "evidence": {
                "change_class": "PRICE_ONLY",
                "reused_layers": ["Stage2", "P1.7"],
                "partial_layers": ["MC", "scenario"],
                "recomputed_layers": [
                    "PRICE_SURFACES",
                    "P1.8_MINI_LEAGUE_OVERLAY",
                    "STABILITY",
                    "DEPENDENT_REPORT_SURFACES",
                    "QA",
                ],
                "football_math_recomputed": False,
                "second_optimizer_created": False,
            },
        }
    )
    execution_proof = dict(bundle.get("execution_proof") or {})
    execution_proof["stages"] = ledger
    execution_proof["warm_partial_refresh"] = {
        "change_class": "PRICE_ONLY",
        "status": "PASS",
        "stage2_reused": True,
        "p1_7_reused": True,
        "mc_partial_invalidation": True,
        "scenario_partial_invalidation": True,
        "stability_recomputed": True,
        "football_math_recomputed": False,
        "affected_dependency_scope": "PRICE_ONLY",
    }

    source_fingerprints = dict(bundle.get("source_fingerprints") or {})
    source_fingerprints["price_predictor"] = _fingerprint(predictor)
    bundle.update(
        {
            "runner_status": "PASS",
            "stage_ledger": ledger,
            "section_manifest": section_manifest,
            "human_facing_manifest": human_manifest,
            "compute_contract": compute_contract,
            "pre_render_qa": pre_render_qa,
            "post_render_qa": post_render_qa,
            "human_facing_qa": {"status": "PASS", "failures": []},
            "execution_proof": execution_proof,
            "report": new_report,
            "visible_body": body,
            "source_fingerprints": source_fingerprints,
        }
    )
    governance_out = dict(bundle.get("governance") or {})
    governance_out.update(
        {
            "p6_partial_refresh": "PRICE_ONLY",
            "p6_partial_refresh_reused_football_math": True,
            "qa_relaxed": False,
            "second_methodology_created": False,
        }
    )
    bundle["governance"] = governance_out
    warm.update(
        {
            "predictor": predictor,
            "rise": rise,
            "fall": fall,
            "price_radar": price_radar,
            "watchlist": watchlist,
            "package_with_stage3": package_with_stage3,
            "mini_overlay": mini_overlay,
        }
    )
    refreshed["bundle"] = bundle
    refreshed["execution_proof"] = execution_proof
    refreshed["warm_state"] = warm

    output_dir = Path(str(refreshed.get("output_dir") or ""))
    if not output_dir:
        raise IntegratedRunnerError("PRICE_ONLY output_dir is unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report_bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "execution_proof.json").write_text(
        json.dumps(
            execution_proof,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "report_body.md").write_text(body, encoding="utf-8")
    refreshed["warm_layer_timings"] = {
        "change_class": "PRICE_ONLY",
        "seconds": {
            "MC": 0.0,
            "scenario": 0.0,
        },
        "evidence": {
            "football_math_recomputed": False,
            "mc_execution_skipped": True,
            "scenario_execution_skipped": True,
            "price_surfaces_recomputed": True,
        },
    }
    return refreshed


def refresh_mini_league_only_state(
    *,
    runtime_data_root: Path,
    state: Mapping[str, Any],
    report_slot: str,
) -> dict[str, Any]:
    """Refresh only downstream P1.8/report surfaces for MINI_LEAGUE_ONLY.

    The frozen football state remains authoritative: Stage2, exact P1.7 and
    canonical P1.4 MC are reused read-only. Fresh standings/submitted-picks
    evidence is rebound through P1.8, then all dependent visible surfaces are
    rematerialized and pass the same QA/final-delivery barriers as a cold run.
    """
    # Copy-on-write: the frozen canonical warm state can be very large.
    # MINI_LEAGUE_ONLY changes only P1.8/downstream report surfaces, so keep
    # unchanged football/model payloads by reference and copy only containers
    # that are actually mutated below.
    refreshed = dict(state)
    bundle_source = refreshed.get("bundle")
    warm_source = refreshed.get("warm_state")
    if not isinstance(bundle_source, Mapping) or not isinstance(warm_source, Mapping):
        raise IntegratedRunnerError(
            "MINI_LEAGUE_ONLY requires canonical bundle and warm state"
        )
    bundle = dict(bundle_source)
    warm = dict(warm_source)
    if str(bundle.get("report_mode") or "").upper() != "DEEP":
        raise IntegratedRunnerError("MINI_LEAGUE_ONLY partial refresh requires DEEP state")
    if not warm or not isinstance(bundle.get("report"), Mapping):
        raise IntegratedRunnerError("MINI_LEAGUE_ONLY requires frozen private warm state")

    projections = dict(warm.get("projections") or {})
    owned = [
        dict(row) for row in warm.get("owned") or [] if isinstance(row, Mapping)
    ]
    lineup = dict(warm.get("lineup") or {})
    predictor = dict(warm.get("predictor") or {})
    calendar_context = dict(warm.get("calendar_context") or {})
    bgw_context = dict(warm.get("bgw_context") or {})
    finance = dict(warm.get("finance") or {})
    stage3_decision = dict(warm.get("stage3_decision") or {})
    package_with_stage3 = dict(warm.get("package_with_stage3") or {})
    monte_carlo = dict(warm.get("monte_carlo") or {})
    if not projections or not owned or not lineup or not package_with_stage3:
        raise IntegratedRunnerError(
            "MINI_LEAGUE_ONLY frozen football prerequisites are incomplete"
        )

    # Strip the old P1.8 attachment before recomputing the downstream overlay.
    package_with_stage3.pop("mini_league_overlay", None)
    governance = package_with_stage3.get("governance")
    if isinstance(governance, Mapping):
        governance = dict(governance)
        governance.pop("mini_league_overlay_owner", None)
        governance.pop("mini_league_overlay_downstream_only", None)
        package_with_stage3["governance"] = governance

    standings = _read_json(
        runtime_data_root / "data/v6/mini_leagues/9477/standings.json",
        {},
    ) or {}
    picks_paths = list(
        (runtime_data_root / "data/v6/mini_leagues/9477").glob(
            "gw_*_manager_picks.json"
        )
    )
    picks_gw = max(
        [
            int(path.name.split("_")[1])
            for path in picks_paths
            if path.name.startswith("gw_")
        ]
        or [max(1, int(warm.get("planning_gw") or 1) - 1)]
    )
    manager_picks = _read_json(
        runtime_data_root
        / f"data/v6/mini_leagues/9477/gw_{picks_gw}_manager_picks.json",
        {},
    ) or {}
    planning_gw = int(warm.get("planning_gw") or bundle.get("planning_gw") or 1)
    mini = build_mini_league_snapshot(
        standings,
        manager_picks,
        our_entry_id=3462711,
        planning_gw=planning_gw,
    )
    mini_overlay = evaluate_mini_league_overlay(
        package_with_stage3,
        mini,
        monte_carlo=monte_carlo,
        relative_mc=None,
        input_snapshot_id="STAGE3_MINI:" + _fingerprint(mini)[:24],
        generated_at=report_slot,
    )
    package_with_stage3 = attach_mini_league_overlay(
        package_with_stage3,
        mini_overlay,
    )

    report = dict(bundle.get("report") or {})
    section_payloads: dict[str, dict[str, Any]] = {}
    for raw in report.get("sections") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("section_id") or "")
        if not sid:
            continue
        section_payloads[sid] = {
            "state": raw.get("state"),
            # Unchanged section content is immutable for this refresh. Each
            # MINI-dependent section is copied explicitly before mutation.
            "content": raw.get("content"),
            "degradation_reason": raw.get("degradation_reason"),
            "available_count": raw.get("available_count"),
            "expected_count": raw.get("expected_count"),
        }
    required_sections = {"S01", "S02", "S06B", "S07", "S08", "S14", "S14B",
                         "S15B", "S16", "S18", "S19"}
    missing = sorted(required_sections - set(section_payloads))
    if missing:
        raise IntegratedRunnerError(
            "MINI_LEAGUE_ONLY missing baseline sections: " + ",".join(missing)
        )

    official = _official_payload(runtime_data_root)
    mini_deep_detail = _mini_league_deep_detail(
        mini=mini,
        standings=standings,
        manager_picks=manager_picks,
        owned=owned,
        projections=projections,
        lineup=lineup,
        mini_overlay=mini_overlay,
        disclosed_gw=picks_gw,
        operational_action=str(
            stage3_decision.get("operational_action") or "WAIT"
        ).upper(),
        calendar_context=calendar_context,
    )
    formation_strategy = _formation_mini_league_strategy(
        lineup=lineup,
        mini=mini,
        mini_overlay=mini_overlay,
        projections=projections,
    )
    all15_rows = _enrich_all15_rows(
        all15=warm.get("all15"),
        projections=projections,
        predictor=predictor,
        owned=owned,
        bootstrap=official["bootstrap"],
        mini=mini,
        mini_detail=mini_deep_detail,
        calendar_context=calendar_context,
    )
    xi_battles = _xi_battles(
        lineup=lineup,
        projections=projections,
        mini=mini,
        mini_detail=mini_deep_detail,
        calendar_context=calendar_context,
    )
    lineup_state = "COMPLETE"
    captain_surface = _captain_decision_surface(
        owned=owned,
        lineup=lineup,
        lineup_state=lineup_state,
        mini_detail=mini_deep_detail,
        projections=projections,
    )

    captain_frontier_ids = {
        int(row.get("element_id") or 0)
        for row in captain_surface.get("captain_frontier") or []
        if isinstance(row, Mapping)
    }
    selected_captain_id = _surface_element(captain_surface.get("captain"))
    selected_vice_id = _surface_element(captain_surface.get("vice_captain"))
    mini_deep_detail["captain_leverage"] = [
        {
            **dict(row),
            "football_frontier_member": int(row.get("element_id") or 0)
            in captain_frontier_ids,
            "selected_captain": int(row.get("element_id") or 0)
            == int(selected_captain_id or 0),
            "selected_vice": int(row.get("element_id") or 0)
            == int(selected_vice_id or 0),
            "decision_authority": "EVIDENCE_ONLY_S08_OWNS_C_VC_DECISION",
        }
        for row in mini_deep_detail.get("captain_leverage") or []
        if isinstance(row, Mapping)
    ]

    # S14 keeps the frozen football frontier/MC, replacing only its P1.8 fields.
    stage3_visible = dict(section_payloads["S14"].get("content") or {})
    stage3_visible["mini_league_overlay"] = dict(mini_overlay)
    if isinstance(stage3_visible.get("package_routes"), list):
        stage3_visible["package_routes"] = [
            (
                {
                    **dict(row),
                    "mini_league_utility": mini_overlay.get("decision_delta"),
                }
                if isinstance(row, Mapping)
                else row
            )
            for row in stage3_visible.get("package_routes") or []
        ]
    if isinstance(stage3_visible.get("package_universe_challengers"), list):
        stage3_visible["package_universe_challengers"] = [
            (
                {
                    **dict(row),
                    "mini_league_leverage": mini_overlay.get("decision_delta"),
                }
                if isinstance(row, Mapping)
                else row
            )
            for row in stage3_visible.get("package_universe_challengers") or []
        ]

    chip_state = finance.get("chips")
    chip_available = (
        chip_state not in (None, {}, [])
        and finance.get("chips_status") == "AVAILABLE"
    )
    staging = dict(section_payloads["S14B"].get("content") or {})
    final_judgement = _final_judgement_surface(
        operational_action=str(
            stage3_decision.get("operational_action") or "WAIT"
        ).upper(),
        stage3_decision=stage3_decision,
        stage3_visible=stage3_visible,
        lineup=lineup,
        captain_surface=captain_surface,
        mini_detail=mini_deep_detail,
        staging=staging,
        chip_state=chip_state if chip_available else None,
    )
    final_judgement["bgw_context"] = bgw_context
    final_judgement["bgw_reconciled"] = True

    baseline_dashboard = dict(
        (section_payloads["S01"].get("content") or {}).get(
            "decision_dashboard"
        )
        or {}
    )
    personal_auth = str(baseline_dashboard.get("PERSONAL_AUTH") or "UNAVAILABLE")
    auth_state = (
        "AUTH_AVAILABLE"
        if personal_auth == "AVAILABLE"
        else "AUTH_EXPIRED"
        if personal_auth == "DEGRADED"
        else "UNAVAILABLE"
    )
    decision_dashboard = _decision_dashboard(
        operational_action=str(
            stage3_decision.get("operational_action") or "WAIT"
        ).upper(),
        planning_gw=planning_gw,
        stage3_decision=stage3_decision,
        lineup_state=lineup_state,
        lineup=lineup,
        captain_surface=captain_surface,
        chip_available=chip_available,
        price_radar=dict(warm.get("price_radar") or {}),
        auth_state=auth_state,
        finance=finance,
    )
    action_board = _action_board_surface(
        dashboard=decision_dashboard,
        stage3_decision=stage3_decision,
        stage3_visible=stage3_visible,
        all15_rows=all15_rows,
    )
    action_board["captain_decision"] = {
        "captain": dict(captain_surface.get("captain") or {}),
        "vice_captain": dict(captain_surface.get("vice_captain") or {}),
        "football_leader": dict(captain_surface.get("football_leader") or {}),
        "frontier_classification": captain_surface.get(
            "football_frontier_classification"
        ),
        "risk_posture": captain_surface.get("risk_posture"),
        "source": "S08_CANONICAL_CAPTAIN_DECISION",
    }

    bindings = {
        "S01": "STAGE3_DECISION+S08+S09+S10+S17",
        "S02": "CURRENT15_RESOLUTION+P1_1_P1_3+S05+S15B",
        "S07": "P1_7_XI_BATTLE+P1_1+S05+S15B",
        "S08": "P1_7_LEGALITY+P1_3B_CAPTAIN_FRONTIER+P1_8_COMPETITIVE_TIEBREAK",
        "S14": "P1_2_PACKAGE_UTILITY+P1_4_MONTE_CARLO+P1_8_MINI_LEAGUE_OVERLAY",
        "S15B": "P1_8_MINI_LEAGUE_SNAPSHOT+P1_8_MINI_LEAGUE_OVERLAY",
        "S16": "P1_1_P1_3_FULL_UNIVERSE+P1_6_TACTICAL_ROLE",
        "S18": "S01+S08+S10+S14+TEAM_NEWS",
        "S19": "S08_CAPTAIN_FRONTIER+S15B_MINI_LEAGUE_RECONCILIATION",
    }

    def bound(sid: str, content: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(content)
        producer = bindings.get(sid)
        if producer:
            payload_fingerprint = _fingerprint(
                {
                    key: value
                    for key, value in out.items()
                    if key != "authoritative_binding"
                }
            )
            out["authoritative_binding"] = {
                "status": "BOUND",
                "producer": producer,
                "payload_fingerprint": payload_fingerprint,
                "report_slot": report_slot,
            }
        return out

    s01 = dict(section_payloads["S01"].get("content") or {})
    s01.update(
        {
            "decision_dashboard": decision_dashboard,
            "operational_state": str(
                stage3_decision.get("operational_action") or "WAIT"
            ).upper(),
            "reason": decision_dashboard.get("PRIMARY_REASON"),
            "key_decision_driver": decision_dashboard.get("KEY_DRIVER"),
            "current_blockers": decision_dashboard.get("CURRENT_BLOCKERS"),
        }
    )
    section_payloads["S01"]["content"] = bound("S01", s01)

    s02 = dict(section_payloads["S02"].get("content") or {})
    s02["rows"] = all15_rows
    section_payloads["S02"]["content"] = bound("S02", s02)

    section_payloads["S06B"] = _section(
        "COMPLETE",
        bound(
            "S06B",
            _xi_battle_presentation(
                battles=xi_battles,
                battle_summary=lineup.get("main_starting_xi_battle"),
            ),
        ),
    )
    section_payloads["S07"]["content"] = bound(
        "S07",
        _lineup_risk_presentation(
            lineup=lineup,
            battles=xi_battles,
        ),
    )
    section_payloads["S08"]["content"] = bound("S08", captain_surface)

    section_payloads["S14"]["content"] = bound("S14", stage3_visible)

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
    s15b = {
        **mini,
        "current_league_context": _mini_context(mini),
        "exposures": list(mini.get("exposures") or []),
        "downstream_overlay": mini_overlay,
        "football_baseline_precedes_leverage": True,
        "protection_players": formation_strategy.get("high_eo_protection"),
        "differential_opportunities": formation_strategy.get(
            "differential_slots"
        ),
        **mini_deep_detail,
    }
    section_payloads["S15B"] = _section(
        mini_state,
        bound("S15B", s15b) if mini_state == "COMPLETE" else s15b,
        mini_reason,
    )

    s16 = dict(section_payloads["S16"].get("content") or {})
    s16["rows"] = all15_rows
    section_payloads["S16"]["content"] = bound("S16", s16)

    s18 = dict(section_payloads["S18"].get("content") or {})
    s18.update(
        {
            "action_board": action_board,
            "NOW": {
                row.get("axis"): row.get("NOW")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "NEXT": {
                row.get("axis"): row.get("NEXT")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "TRIGGER TO ACT": {
                row.get("axis"): row.get("TRIGGER TO ACT")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "LATEST SAFE DECISION POINT": {
                row.get("axis"): row.get("LATEST SAFE DECISION POINT")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "COST OF WAITING": {
                row.get("axis"): row.get("COST OF WAITING")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "ABORT / REVERSAL": {
                row.get("axis"): row.get("ABORT / REVERSAL")
                for row in action_board.get("axes") or []
                if isinstance(row, Mapping)
            },
            "BEST ALTERNATIVE": action_board.get("best_alternative"),
        }
    )
    section_payloads["S18"]["content"] = bound("S18", s18)
    section_payloads["S19"]["content"] = bound(
        "S19",
        {"final_judgement": final_judgement},
    )

    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    new_report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads=section_payloads,
    )
    section_manifest = [
        {
            "section_id": str(row.get("section_id") or ""),
            "status": str(row.get("state") or ""),
        }
        for row in new_report.get("sections") or []
    ]
    human_manifest = build_deep_human_facing_manifest(new_report)
    compute_contract = _qa_compute_contract(
        owned=owned,
        lineup=lineup,
        watchlist=dict(warm.get("watchlist") or {}),
        rise=dict(warm.get("rise") or {}),
        fall=dict(warm.get("fall") or {}),
        sections=section_payloads,
        human_manifest=human_manifest,
    )
    mini_complete = bool(
        mini and str(mini.get("coverage_state") or "").upper() == "FULL"
    )
    weather_contract_state = _weather_contract_state_from_calendar(
        calendar_context
    )
    pre_render_qa = validate_pre_render_qa(
        compute_contract=compute_contract,
        section_manifest=section_manifest,
        mini_league_denominator_complete=mini_complete,
        report_mode="DEEP",
        weather_contract_state=weather_contract_state,
    )
    body = render_deep_text(new_report)
    final_delivery_barrier = validate_final_delivery_barrier(
        report_mode="DEEP",
        report=new_report,
        body=body,
    )
    human_failures = list(
        dict.fromkeys(
            validate_human_facing_body(body)
            + validate_deep_human_facing_manifest(human_manifest)
            + list(final_delivery_barrier.get("failures") or [])
        )
    )
    parsed_ids, _, _ = _parse_sections(body)
    rendered_states = {
        str(row.get("section_id") or ""): str(row.get("state") or "")
        for row in new_report.get("sections") or []
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
        rendered_weather_contract_state=weather_contract_state,
        truncated=False,
    )
    if (
        str(pre_render_qa.get("status") or "").upper() != "PASS"
        or str(post_render_qa.get("status") or "").upper() != "PASS"
        or human_failures
        or str(final_delivery_barrier.get("status") or "").upper() != "PASS"
    ):
        safe_qa_failure = {
            "pre_render": {
                "status": str(pre_render_qa.get("status") or ""),
                "failures": [
                    str(value)
                    for value in (
                        pre_render_qa.get("hard_failures")
                        or pre_render_qa.get("failures")
                        or []
                    )
                ],
            },
            "post_render": {
                "status": str(post_render_qa.get("status") or ""),
                "failures": [
                    str(value)
                    for value in (
                        post_render_qa.get("hard_failures")
                        or post_render_qa.get("failures")
                        or []
                    )
                ],
            },
            "human_facing_failures": [str(value) for value in human_failures],
            "final_delivery": {
                "status": str(final_delivery_barrier.get("status") or ""),
                "failures": [
                    str(value)
                    for value in (final_delivery_barrier.get("failures") or [])
                ],
            },
        }
        raise IntegratedRunnerError(
            "MINI_LEAGUE_ONLY partial refresh failed canonical delivery QA: "
            + json.dumps(safe_qa_failure, sort_keys=True, ensure_ascii=True)
        )

    ledger = [
        dict(row)
        for row in bundle.get("stage_ledger") or []
        if isinstance(row, Mapping)
    ]
    ledger.append(
        {
            "stage": "P6_MINI_LEAGUE_PARTIAL_REFRESH",
            "status": "PASS",
            "required": True,
            "reason": None,
            "evidence": {
                "change_class": "MINI_LEAGUE_ONLY",
                "reused_layers": ["Stage2", "P1.7", "MC"],
                "recomputed_layers": [
                    "P1.8_MINI_LEAGUE",
                    "DEPENDENT_REPORT_SURFACES",
                    "QA",
                ],
                "football_math_recomputed": False,
                "second_optimizer_created": False,
            },
        }
    )
    execution_proof = dict(bundle.get("execution_proof") or {})
    execution_proof["stages"] = ledger
    execution_proof["warm_partial_refresh"] = {
        "change_class": "MINI_LEAGUE_ONLY",
        "status": "PASS",
        "stage2_reused": True,
        "p1_7_reused": True,
        "mc_reused": True,
        "p1_8_recomputed": True,
        "stability_recomputed": True,
        "football_math_recomputed": False,
        "affected_dependency_scope": "MINI_LEAGUE_ONLY",
    }

    source_fingerprints = dict(bundle.get("source_fingerprints") or {})
    source_fingerprints["mini_league_standings"] = _fingerprint(standings)
    source_fingerprints["mini_league_picks"] = _fingerprint(manager_picks)

    bundle.update(
        {
            "runner_status": "PASS",
            "stage_ledger": ledger,
            "section_manifest": section_manifest,
            "human_facing_manifest": human_manifest,
            "compute_contract": compute_contract,
            "pre_render_qa": pre_render_qa,
            "post_render_qa": post_render_qa,
            "human_facing_qa": {
                "status": "PASS",
                "failures": [],
            },
            "execution_proof": execution_proof,
            "report": new_report,
            "visible_body": body,
            "source_fingerprints": source_fingerprints,
        }
    )
    governance_out = dict(bundle.get("governance") or {})
    governance_out.update(
        {
            "p6_partial_refresh": "MINI_LEAGUE_ONLY",
            "p6_partial_refresh_reused_football_math": True,
            "qa_relaxed": False,
            "second_methodology_created": False,
        }
    )
    bundle["governance"] = governance_out

    warm.update(
        {
            "standings": standings,
            "manager_picks": manager_picks,
            "mini": mini,
            "mini_overlay": mini_overlay,
            "package_with_stage3": package_with_stage3,
        }
    )
    refreshed["bundle"] = bundle
    refreshed["execution_proof"] = execution_proof
    refreshed["warm_state"] = warm

    output_dir = Path(str(refreshed.get("output_dir") or ""))
    if not output_dir:
        raise IntegratedRunnerError("MINI_LEAGUE_ONLY output_dir is unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report_bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "execution_proof.json").write_text(
        json.dumps(
            execution_proof,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "report_body.md").write_text(body, encoding="utf-8")
    return refreshed


def run_deep(
    *,
    runtime_data_root: Path,
    report_slot: str,
    output_dir: Path,
    checkpoint_time: str | None = None,
    previous_visible_deep_dir: Path | None = None,
    private_data_root: Path | None = None,
    allow_legacy_private_sources: bool = True,
    require_private_personal: bool = False,
    scenario_overrides: Mapping[str | int, Mapping[str, Any]] | None = None,
    warm_state_out: Path | None = None,
) -> dict[str, Any]:
    ledger: list[dict[str, Any]] = []
    scenario_overrides = dict(scenario_overrides or {})
    stage2_cache_proof: dict[str, Any] = {}
    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    state = _read_json(STATE_PATH, {}) or {}
    previous_deep = _load_previous_visible_deep_baseline(
        previous_visible_deep_dir,
        current_report_slot=report_slot,
    )
    ledger.append(
        {
            "stage": "PREVIOUS_VALID_VISIBLE_DEEP_BASELINE",
            "status": (
                "PASS" if previous_deep.get("state") == "AVAILABLE" else "DEGRADED"
            ),
            "required": False,
            "reason": previous_deep.get("reason"),
            "evidence": {
                "state": previous_deep.get("state"),
                "report_slot": previous_deep.get(
                    "report_slot",
                    previous_deep.get("candidate_report_slot"),
                ),
                "source": previous_deep.get("source"),
                "validation_failures": previous_deep.get(
                    "validation_failures"
                ),
            },
        }
    )

    prefetch = _stage(
        ledger,
        "V6_REPORT_PREFETCH_BINDING",
        lambda: wait_for_prefetch_terminal(
            runtime_data_root,
            report_slot=report_slot,
            refresh_fn=lambda: _refresh_runtime_data_checkout(runtime_data_root),
        ),
        required=True,
    )
    if not prefetch:
        failure = (
            _stage_failure_reason(ledger, "V6_REPORT_PREFETCH_BINDING")
            or "same-occurrence prefetch did not become terminal"
        )
        raise IntegratedRunnerError("PREFETCH_NOT_TERMINAL: " + failure)

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
    set_piece_notes_evidence = _stage(
        ledger,
        "OFFICIAL_SET_PIECE_NOTES",
        lambda: _bound_set_piece_notes(
            runtime_data_root,
            prefetch=prefetch,
            report_slot=report_slot,
        ),
    ) or {"status": "UNAVAILABLE", "payload": None}
    set_piece_notes_payload = (
        set_piece_notes_evidence.get("payload")
        if set_piece_notes_evidence.get("status") == "AVAILABLE"
        else None
    )
    planning_gw = _planning_gw(bootstrap)
    personal_resolution = _stage(
        ledger,
        "PERSONAL_EVIDENCE_RECONCILIATION",
        lambda: _personal_evidence_resolution(
            runtime_data_root,
            state,
            planning_gw=planning_gw,
            private_data_root=private_data_root,
            allow_legacy_private_sources=allow_legacy_private_sources,
            require_private_personal=require_private_personal,
        ),
        required=True,
    )
    private_current_team = dict(
        (personal_resolution or {}).get("payload") or {}
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
        def _canonical_stage2_builder() -> dict[str, Any]:
            return build_player_projections(
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
                scenario_overrides=scenario_overrides,
            )

        def _stage2_projection_with_cache() -> dict[str, Any]:
            if scenario_overrides:
                started = time.perf_counter()
                projections_payload = _canonical_stage2_builder()
                proof = {
                    "schema": "P4_SCENARIO_OVERRIDE_BYPASS_V1",
                    "input_fingerprint": _fingerprint(
                        {"scenario_overrides": scenario_overrides}
                    ),
                    "cache_authoritative": False,
                    "mathematical_owner_changed": False,
                    "private_current15_in_key": False,
                    "status": "MISS",
                    "cache_hit": False,
                    "cache_miss": True,
                    "cache_write": False,
                    "cache_corrupt_reject": False,
                    "scenario_override_cache_bypass": True,
                    "load_or_build_seconds": round(
                        time.perf_counter() - started, 6
                    ),
                }
            else:
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
                    builder=_canonical_stage2_builder,
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
            lambda: attach_official_role_evidence(
                projections,
                bootstrap,
                set_piece_notes=set_piece_notes_payload,
            ),
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


    post_match_review: dict[str, Any] = {}
    s16b_context: dict[str, Any] = {}

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

    universe = _watchlist_candidate_universe(projections or {})
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

    s16b_context = resolve_s16b_context(
        report_slot=report_slot,
        report_mode="DEEP",
        fixtures=fixtures or [],
        player_match_rows=(foundation or {}).get("player_match_rows") or [],
        prior_delivery_state=previous_deep.get("s16b_delivery_state"),
    )
    # Same-occurrence scratch only. This is not an authority and is deleted
    # before serving publication; it lets fail-operational assembly preserve a
    # lifecycle decision already proven by this run.
    s16b_context["delivery_state_after"] = state_after_occurrence(
        s16b_context,
        occurrence_id=f"DEEP|{report_slot}",
        generated_at=datetime.now().astimezone().isoformat(),
        body_fingerprint=None,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / ".s16b_context.json").write_text(
        json.dumps(s16b_context, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    ledger.append(
        {
            "stage": "S16B_LIFECYCLE",
            "status": "PASS",
            "required": True,
            "reason": s16b_context.get("due_reason"),
            "evidence": {
                "completed_gw": s16b_context.get("completed_gw"),
                "s16b_due": s16b_context.get("s16b_due"),
                "expected_section_count": s16b_context.get(
                    "expected_section_count"
                ),
                "gw_completion": s16b_context.get("gw_completion"),
                "post_match_evidence": s16b_context.get(
                    "post_match_evidence"
                ),
            },
        }
    )
    if s16b_context.get("s16b_due") is True:
        post_match_review = _stage(
            ledger,
            "S16B_POST_MATCH_COMPLETED_GW",
            lambda: _post_match_review(
                projections=projections,
                foundation=foundation,
                fixtures=fixtures or [],
                bootstrap=bootstrap,
                owned_ids=owned_ids,
                completed_gw=int(s16b_context.get("completed_gw") or 0),
                watchlist=watchlist,
                previous_report=previous_deep.get("report"),
            ),
            required=True,
        ) or {}
        expected_fixtures = int(
            (s16b_context.get("gw_completion") or {}).get(
                "expected_fixture_count"
            )
            or 0
        )
        if (
            int(post_match_review.get("fixtures_expected") or -1)
            != expected_fixtures
            or int(post_match_review.get("fixtures_reviewed") or -1)
            != expected_fixtures
            or int(post_match_review.get("unique_fixture_count") or -1)
            != expected_fixtures
            or int(post_match_review.get("duplicate_fixture_count") or -1)
            != 0
            or len(
                (
                    post_match_review.get("after_gw_reassessment") or {}
                ).get("owned15_review")
                or []
            )
            != 15
        ):
            raise IntegratedRunnerError(
                "S16B_DUE_CONTENT_INCOMPLETE: fixture/exact15 contract failed"
            )
        s16b_context["post_match_review"] = post_match_review
        (output_dir / ".s16b_context.json").write_text(
            json.dumps(s16b_context, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    else:
        _skip_stage(
            ledger,
            "S16B_POST_MATCH_COMPLETED_GW",
            str(s16b_context.get("due_reason") or "S16B_NOT_DUE"),
            required=False,
        )

    calendar_elements = set(owned_ids)
    calendar_elements.update(
        int(row.get("element_id") or 0)
        for row in (watchlist or {}).get("rows") or []
        if isinstance(row, Mapping) and int(row.get("element_id") or 0) > 0
    )
    s05_inputs = _stage(
        ledger,
        "REPORT_TIME_S05_BINDING",
        lambda: build_report_time_s05_inputs(
            bootstrap=bootstrap,
            fixtures=fixtures or [],
            planning_gw=planning_gw,
            report_slot=report_slot,
            output_dir=output_dir,
            runtime_data_root=runtime_data_root,
            private_data_root=private_data_root,
        ),
    ) or {
        "verified_schedule_events": [],
        "non_pl_schedule_authority": False,
        "weather_rows": [],
        "weather_forecast_horizon_hours": 168.0,
        "weather_status": "UNAVAILABLE",
        "club_schedule": {"status": "UNAVAILABLE"},
        "player_observation": {"status": "UNAVAILABLE"},
    }
    calendar_context = build_calendar_workload_context(
        planning_gw=planning_gw,
        pl_fixtures=fixtures or [],
        team_ids=[
            int(row.get("id"))
            for row in (bootstrap or {}).get("teams") or []
            if isinstance(row, Mapping) and row.get("id") is not None
        ],
        relevant_players=_calendar_relevant_players(
            projections,
            planning_gw=planning_gw,
            element_ids=calendar_elements,
        ),
        verified_schedule_events=(
            s05_inputs.get("verified_schedule_events") or []
        ),
        non_pl_schedule_authority=(
            s05_inputs.get("non_pl_schedule_authority") is True
        ),
        report_timestamp=report_slot,
        weather_rows=s05_inputs.get("weather_rows") or [],
        weather_forecast_horizon_hours=s05_inputs.get(
            "weather_forecast_horizon_hours"
        ),
    )
    calendar_context["competition_coverage"].update(
        {
            "club_schedule_status": (
                (s05_inputs.get("club_schedule") or {}).get("status")
            ),
            "player_observation_status": (
                (s05_inputs.get("player_observation") or {}).get("status")
            ),
            "weather_binding_status": s05_inputs.get("weather_status"),
        }
    )
    bgw_context = _bgw_propagation_context(
        calendar_context,
        owned_ids=owned_ids,
        lineup=lineup,
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
    stage3_guard_checks = {
        "PACKAGE_SEARCH_PRESENT": bool(package_search_result),
        "PACKAGE_UTILITY_PRESENT": bool(package_utility),
        "MATERIAL_MC_ROUTES_PRESENT": bool(material_mc_routes),
        "MONTE_CARLO_PRESENT": bool(monte_carlo),
        "STAGE3_DECISION_PRESENT": bool(stage3_decision),
        "PACKAGE_WITH_STAGE3_PRESENT": bool(package_with_stage3),
        "MINI_OVERLAY_PRESENT": bool(mini_overlay),
        "MC_EXECUTED": bool(
            monte_carlo and monte_carlo.get("execution_state") == "EXECUTED"
        ),
        "MC_CANONICAL_PASS": bool(
            monte_carlo and monte_carlo.get("canonical_pass") is True
        ),
        "MC_PATHS_500K": bool(
            monte_carlo
            and int(monte_carlo.get("actual_paths") or 0) >= 500_000
        ),
        "MC_CONVERGENCE_PASS": bool(
            monte_carlo
            and (monte_carlo.get("convergence_evidence") or {}).get("status")
            == "PASS"
        ),
        "MC_MATCH_STATE_INVARIANTS_PASS": bool(
            monte_carlo
            and (
                (monte_carlo.get("sampling_diagnostics") or {}).get(
                    "match_state_invariants"
                )
                or {}
            ).get("status")
            == "PASS"
        ),
        "PACKAGE_SEARCH_AUTHORITY_FULL": bool(
            package_search_result
            and package_search_result.get("search_authority") == "FULL"
        ),
        "PACKAGE_SEARCH_COVERAGE_COMPLETE": bool(
            package_search_result
            and package_search_result.get("coverage", {}).get(
                "coverage_complete"
            ) is True
        ),
        "PACKAGE_UTILITY_AUTHORITY_FULL": bool(
            package_utility
            and package_utility.get("search_authority")
            == "FULL_DIRECT_MATERIAL_FUNDED"
        ),
        "NO_GLOBAL_TWO_TRANSFER_EXHAUSTIVE_CLAIM": bool(
            package_utility
            and (package_utility.get("search_scope") or {}).get(
                "global_two_transfer_exhaustive_claim"
            ) is False
        ),
        "DIRECT_SEARCH_COMPLETE": bool(
            package_utility
            and (
                (package_utility.get("search_scope") or {}).get("direct")
                or {}
            ).get("global_direct_complete") is True
        ),
        "FUNDED_AUTHORITY_MATERIAL_FUNDED": bool(
            package_utility
            and (
                (package_utility.get("search_scope") or {}).get(
                    "funded_two_transfer"
                )
                or {}
            ).get("authority") == "MATERIAL_FUNDED"
        ),
        "STAGE2_LINEAGE_COMPLETE": bool(
            canonical_bundle.get("stage2_lineage_complete_players")
            == canonical_bundle.get("complete_players")
        ),
        "WATCHLIST_COMPLETE": bool(
            str((watchlist or {}).get("state") or "").upper() == "COMPLETE"
        ),
        "MINI_COVERAGE_FULL": bool(
            str((mini or {}).get("coverage_state") or "").upper() == "FULL"
        ),
        "REQUIRED_STAGES_PASS": bool(
            all(
                stage_status.get(name) == "PASS"
                for name in stage3_required_stage_names
            )
        ),
    }
    stage3_guard_failures = [
        name for name, passed in stage3_guard_checks.items() if not passed
    ]
    stage3_internal_pass = not stage3_guard_failures
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

    formation_strategy = _formation_mini_league_strategy(
        lineup=lineup,
        mini=mini,
        mini_overlay=mini_overlay,
        projections=projections,
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
        calendar_context=calendar_context,
    )
    all15_rows = _enrich_all15_rows(
        all15=all15,
        projections=projections,
        predictor=predictor,
        owned=owned,
        bootstrap=bootstrap,
        mini=mini,
        mini_detail=mini_deep_detail,
        calendar_context=calendar_context,
    )
    xi_battles = _xi_battles(
        lineup=lineup,
        projections=projections,
        mini=mini,
        mini_detail=mini_deep_detail,
        calendar_context=calendar_context,
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
    staging = {
        **staging,
        "bgw_context": dict(bgw_context),
        "bgw_reoptimization_trigger": bool(bgw_context.get("active")),
    }
    captain_surface = _captain_decision_surface(
        owned=owned,
        lineup=lineup,
        lineup_state=lineup_state,
        mini_detail=mini_deep_detail,
    )
    chip_state = (finance or {}).get("chips")
    chip_available = (
        chip_state not in (None, {}, [])
        and (finance or {}).get("chips_status") == "AVAILABLE"
    )
    final_judgement = _final_judgement_surface(
        operational_action=operational_action,
        stage3_decision=stage3_decision,
        stage3_visible=stage3_visible,
        lineup=lineup,
        captain_surface=captain_surface,
        mini_detail=mini_deep_detail,
        staging=staging,
        chip_state=chip_state if chip_available else None,
    )
    final_judgement["bgw_context"] = dict(bgw_context)
    final_judgement["bgw_reconciled"] = True
    decision_dashboard = _decision_dashboard(
        operational_action=operational_action,
        planning_gw=planning_gw,
        stage3_decision=stage3_decision,
        lineup_state=lineup_state,
        lineup=lineup,
        captain_surface=captain_surface,
        chip_available=chip_available,
        price_radar=price_radar,
        auth_state=str(private_current_team.get("auth_state") or "UNAVAILABLE"),
        finance=finance,
    )
    current_decision_snapshot = _decision_snapshot_from_current(
        operational_action=operational_action,
        final_judgement=final_judgement,
        all15_rows=all15_rows,
        mini_detail=mini_deep_detail,
        finance_available=_execution_finance_available(finance),
        chip_state=chip_state,
        chip_available=chip_available,
    )
    if previous_deep.get("state") == "AVAILABLE":
        decision_delta = _decision_delta_surface(
            previous_snapshot=_decision_snapshot_from_report(
                previous_deep.get("report") or {}
            ),
            current_snapshot=current_decision_snapshot,
            previous_report_slot=str(previous_deep.get("report_slot") or ""),
            evidence_time=report_slot,
        )
        decision_delta_state = "COMPLETE"
        decision_delta_reason = None
    else:
        decision_delta = {
            "baseline_state": "UNAVAILABLE",
            "baseline_requirement": "PREVIOUS_VALID_VISIBLE_DEEP",
            "rows": [],
            "summary": (
                "BASELINE UNAVAILABLE — no prior DEEP artifact survived current "
                "human-facing semantic validation; no decision delta is inferred."
            ),
            "baseline_reason": previous_deep.get("reason"),
            "candidate_report_slot": previous_deep.get("candidate_report_slot"),
            "validation_failures": previous_deep.get("validation_failures"),
            "current_snapshot": current_decision_snapshot,
            "material_only": True,
            "no_recomputation_no_numeric_delta": True,
        }
        decision_delta_state = "DEGRADED"
        decision_delta_reason = (
            "previous valid visible DEEP baseline is unavailable under the "
            "current semantic contract"
        )

    our_news_ids = [
        int(row.get("element_id") or row.get("element") or 0)
        for row in owned
        if isinstance(row, Mapping)
        and int(row.get("element_id") or row.get("element") or 0) > 0
    ]
    watchlist_news_ids = [
        int(row.get("element_id") or row.get("element") or 0)
        for row in (watchlist or {}).get("rows") or []
        if isinstance(row, Mapping)
        and int(row.get("element_id") or row.get("element") or 0) > 0
    ]
    official_material_news = build_official_fpl_material_news(
        bootstrap,
        our_element_ids=our_news_ids,
        watchlist_element_ids=watchlist_news_ids,
        report_timestamp=report_slot,
        previous_report_timestamp=(
            str(previous_deep.get("report_slot") or "") or None
        ),
    )
    report_time_evidence = _read_json(
        runtime_data_root / "data/report_time_evidence.json",
        {},
    ) or {}
    report_time_material_news = build_report_time_material_news(
        report_time_evidence,
        bootstrap,
        our_element_ids=our_news_ids,
        watchlist_element_ids=watchlist_news_ids,
        report_timestamp=report_slot,
    )
    material_news: list[dict[str, Any]] = []
    material_news_seen: set[tuple[str, str, str]] = set()
    for news_item in [*official_material_news, *report_time_material_news]:
        key = (
            str(news_item.get("source_name") or ""),
            str(news_item.get("subject") or ""),
            str(news_item.get("summary") or ""),
        )
        if key in material_news_seen:
            continue
        material_news_seen.add(key)
        material_news.append(news_item)
    news_groups = {
        group_name: [
            row for row in material_news
            if str(row.get("audience") or "OTHER MATERIAL").upper() == group_name
        ]
        for group_name in (
            "OUR15",
            "WATCHLIST / TARGETS",
            "TEAM / TACTICAL",
            "OTHER MATERIAL",
        )
    }
    model_developments = (
        [
            {
                "classification": "NEW",
                "source_class": "MODEL_SIGNAL",
                "scope": "FULL_ELIGIBLE_UNIVERSE",
                "summary": (
                    f"{(post_match_review.get('full_universe_scan') or {}).get('material_count')} "
                    "material GW1→Now trajectories are present in the bound model scan"
                ),
                "evidence_time": report_slot,
                "news_observation_is_model_update": False,
                "act_authority": False,
            }
        ]
        if (post_match_review.get("full_universe_scan") or {}).get("material_count")
        else []
    )

    evidence_quality = _evidence_quality_surface(
        official=official,
        personal_resolution=personal_resolution,
        finance=finance,
        chip_available=chip_available,
        calendar_context=calendar_context,
        projections=projections,
        post_match_review=post_match_review,
        rise=rise,
        mini=mini,
        private_auth_state=str(
            private_current_team.get("auth_state") or "UNAVAILABLE"
        ),
        report_slot=report_slot,
    )
    action_board = _action_board_surface(
        dashboard=decision_dashboard,
        stage3_decision=stage3_decision,
        stage3_visible=stage3_visible,
        all15_rows=all15_rows,
    )
    action_board["captain_decision"] = {
        "captain": dict(captain_surface.get("captain") or {}),
        "vice_captain": dict(captain_surface.get("vice_captain") or {}),
        "football_leader": dict(captain_surface.get("football_leader") or {}),
        "frontier_classification": captain_surface.get(
            "football_frontier_classification"
        ),
        "risk_posture": captain_surface.get("risk_posture"),
        "source": "S08_CANONICAL_CAPTAIN_DECISION",
    }

    sections = {
        "S01": _section(
            "COMPLETE",
            {
                "decision_dashboard": decision_dashboard,
                "operational_state": operational_action,
                "planning_gw": planning_gw,
                "primary_decision": (
                    (stage3_decision or {}).get("selected_route_id") or "HOLD"
                ),
                "reason": decision_dashboard.get("PRIMARY_REASON"),
                "key_decision_driver": decision_dashboard.get("KEY_DRIVER"),
                "current_blockers": decision_dashboard.get("CURRENT_BLOCKERS"),
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
                "current15_authority": {
                    "source_class": (personal_resolution or {}).get("source_class"),
                    "source": (personal_resolution or {}).get("source"),
                    "observed_at": (personal_resolution or {}).get("observed_at"),
                    "applicable_gw": (personal_resolution or {}).get("gw"),
                    "resolution_status": (personal_resolution or {}).get("resolution_status"),
                    "auth_state": str(
                        private_current_team.get("auth_state") or "UNAVAILABLE"
                    ).upper(),
                    "finance_availability": (
                        "AVAILABLE"
                        if _execution_finance_available(finance)
                        else "DEGRADED"
                    ),
                    "stale": (personal_resolution or {}).get("stale"),
                },
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
            decision_delta_state,
            {
                "decision_delta": decision_delta,
            },
            decision_delta_reason,
        ),
        "S04": _section(
            "COMPLETE",
            {
                "news_summary": (
                    "MATERIAL NEWS PRESENT"
                    if material_news
                    else "NO MATERIAL NEW EXTERNAL NEWS"
                ),
                "material_news": material_news,
                "news_groups": news_groups,
                "model_developments": model_developments,
                "decision_consequence": {
                    "transfer_state": decision_dashboard.get("TRANSFER"),
                    "xi_state": decision_dashboard.get("XI"),
                    "captain_state": decision_dashboard.get("CAPTAIN"),
                    "price_state": decision_dashboard.get("PRICE"),
                    "news_self_authorizes_act": False,
                    "news_observation_is_model_update": False,
                    "model_numbers_mutated_here": False,
                    "optimizer_authority_remains_s14": True,
                },
                "source_policy": {
                    "allowed_source_classes": [
                        "OFFICIAL",
                        "RELIABLE_REPORT",
                        "MULTIPLE_CREDIBLE_REPORTS",
                        "RUMOR / UNVERIFIED",
                        "MODEL_SIGNAL",
                        "INFERENCE",
                    ],
                    "rumor_is_fact": False,
                    "rumor_may_authorize_act": False,
                    "news_observation_equals_model_update": False,
                },
                "changes": model_developments,
                "decision_change_sources": {
                    "FACTUAL_EVENT": "official/report-time injury, lineup, fixture or availability evidence",
                    "MODEL_RECOMPUTATION": "P1.x occurrence execution",
                    "STAGEC_UNIVERSE_SIGNAL": "full-universe breakout/regression scanner",
                    "POST_MATCH_MATERIALITY": "GW1→Now contextual trajectory",
                    "PRICE_EVENT": "official/predictor price evidence",
                    "MINI_LEAGUE_EVENT": "standings/submitted-picks evidence",
                },
                **(
                    {"stagec_universe_intelligence": stagec_surface}
                    if stagec_surface is not None
                    else {}
                ),
            },
        ),
        "S05": _section(
            str(calendar_context.get("state") or "DEGRADED"),
            {
                **calendar_context,
                "opponent_strength": strength or {},
                "fixture_swing": "MODEL_DERIVED_WHERE_SUPPORTABLE",
            },
            calendar_context.get("degradation_reason"),
        ),
        "S06": _section(
            lineup_state,
            {
                **_lineup_content(lineup),
                "bgw_context": dict(bgw_context),
                "bgw_lineup_review_required": bool(bgw_context.get("active")),
            },
            lineup_reason,
        ),
        "S06B": _section(
            lineup_state,
            _xi_battle_presentation(
                battles=xi_battles,
                battle_summary=(lineup or {}).get("main_starting_xi_battle"),
            ),
            lineup_reason,
        ),
        "S07": _section(
            lineup_state,
            _lineup_risk_presentation(
                lineup=lineup,
                battles=xi_battles,
            ),
            lineup_reason,
        ),
        "S08": _section(
            lineup_state,
            captain_surface,
            lineup_reason,
        ),
        "S09": _section(
            "COMPLETE" if chip_available else "DEGRADED",
            {
                "chip": chip_state if chip_available else "UNAVAILABLE",
                "chip_ledger": chip_state if chip_available else "UNAVAILABLE",
                "chip_ledger_authority": "PRIVATE_PERSONAL_PLANE" if chip_available else "UNAVAILABLE",
                "remaining_chip_set_required": True,
                "free_hit_optimization_required_when_fh_only": True,
                "considered_now": False,
                "horizon": "REASSESS EACH DEADLINE",
                "trigger": "material chip-specific fixture/ceiling edge",
                "hold_reason": "No chip action is created without current authenticated chip state and a supportable edge.",
                "bgw_context": dict(bgw_context),
                "bgw_chip_review_required": bool(bgw_context.get("active")),
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
                **(watchlist or {"rows": []}),
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
                "selected_route_id": (stage3_decision or {}).get("selected_route_id") or "HOLD",
                "package_routes": stage3_visible.get("package_routes", []),
                "frontier": stage3_visible.get("frontier", []),
                **stage3_visible,
                "bgw_context": dict(bgw_context),
                "bgw_frontier_review_required": bool(bgw_context.get("active")),
                "bgw_is_context_not_second_optimizer": True,
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
                "evidence_quality": evidence_quality,
                "model_execution": {
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
                },
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
        **(
            {
                "S16B": _section(
                    "COMPLETE",
                    post_match_review,
                    None,
                    available_count=post_match_review.get("fixtures_reviewed"),
                    expected_count=post_match_review.get("fixtures_expected"),
                )
            }
            if s16b_context.get("s16b_due") is True
            else {}
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
                        if _execution_finance_available(finance)
                        else "DEGRADED"
                    ),
                    "fixture_data": "HEALTHY" if fixtures is not None else "UNAVAILABLE",
                    "price_predictor": (rise or {}).get("predictor_health") or "UNAVAILABLE",
                    "price_predictor_freshness": next(
                        (
                            str(row.get("freshness") or "UNKNOWN").upper()
                            for row in (rise or {}).get("rows") or []
                            if isinstance(row, Mapping)
                        ),
                        "UNAVAILABLE",
                    ),
                    "price_predictor_source_age_minutes": next(
                        (
                            row.get("source_age_minutes")
                            for row in (rise or {}).get("rows") or []
                            if isinstance(row, Mapping)
                        ),
                        None,
                    ),
                    "tactical_statistical_data": "HEALTHY" if foundation else "UNAVAILABLE",
                    "mini_league": (mini or {}).get("coverage_state") or "UNAVAILABLE",
                    "weather": (
                        "REPORT_TIME_BOUND"
                        if _weather_contract_state_from_calendar(calendar_context)
                        == "REPORT_TIME_BOUND"
                        else (
                            "OUTSIDE_RELIABLE_FORECAST_HORIZON"
                            if all(
                                "OUTSIDE RELIABLE FORECAST HORIZON"
                                in str(row.get("state") or "")
                                for row in calendar_context.get("weather") or []
                                if isinstance(row, Mapping)
                            )
                            and bool(calendar_context.get("weather"))
                            else "DEGRADED_OR_UNAVAILABLE"
                        )
                    ),
                },
                "auth_authority": {
                    "field": "data/v6/personal/current_team.json:auth_state",
                    "value": str(private_current_team.get("auth_state") or "UNAVAILABLE").upper(),
                    "identity_resolution_is_not_auth_authority": True,
                },
                "lineage": {
                    "report_mode": "DEEP",
                    "logical_slot": report_slot,
                    "exact_occurrence_binding": prefetch.get("same_occurrence_bound") is True,
                    "serving_source": "canonical occurrence-bound report bundle",
                    "substituted_slot": False,
                    "v6_factual_plane_mutated": False,
                    "post_match_source": "V12 contextual dynamics over read-only V6 normalized match rows",
                },
            },
        ),
        "S18": _section(
            "COMPLETE",
            {
                "action_board": action_board,
                "NOW": {
                    row.get("axis"): row.get("NOW")
                    for row in action_board.get("axes") or []
                    if isinstance(row, Mapping)
                },
                "NEXT": {
                    row.get("axis"): row.get("NEXT")
                    for row in action_board.get("axes") or []
                    if isinstance(row, Mapping)
                },
                "TRIGGER TO ACT": {
                    row.get("axis"): row.get("TRIGGER TO ACT")
                    for row in action_board.get("axes") or []
                    if isinstance(row, Mapping)
                },
                "LATEST SAFE DECISION POINT": {
                    row.get("axis"): row.get("LATEST SAFE DECISION POINT")
                    for row in action_board.get("axes") or []
                    if isinstance(row, Mapping)
                },
                "COST OF WAITING": {
                    row.get("axis"): row.get("COST OF WAITING")
                    for row in action_board.get("axes") or []
                    if isinstance(row, Mapping)
                },
                "ABORT / REVERSAL": {
                    row.get("axis"): row.get("ABORT / REVERSAL")
                    for row in action_board.get("axes") or []
                    if isinstance(row, Mapping)
                },
                "BEST ALTERNATIVE": action_board.get("best_alternative"),
            },
        ),
        "S19": _section(
            "COMPLETE",
            {
                "final_judgement": final_judgement,
            },
        ),
    }

    # Bind decision-critical visible sections to the exact producer payload
    # before rendering. Renderer never manufactures this metadata.
    producer_by_section = {
        "S01": "STAGE3_DECISION+S08+S09+S10+S17",
        "S02": "CURRENT15_RESOLUTION+P1_1_P1_3+S05+S15B",
        "S04": "BOUND_OCCURRENCE_MATERIALITY+STAGEC",
        "S06": "P1_7_LINEUP",
        "S07": "P1_7_XI_BATTLE+P1_1+S05+S15B",
        "S08": "P1_7_LEGALITY+P1_3B_CAPTAIN_FRONTIER+P1_8_COMPETITIVE_TIEBREAK",
        "S10": "OFFICIAL_FPL_PRICE_FACT+PRICE_PREDICTOR",
        "S11": "WATCHLIST20",
        "S12": "OFFICIAL_FPL_PREDICTOR_RISE20",
        "S13": "OFFICIAL_FPL_PREDICTOR_FALL20",
        "S14": "P1_2_PACKAGE_UTILITY+P1_4_MONTE_CARLO+P1_8_MINI_LEAGUE_OVERLAY",
        "S15": "BOUND_SOURCE_HEALTH+MODEL_EXECUTION",
        "S15B": "P1_8_MINI_LEAGUE_SNAPSHOT+P1_8_MINI_LEAGUE_OVERLAY",
        "S16": "P1_1_P1_3_FULL_UNIVERSE+P1_6_TACTICAL_ROLE",
        "S16B": "POST_MATCH_DEEP_DETAILS",
        "S18": "S01+S08+S10+S14+TEAM_NEWS",
        "S19": "S08_CAPTAIN_FRONTIER+S15B_MINI_LEAGUE_RECONCILIATION",
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

    s08_content = dict((sections.get("S08") or {}).get("content") or {})
    s18_content = dict((sections.get("S18") or {}).get("content") or {})
    s19_content = dict((sections.get("S19") or {}).get("content") or {})
    s18_cap = dict(
        (s18_content.get("action_board") or {}).get("captain_decision") or {}
    )
    s19_judgement = dict(s19_content.get("final_judgement") or {})
    s08_c = _surface_element(s08_content.get("captain"))
    s08_v = _surface_element(s08_content.get("vice_captain"))
    s18_c = _surface_element(s18_cap.get("captain"))
    s18_v = _surface_element(s18_cap.get("vice_captain"))
    s19_c = _surface_element(s19_judgement.get("final_captain"))
    s19_v = _surface_element(s19_judgement.get("vice"))
    captain_consistency_required = bool(
        str(lineup_state or "").upper() == "COMPLETE"
        and all(
            str((sections.get(sid) or {}).get("state") or "").upper() == "COMPLETE"
            for sid in ("S08", "S18", "S19")
        )
    )
    if captain_consistency_required and not (
        s08_c is not None
        and s08_v is not None
        and s08_c == s18_c == s19_c
        and s08_v == s18_v == s19_v
        and s08_c in {
            _surface_element(row)
            for row in (lineup or {}).get("starting_xi") or []
        }
        and s08_v in {
            _surface_element(row)
            for row in (lineup or {}).get("starting_xi") or []
        }
        and s08_c != s08_v
    ):
        raise IntegratedRunnerError(
            "CAPTAIN_VICE_CANONICAL_CONSISTENCY_FAIL:S08_S18_S19"
        )

    math_stack = build_visible_mathematical_decision_stack(
        stage3_math_proof
    )
    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads=sections,
        s16b_due=s16b_context.get("s16b_due") is True,
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
    weather_contract_state = _weather_contract_state_from_calendar(
        calendar_context
    )
    pre_render_qa = validate_pre_render_qa(
        compute_contract=compute_contract,
        section_manifest=section_manifest,
        mini_league_denominator_complete=mini_complete,
        report_mode="DEEP",
        weather_contract_state=weather_contract_state,
    )
    body = render_deep_text(report)
    final_delivery_barrier = validate_final_delivery_barrier(
        report_mode="DEEP",
        report=report,
        body=body,
    )
    human_failures = list(dict.fromkeys(
        validate_human_facing_body(body)
        + validate_deep_human_facing_manifest(human_manifest)
        + list(final_delivery_barrier.get("failures") or [])
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
        rendered_weather_contract_state=weather_contract_state,
        truncated=False,
    )
    contract = canonical_mode_contract(
        canonical,
        "DEEP",
        s16b_due=s16b_context.get("s16b_due") is True,
    )
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
                "stage": "FINAL_DELIVERY_BARRIER",
                "status": final_delivery_barrier.get("status"),
                "required": True,
                "reason": ";".join(final_delivery_barrier.get("failures") or []) or None,
            },
            {
                "stage": "HUMAN_FACING_QA",
                "status": "PASS" if not human_failures else "FAILED",
                "required": True,
                "reason": ";".join(human_failures) or None,
            },
        ]
    )

    s16b_delivery_state = state_after_occurrence(
        s16b_context,
        occurrence_id=f"DEEP|{report_slot}",
        generated_at=datetime.now().astimezone().isoformat(),
        body_fingerprint=(
            hashlib.sha256(body.encode("utf-8")).hexdigest()
            if s16b_context.get("s16b_due") is True
            else None
        ),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    execution_proof = {
        "schema_version": 2,
        "runner": "V12_INTEGRATED_REPORT_RUNNER",
        "cpu_count": max(1, int(os.cpu_count() or 1)),
        "report_slot": report_slot,
        "report_mode": "DEEP",
        "planning_gw": planning_gw,
        "s16b_due": s16b_context.get("s16b_due") is True,
        "s16b_completed_gw": s16b_context.get("completed_gw"),
        "s16b_due_reason": s16b_context.get("due_reason"),
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
        "final_delivery_barrier": deepcopy(final_delivery_barrier),
        "final_delivery_barrier_status": final_delivery_barrier.get("status"),
        "stage3_internal_pass": stage3_internal_pass,
        "stage3_guard_failures": list(stage3_guard_failures),
        "stage3_action": operational_action,
        "stage3_required_stages": sorted(stage3_required_stage_names),
        "stage2_derived_cache": deepcopy(stage2_cache_proof),
        "p4_scenario_override": {
            "applied": bool(scenario_overrides),
            "override_count": len(scenario_overrides),
            "payload_fingerprint": (
                _fingerprint(scenario_overrides) if scenario_overrides else None
            ),
            "stage2_cache_bypassed": bool(scenario_overrides),
        },
        "p1_7_execution": {
            "lineup": next(
                (
                    deepcopy(row)
                    for row in ledger
                    if str(row.get("stage") or "") == "P1_7_LINEUP"
                ),
                None,
            ),
            "direct_package": deepcopy(
                ((direct_package_utility or {}).get("governance") or {}).get(
                    "p1_7_execution_proof"
                )
            ),
            "funded_package": deepcopy(
                ((funded_package_utility or {}).get("governance") or {}).get(
                    "p1_7_execution_proof"
                )
            ),
            "timing_semantics": (
                "EXACT_OWNER_WALL_TIMES_ONLY; broad package-utility wall time "
                "is not P1.7 timing authority"
            ),
        },
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
        "s16b_due": s16b_context.get("s16b_due") is True,
        "s16b_context": s16b_context,
        "s16b_delivery_state": s16b_delivery_state,
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
            "p4_scenario_override_private_only": bool(scenario_overrides),
            "p4_scenario_override_posthoc_xpts_mutation": False,
            "stage3_requires_internal_producers_before_runner_pass": True,
        },
    }
    if warm_state_out is not None:
        warm_state = {
            "schema": "FPL_MASTER_V12_PRIVATE_WARM_STATE_V1",
            "private_only": True,
            "report_slot": report_slot,
            "planning_gw": planning_gw,
            "projections": projections,
            "owned": owned,
            "all15": all15,
            "lineup": lineup,
            "predictor": predictor,
            "rise": rise,
            "fall": fall,
            "price_radar": price_radar,
            "watchlist": watchlist,
            "standings": standings,
            "manager_picks": manager_picks,
            "mini": mini,
            "calendar_context": calendar_context,
            "bgw_context": bgw_context,
            "canonical_universe": canonical_bundle,
            "finance": finance,
            "package_search_result": package_search_result,
            "direct_package_utility": direct_package_utility,
            "funding_leg_selection": funding_leg_selection,
            "funded_search_result": funded_search_result,
            "funded_package_utility": funded_package_utility,
            "package_utility": package_utility,
            "material_mc_routes": material_mc_routes,
            "monte_carlo": monte_carlo,
            "stage3_decision": stage3_decision,
            "package_with_stage3": package_with_stage3,
            "mini_overlay": mini_overlay,
        }
        warm_state_out.parent.mkdir(parents=True, exist_ok=True)
        warm_state_out.write_text(
            json.dumps(
                warm_state,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )

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
    parser.add_argument("--previous-visible-deep-dir", default=None)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--private-data-root", default=None)
    parser.add_argument(
        "--disable-legacy-private-sources",
        action="store_true",
        help="Do not read personal current-team/manual state from public repo surfaces.",
    )
    parser.add_argument(
        "--require-private-personal",
        action="store_true",
        help="Fail closed when the private personal plane is unavailable.",
    )
    parser.add_argument(
        "--scenario-overrides-file",
        default=None,
        help="Private controlled P4 typed availability override JSON.",
    )
    parser.add_argument(
        "--warm-state-out",
        default=None,
        help="Ephemeral private warm-state output; never a public artifact.",
    )
    args = parser.parse_args()
    mode = str(args.report_mode).upper()
    if mode not in SUPPORTED_MODES:
        raise IntegratedRunnerError(
            f"integrated runner supports {sorted(SUPPORTED_MODES)}; got {mode}"
        )
    scenario_overrides = {}
    if args.warm_state_out and not args.private_data_root:
        raise IntegratedRunnerError(
            "private warm state requires an explicit private data plane"
        )
    if args.scenario_overrides_file:
        if mode != "DEEP":
            raise IntegratedRunnerError("P4 scenario overrides require DEEP mode")
        if not args.private_data_root:
            raise IntegratedRunnerError(
                "P4 scenario overrides require an explicit private data plane"
            )
        raw_overrides = _read_json(Path(args.scenario_overrides_file), None)
        if not isinstance(raw_overrides, dict):
            raise IntegratedRunnerError("P4 scenario override file must be a JSON object")
        scenario_overrides = raw_overrides

    if mode == "PRICE":
        bundle = run_price_occurrence(
            runtime_data_root=Path(args.runtime_data_root),
            canonical_path=CANONICAL_PATH,
            state_path=STATE_PATH,
            report_slot=args.report_slot,
            output_dir=Path(args.output_dir),
        )
    else:
        runtime_root = Path(args.runtime_data_root)
        output_dir = Path(args.output_dir)
        previous_dir = (
            Path(args.previous_visible_deep_dir)
            if args.previous_visible_deep_dir
            else None
        )
        try:
            bundle = run_deep(
                runtime_data_root=runtime_root,
                report_slot=args.report_slot,
                output_dir=output_dir,
                checkpoint_time=args.checkpoint_time,
                previous_visible_deep_dir=previous_dir,
                private_data_root=(
                    Path(args.private_data_root)
                    if args.private_data_root
                    else None
                ),
                allow_legacy_private_sources=not args.disable_legacy_private_sources,
                require_private_personal=bool(args.require_private_personal),
                scenario_overrides=scenario_overrides,
                warm_state_out=(
                    Path(args.warm_state_out)
                    if args.warm_state_out
                    else None
                ),
            )
        except Exception as exc:
            message = str(exc)
            root_failure = (
                "PREFETCH_NOT_TERMINAL"
                if "PREFETCH_NOT_TERMINAL" in message
                or "same-occurrence" in message
                else f"ANALYTICS_PIPELINE_FAILURE:{type(exc).__name__}"
            )
            print(
                "[V12_DELIVERY] DEGRADED "
                f"root_failure={root_failure} error_class={type(exc).__name__}",
                flush=True,
            )
            scratch_path = output_dir / ".s16b_context.json"
            degraded_s16b_context = _read_json(scratch_path, {}) or {}
            bundle = assemble_degraded_deep_report(
                runtime_root=runtime_root,
                report_slot=args.report_slot,
                output_dir=output_dir,
                root_failure=root_failure,
                previous_visible_deep_dir=previous_dir,
                s16b_context=degraded_s16b_context,
            )
        scratch_path = output_dir / ".s16b_context.json"
        if scratch_path.exists():
            scratch_path.unlink()
        write_serving_artifacts(bundle=bundle, output_dir=output_dir)
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
