Warning: truncated output (original token count: 91666)
Total output lines: 9683

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
from src.engines.v12_report_freshness_provenance import attach_report_provenance
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
from src.engines.v12_s05_binding import (
    build_fixture_display_rows,
    build_report_time_s05_inputs,
)
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
from src.engines.v12_injury_availability import (
    build_availability_evidence_by_player,
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
        availability_evidence = dict(
            player.get("availability_evidence") or {}
        )
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
                "gw_availability": availability_evidence.get(
                    "gw_availability", "UNKNOWN"
                ),
                "gw_availability_confidence": availability_evidence.get(
                    "gw_availability_confidence", "LOW"
                ),
                "availability_derivation_reason": availability_evidence.get(
                    "availability_derivation_reason",
                    "NO_NORMALIZED_EVIDENCE_BOUND",
                ),
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
                "voi": decision.get("value_of_informa…51666 tokens truncated…      evaluated_universe=universe,
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
    calendar_context["fixtures_display"] = build_fixture_display_rows(
        bootstrap=bootstrap,
        fixtures=fixtures or [],
        weather_rows=s05_inputs.get("weather_rows") or [],
        workload_rows=calendar_context.get("player_workload") or [],
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
        projections=projections,
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
        "recommended_captain": dict(captain_surface.get("recommended_captain") or {}),
        "recommended_vice_captain": dict(captain_surface.get("recommended_vice_captain") or {}),
        "decision_state": captain_surface.get("decision_state"),
        "recommendation_status": captain_surface.get("recommendation_status"),
        "football_leader": dict(captain_surface.get("football_leader") or {}),
        "frontier_classification": captain_surface.get(
            "football_frontier_classification"
        ),
        "risk_posture": captain_surface.get("risk_posture"),
        "source": "S08_CANONICAL_CAPTAIN_DECISION",
    }

    captain_incomplete = [
        int(row.get("element_id") or 0)
        for row in captain_surface.get("captain_profiles") or []
        if isinstance(row, Mapping)
        and row.get("football_evidence_complete") is not True
    ]
    if str(lineup_state or "").upper() != "COMPLETE":
        captain_section_state = lineup_state
        captain_section_reason = lineup_reason
    elif captain_incomplete:
        captain_section_state = "DEGRADED"
        captain_section_reason = (
            "canonical captain distribution/security evidence genuinely incomplete "
            "for selected-XI elements="
            + ",".join(str(value) for value in captain_incomplete)
        )
    else:
        captain_section_state = "COMPLETE"
        captain_section_reason = None

    price_section_state = str(
        (price_radar or {}).get("state")
        or ("DEGRADED" if price_radar else "UNAVAILABLE")
    ).upper()
    price_section_reason = (
        (price_radar or {}).get("degradation_reason")
        if price_section_state != "COMPLETE"
        else None
    )

    s16_unsupported = [
        {
            "element_id": int(row.get("element_id") or 0),
            "fields": list(
                ((row.get("probability_evidence") or {}).get("unsupported_fields"))
                or []
            ),
        }
        for row in all15_rows
        if isinstance(row, Mapping)
        and ((row.get("probability_evidence") or {}).get("unsupported_fields"))
    ]
    s16_binding_failures = [
        int(row.get("element_id") or 0)
        for row in all15_rows
        if isinstance(row, Mapping)
        and ((row.get("probability_evidence") or {}).get("binding_failures"))
    ]
    if not projections:
        s16_section_state = "DEGRADED"
        s16_section_reason = (
            "P1.1/P1.3 occurrence projection unavailable: "
            + (projection_failure or "UNKNOWN_PROJECTION_FAILURE")
        )
    elif s16_binding_failures:
        s16_section_state = "DEGRADED"
        s16_section_reason = (
            "available canonical probability evidence failed S16 binding for elements="
            + ",".join(str(value) for value in s16_binding_failures)
        )
    elif s16_unsupported:
        s16_section_state = "DEGRADED"
        s16_section_reason = (
            "canonical probability evidence genuinely unsupported for "
            + str(len(s16_unsupported))
            + " OUR15 player(s)"
        )
    else:
        s16_section_state = "COMPLETE"
        s16_section_reason = None

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
            captain_section_state,
            captain_surface,
            captain_section_reason,
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
            price_section_state,
            {
                **(price_radar or {"rows": []}),
                "bank": (finance or {}).get("bank"),
                "bank_status": (finance or {}).get("bank_status"),
                "sell_value_status": (finance or {}).get("sell_value_status"),
            },
            price_section_reason,
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
            s16_section_state,
            {
                "rows": all15_rows,
                "semantic_binding_failures": s16_binding_failures,
                "genuine_probability_unavailable": s16_unsupported,
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
            s16_section_reason,
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
                "injury_availability_evidence": (
                    _availability_evidence_health(projections)
                ),
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

    sections = attach_report_provenance(
        sections,
        report_kind="DEEP",
        target_gw=planning_gw,
        report_timestamp=checkpoint_time,
        target_fixture_ids=[],
    )

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
            private_data_root=(
                Path(args.private_data_root)
                if args.private_data_root
                else None
            ),
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
