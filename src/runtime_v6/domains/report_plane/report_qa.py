from __future__ import annotations

"""Fail-closed report rendering QA gates.

Wave 6 sits after deterministic report compute and before Wave 7 delivery proof.
It never acquires data, publishes V6 artifacts, or marks a report delivered.
"""

from collections import Counter
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .delivery_integrity import MANDATORY_SECTIONS, PARTIAL_ALLOWED_SECTIONS
from .visible_body_contract import validate_visible_report_body


# QA-only mirrors of Canonical V12 invariants. These values are validation
# expectations, not methodology authority. V6 remains standalone and never
# imports downstream decision engines.
_V12_CANONICAL_AUTHORITY = "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
_V12_CANONICAL_WEIGHTS = {
    "PROVEN_HISTORICAL": 0.20,
    "TACTICAL_ROLE": 0.25,
    "CURRENT_UNDERLYING": 0.30,
    "FIXTURE_SECURITY": 0.25,
}

_FULL_COUNT_TARGETS = {
    "OUR15": 15,
    "XI": 11,
    "BENCH": 4,
    "WATCHLIST20": 20,
    "RISE20": 20,
    "FALL20": 20,
}
_MATCH_COUNT_TARGETS = {
    "OUR15": 15,
    "XI": 11,
    "BENCH": 4,
}
_MATCH_SECTION_IDS = tuple(f"MATCH{index}" for index in range(1, 9))
_FULL_BACKBONE_CATALOG_MODES = frozenset(
    {"LEGACY", "DEEP", "FULL", "DEADLINE", "FINAL", "OVERLAP", "POST_ALL_MATCH"}
)
_VALID_SECTION_STATES = frozenset({"COMPLETE", "PARTIAL"})
_MANDATORY_ORDER = {section_id: index for index, section_id in enumerate(MANDATORY_SECTIONS)}
_DEEP_WEATHER_MODES = frozenset(
    {"DEEP", "FULL", "DEADLINE", "FINAL", "OVERLAP", "POST_ALL_MATCH"}
)
_WEATHER_STATES_BY_MODE = {
    **{mode: frozenset({"DIRECT_CHATGPT", "SOURCE_DEGRADED"}) for mode in _DEEP_WEATHER_MODES},
    "MATCH": frozenset({"MATCH_CURRENT", "SOURCE_DEGRADED"}),
    "PRICE": frozenset({"DIRECT_CHATGPT", "PRICE_NOT_IN_SCOPE"}),
}


_FULL_DEEP_VISIBLE_ORDER = (
    "DECISION/STATUS",
    "OUR15",
    "DECISION DELTA",
    "CHANGES",
    "FIXTURES/REST/CONDITIONS",
    "FORMATION/XI/BENCH",
    "XI BATTLE",
    "C/VC",
    "CHIP",
    "ACTIONABLE PRICE RADAR",
    "WATCHLIST20",
    "RISE20",
    "FALL20",
    "PACKAGE OPTIMIZER/FRONTIER",
    "EVIDENCE QUALITY",
    "ICON+ MINI-LEAGUE",
    "ALL15 NEXT-GW TACTICAL/PROBABILITY",
    "SOURCE HEALTH/FRESHNESS/LINEAGE",
    "WAIT/PREPARE/ACT + TRIGGER/REVERSAL",
    "FINAL JUDGEMENT",
)
_PRICE_VISIBLE_ORDER = (
    "PRICE DECISION",
    "OFFICIAL PRICE CHANGES FACT",
    "TEAM-NEEDS PRICE ALERT",
    "WATCHLIST20",
    "RISE20",
    "FALL20",
    "PACKAGE/AFFORDABILITY IMPACT",
    "PRICE RISK VS VALUE OF WAITING FOR FOOTBALL INFORMATION",
    "ICON+ PRICE IMPACT",
    "ACTION BOARD",
    "SOURCE HEALTH",
)

_MATCH_VISIBLE_ORDER = (
    "MATCH CHECKPOINT / GW STATUS",
    "LOCKED PERSONAL TEAM",
    "PERSONAL IMPACT FIRST",
    "GLOBAL AUTOSUB STATE",
    "CAPTAIN / VICE CONSEQUENCE",
    "OWNED LIVE/FINAL POINTS",
    "BONUS/BPS",
    "CARDS / INJURY / DEFCON / ROLE EVENTS",
    "RELEVANT LEAGUE-WIDE SIGNALS",
    "ICON+ LIVE",
    "NEXT-GW LEARNING",
    "NEXT CRITICAL OBSERVATION",
    "SOURCE / FRESHNESS STATUS",
)
_POST_ALL_MATCH_ORDER = (
    "GW RESULT SUMMARY",
    "DECISION P&L / COUNTERFACTUAL",
    "PREDICTION CALIBRATION",
    "OWNED15 REVIEW",
    "GW COMPLETED MATCH-BY-MATCH SCOUT",
    "ROLE / SET-PIECE CHANGES",
    "BAYESIAN CALIBRATION INPUT / ACTUAL UPDATE STATUS",
    "ICON+ FINAL GW",
    "PRICE OUTLOOK",
    "FRESH FULL-UNIVERSE NEXT-GW SCAN",
    "WATCHLIST20",
    "EARLY HOLD / TRANSFER FRONTIER",
    "LEARNING LOG",
)
_DEBUG_VISIBLE_PHRASES = (
    "personal-team reconciliation corrected",
    "reconciliation corrected",
    "repair applied",
    "migration successful",
    "test passed",
)
_MODEL_UPDATE_CLAIMS = (
    "posterior updated",
    "xmins recalibrated",
    "probabilities changed",
    "p(start) changed",
)
_DECISION_DELTA_FIELDS = (
    "decision_item",
    "previous_state",
    "current_state",
    "material_change",
    "reason",
    "evidence_time",
)
_ALL15_VISIBLE_FIELDS = (
    "player",
    "opponent",
    "recommended_or_locked_role",
    "p_available",
    "p_start",
    "p_cameo",
    "p_dnp",
    "xmins",
    "tactical_role",
    "set_piece_penalty_role",
    "matchup",
    "gw_plus_1",
    "three_gw",
    "five_gw",
    "uncertainty_floor_upside",
    "action",
)
_WATCHLIST_VISIBLE_FIELDS = (
    "rank",
    "player",
    "position",
    "club",
    "price",
    "next_opponent",
    "football_score",
    "p_start",
    "xmins",
    "gw_plus_1",
    "three_gw",
    "five_gw",
    "role_set_piece_note",
    "main_upside",
    "main_risk",
    "action",
)
_PACKAGE_VISIBLE_FIELDS = (
    "route",
    "moves",
    "transfer_cost",
    "gw1_net",
    "two_gw_if_relevant",
    "three_gw",
    "five_gw",
    "p_beats_hold",
    "expected_regret",
    "robustness",
    "price_risk",
    "structure_effect",
    "action_verdict",
)
_FINAL_LOCK_FIELDS = (
    "target_gw",
    "transfers_out",
    "transfers_in",
    "number_of_moves",
    "ft_hit_treatment",
    "bank_after_if_known",
    "formation",
    "xi_exact11",
    "bench_gk",
    "outfield_bench_priority_1_3",
    "captain",
    "vice_captain",
    "chip",
    "primary_action",
    "abort_trigger",
    "fallback",
    "evidence_timestamp",
    "canonical_authority_version",
)
_MATCH_SCOUT_FIELDS = (
    "fixture_id",
    "result",
    "formation_system",
    "coach_pattern",
    "player_roles",
    "minutes_substitution_pattern",
    "xg_xa_xgi_shots_chances",
    "set_pieces_penalties",
    "defcon",
    "opponent_channels",
    "sustainable_vs_noisy",
    "implication_for_our15",
    "implication_for_next_opponent",
    "posterior_calibration_implication",
)
_PRICE_WAIT_FIELDS = (
    "route",
    "affordable_now",
    "after_target_plus_0_1",
    "after_owned_minus_0_1",
    "sell_value_impact",
    "route_survival",
    "football_information_benefit_of_waiting",
)
_OVERNIGHT_RISK_FIELDS = (
    "player_or_route",
    "current_action",
    "possible_change_event",
    "materiality",
    "next_checkpoint",
)
_ICON_COUNT_METRICS = ("ownership", "starter_share", "captain_share", "vice_share")
_ALLOWED_ALL15_ACTIONS = frozenset({"START", "BENCH", "HOLD", "WATCH", "SELL-CANDIDATE"})



def _content_fingerprint(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _missing_row_fields(rows: Sequence[Any], fields: Sequence[str], label: str) -> list[str]:
    failures: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            failures.append(f"{label}_ROW_INVALID={index}")
            continue
        missing = [field for field in fields if field not in row]
        if missing:
            failures.append(f"{label}_ROW_SCHEMA_MISSING={index}:{','.join(missing)}")
    return failures


def _row_identity(row: Mapping[str, Any]) -> Any:
    for key in ("element_id", "element", "player_id", "id", "player"):
        if row.get(key) is not None:
            return row.get(key)
    return None


def _validate_bench_presentation(payload: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    bench = payload.get("bench_presentation")
    if not isinstance(bench, Mapping):
        return ["BENCH_PRESENTATION_MISSING"]
    bench_gk = bench.get("bench_gk")
    outfield = list(bench.get("outfield_autosub_priority") or [])
    if bench_gk in (None, ""):
        failures.append("BENCH_GK_MISSING")
    if len(outfield) != 3:
        failures.append(f"OUTFIELD_BENCH_PRIORITY_COUNT={len(outfield)}")
    if bench_gk in outfield:
        failures.append("BENCH_GK_RENDERED_AS_OUTFIELD_PRIORITY")
    if len(set(map(str, outfield))) != len(outfield):
        failures.append("OUTFIELD_BENCH_PRIORITY_DUPLICATE")
    position_by_player = bench.get("position_by_player")
    if isinstance(position_by_player, Mapping):
        for candidate in outfield:
            if str(position_by_player.get(str(candidate), position_by_player.get(candidate)) or "").upper() in {"GK", "GKP"}:
                failures.append("GOALKEEPER_IN_OUTFIELD_AUTOSUB_PRIORITY")
    return failures


def _validate_decision_delta(payload: Mapping[str, Any]) -> list[str]:
    if not payload.get("prior_visible_report"):
        return []
    delta = payload.get("decision_delta")
    if not isinstance(delta, Mapping):
        return ["DECISION_DELTA_MISSING"]
    rows = list(delta.get("rows") or [])
    no_change = bool(delta.get("no_material_decision_change"))
    failures: list[str] = []
    if rows and no_change:
        failures.append("DECISION_DELTA_CONFLICT")
    if not rows and not no_change:
        failures.append("DECISION_DELTA_EMPTY_WITHOUT_NO_CHANGE")
    failures.extend(_missing_row_fields(rows, _DECISION_DELTA_FIELDS, "DECISION_DELTA"))
    for index, row in enumerate(rows, start=1):
        if isinstance(row, Mapping) and row.get("material_change") is not True:
            failures.append(f"DECISION_DELTA_NONMATERIAL_ROW={index}")
    return failures


def _validate_icon_contract(payload: Mapping[str, Any]) -> list[str]:
    icon = payload.get("icon")
    if not isinstance(icon, Mapping):
        return []
    if str(icon.get("status") or "").upper() not in {"FRESH", "COMPLETE"}:
        return []
    metrics = icon.get("metrics")
    if not isinstance(metrics, Mapping):
        return ["ICON_METRICS_MISSING"]
    failures: list[str] = []
    for label in _ICON_COUNT_METRICS:
        row = metrics.get(label)
        if not isinstance(row, Mapping):
            failures.append(f"ICON_METRIC_MISSING={label}")
            continue
        try:
            numerator = float(row["numerator"])
            denominator = float(row["denominator"])
            percentage = float(row["percentage"])
        except (KeyError, TypeError, ValueError):
            failures.append(f"ICON_METRIC_INVALID={label}")
            continue
        if denominator <= 0:
            failures.append(f"ICON_DENOMINATOR_INVALID={label}")
            continue
        expected = numerator / denominator * 100.0
        if abs(expected - percentage) > 0.11:
            failures.append(f"ICON_ARITHMETIC_MISMATCH={label}")
    if "eo" not in metrics:
        failures.append("ICON_EO_MISSING")
    return failures


def _validate_model_update_semantics(payload: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    rows = list(payload.get("calibration_items") or [])
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            failures.append(f"CALIBRATION_ROW_INVALID={index}")
            continue
        state = str(row.get("status") or "").upper()
        if state not in {"CALIBRATION_INPUT", "MODEL_UPDATE_PENDING_NEXT_COMPUTE", "ACTUAL_MODEL_UPDATE"}:
            failures.append(f"CALIBRATION_STATUS_INVALID={index}:{state or '<empty>'}")
            continue
        if state == "ACTUAL_MODEL_UPDATE":
            proof = row.get("execution_proof")
            if not (
                isinstance(proof, Mapping)
                and proof.get("executed") is True
                and proof.get("evidence_time")
                and "previous_value" in proof
                and "current_value" in proof
            ):
                failures.append(f"MODEL_UPDATE_EXECUTION_PROOF_MISSING={index}")
    return failures


_VISIBLE_SECTION_STATES = frozenset({"COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE"})
_DEGRADED_STATES = frozenset({"PARTIAL", "DEGRADED", "UNAVAILABLE"})
_SECTION_TO_COMPUTE_SECTION = {
    "WATCHLIST20": "WATCHLIST20",
    "RISE20": "RISE20",
    "FALL20": "FALL20",
    "ALL15": "ALL15_TACTICAL",
    "PACKAGE_FRONTIER": "OPTIMIZER",
    "ICON+": "ICON14B",
}
_SECTION_TO_COUNT_LABEL = {
    "WATCHLIST20": "WATCHLIST20",
    "RISE20": "RISE20",
    "FALL20": "FALL20",
}
_SECTION_TO_RENDER_COUNT_LABEL = {
    "ALL15": "ALL15_TACTICAL",
    "WATCHLIST20": "WATCHLIST20",
    "RISE20": "RISE20",
    "FALL20": "FALL20",
}



def _section_state(
    payload: Mapping[str, Any],
    section: str,
    *,
    default: str = "COMPLETE",
) -> dict[str, Any]:
    raw_states = payload.get("section_states")
    raw = raw_states.get(section) if isinstance(raw_states, Mapping) else None
    if isinstance(raw, Mapping):
        meta = dict(raw)
        state = str(meta.get("state") or default).strip().upper()
    elif raw is not None:
        meta = {}
        state = str(raw or default).strip().upper()
    else:
        meta = {}
        state = default
    meta["state"] = state
    return meta


def _section_degradation(
    *,
    section: str,
    meta: Mapping[str, Any],
    actual_count: int | None = None,
    expected_count: int | None = None,
    require_count: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    state = str(meta.get("state") or "").strip().upper()
    hard: list[str] = []
    if state not in _VISIBLE_SECTION_STATES:
        return {}, [f"SECTION_STATE_INVALID={section}:{state or '<empty>'}"]
    if state == "COMPLETE":
        return {}, []
    reason = str(meta.get("degradation_reason") or "").strip()
    if not reason:
        hard.append(f"SECTION_DEGRADATION_REASON_MISSING={section}")
    available = meta.get("available_count", actual_count)
    expected = meta.get("expected_count", expected_count)
    if require_count:
        try:
            available_int = int(available)
            expected_int = int(expected)
        except (TypeError, ValueError):
            hard.append(f"SECTION_DEGRADATION_COUNT_METADATA_INVALID={section}")
            available_int = actual_count
            expected_int = expected_count
        else:
            if actual_count is not None and available_int != actual_count:
                hard.append(
                    f"SECTION_AVAILABLE_COUNT_MISMATCH={section}:{available_int}!={actual_count}"
                )
            if expected_count is not None and expected_int != expected_count:
                hard.append(
                    f"SECTION_EXPECTED_COUNT_MISMATCH={section}:{expected_int}!={expected_count}"
                )
    else:
        available_int = available
        expected_int = expected
    degradation = {
        "section": section,
        "state": state,
        "degradation_reason": reason or None,
        "available_count": available_int,
        "expected_count": expected_int,
        "missing_fields": list(meta.get("missing_fields") or []),
        "missing_scope": list(meta.get("missing_scope") or []),
        "provenance": meta.get("provenance"),
        "freshness": meta.get("freshness"),
    }
    return degradation, hard


def _placeholder_rows(rows: Sequence[Any], label: str) -> list[str]:
    failures: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            continue
        if (
            row.get("fabricated") is True
            or row.get("placeholder") is True
            or row.get("synthetic_fill") is True
            or str(row.get("row_origin") or "").strip().upper()
            in {"PLACEHOLDER", "FABRICATED", "QA_FILL", "SYNTHETIC_FILL"}
        ):
            failures.append(f"{label}_FABRICATED_PLACEHOLDER_ROW={index}")
    return failures


def _duplicate_id_failure(rows: Sequence[Any], label: str) -> list[str]:
    ids = [_row_identity(row) for row in rows if isinstance(row, Mapping)]
    concrete = [str(value) for value in ids if value is not None]
    failures: list[str] = []
    if len(concrete) != len(ids):
        failures.append(f"{label}_IDENTITY_MISSING")
    if len(set(concrete)) != len(concrete):
        failures.append(f"{label}_IDENTITY_DUPLICATE")
    return failures


def _degradation_label_visible(body: str, section: str, state: str) -> bool:
    upper = str(body or "").upper()
    section_upper = section.upper()
    start = upper.find(section_upper)
    if start < 0:
        return False
    window = upper[start : start + 420]
    state_upper = state.upper()
    return any(
        marker in window
        for marker in (
            f"STATE={state_upper}",
            f"STATE: {state_upper}",
            f"STATE {state_upper}",
            f"— {state_upper}",
            f"- {state_upper}",
        )
    )


def _validate_visible_degradation_labels(
    *,
    rendered_body: str,
    section_degradations: Sequence[Mapping[str, Any]],
) -> list[str]:
    failures: list[str] = []
    for row in section_degradations:
        section = str(row.get("section") or "").strip()
        state = str(row.get("state") or "").strip().upper()
        if section and state and not _degradation_label_visible(rendered_body, section, state):
            failures.append(f"VISIBLE_DEGRADATION_LABEL_MISSING={section}:{state}")
    return failures


def validate_v12_visible_content_contract(
    *,
    report_mode: str,
    content_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate correctness separately from truthful section-level degradation."""
    mode = str(report_mode or "").strip().upper()
    payload = dict(content_contract or {})
    hard_failures: list[str] = []
    section_degradations: list[dict[str, Any]] = []
    warnings: list[str] = []

    hard_failures.extend(_validate_decision_delta(payload))
    hard_failures.extend(_validate_model_update_semantics(payload))

    icon = payload.get("icon") if isinstance(payload.get("icon"), Mapping) else None
    icon_default_state = (
        "COMPLETE"
        if isinstance(icon, Mapping) and str(icon.get("status") or "").upper() in {"FRESH", "COMPLETE"}
        else str((icon or {}).get("status") or "UNAVAILABLE").upper()
        if isinstance(icon, Mapping)
        else "UNAVAILABLE"
    )
    icon_meta = _section_state(payload, "ICON+", default=icon_default_state)
    icon_state = str(icon_meta.get("state") or "").upper()
    if icon_state == "COMPLETE":
        hard_failures.extend(_validate_icon_contract(payload))
        if payload.get("football_optimal_baseline_before_icon") is not True:
            hard_failures.append("ICON_OVERLAY_PRECEDENCE_INVALID")
    else:
        degradation, meta_hard = _section_degradation(
            section="ICON+",
            meta=icon_meta,
            require_count=False,
        )
        hard_failures.extend(meta_hard)
        if degradation:
            section_degradations.append(degradation)
        if isinstance(icon, Mapping) and (
            icon.get("presented_as_current") is True
            or str(icon.get("freshness") or "").upper() == "CURRENT"
        ):
            hard_failures.append("ICON_DEGRADED_PRESENTED_AS_CURRENT")

    if (
        payload.get("report_due") is True
        and payload.get("optional_scope_degraded") is True
        and payload.get("visible_report_suppressed") is True
    ):
        hard_failures.append("OPTIONAL_DEGRADED_SCOPE_SUPPRESSED_DUE_REPORT")

    if mode in {"MATCH", "DEEP", "FULL", "DEADLINE", "FINAL", "OVERLAP", "POST_ALL_MATCH"}:
        hard_failures.extend(_validate_bench_presentation(payload))

    if mode == "MATCH":
        order = tuple(str(value).strip().upper() for value in payload.get("visible_order") or [])
        if order != tuple(value.upper() for value in _MATCH_VISIBLE_ORDER):
            hard_failures.append("PURE_MATCH_VISIBLE_ORDER_INVALID")
        required = (
            "locked_team",
            "personal_impact",
            "global_autosub_state",
            "captain_vice_consequence",
            "owned_live_final_points",
            "bonus_bps",
            "cards_injury_defcon_role_events",
            "league_wide_signals",
            "next_gw_learning",
            "next_critical_observation",
            "source_freshness",
        )
        for key in required:
            if key not in payload:
                hard_failures.append(f"PURE_MATCH_BLOCK_MISSING={key}")

        impact_rows = list(payload.get("personal_impact") or [])
        substitution_map = (
            (payload.get("global_autosub_state") or {}).get("final_substitution_map")
            if isinstance(payload.get("global_autosub_state"), Mapping)
            else {}
        ) or {}
        for index, row in enumerate(impact_rows, start=1):
            if not isinstance(row, Mapping):
                hard_failures.append(f"PERSONAL_IMPACT_ROW_INVALID={index}")
                continue
            state = str(row.get("personal_state") or "").upper()
            element = row.get("element_id")
            mapped = substitution_map.get(str(element)) if element is not None else None
            if state == "DNP_WITH_AUTOSUB_POSSIBLE" and mapped in (None, "no_legal_sub", "pending"):
                hard_failures.append(f"DNP_AUTOSUB_VISIBLE_STATE_MISMATCH={index}")
            if state == "DNP_AUTOSUB_PENDING" and mapped != "pending":
                hard_failures.append(f"DNP_AUTOSUB_PENDING_MISMATCH={index}")
            if state == "BENCH_DNP_NO_DIRECT_XI_AUTOSUB_EFFECT" and row.get("autosub_activates") is True:
                hard_failures.append(f"BENCH_DNP_FALSE_AUTOSUB_ACTIVATION={index}")
            if state == "CAMEO_BLOCKED_AUTOSUB" and mapped not in (None, "no_legal_sub"):
                hard_failures.append(f"CAMEO_SHOULD_NOT_BE_IN_SUBSTITUTION_MAP={index}")

    if mode in {"DEEP", "FULL", "DEADLINE", "FINAL"}:
        order = tuple(str(value).strip().upper() for value in payload.get("visible_order") or [])
        if order != tuple(value.upper() for value in _FULL_DEEP_VISIBLE_ORDER):
            hard_failures.append("FULL_DEEP_VISIBLE_ORDER_INVALID")

    if mode in {"DEEP", "FULL", "DEADLINE", "FINAL", "OVERLAP", "POST_ALL_MATCH"}:
        all15 = list(payload.get("all15") or [])
        all15_meta = _section_state(payload, "ALL15")
        all15_state = str(all15_meta.get("state") or "").upper()
        hard_failures.extend(_duplicate_id_failure(all15, "ALL15"))
        hard_failures.extend(_placeholder_rows(all15, "ALL15"))
        if all15_state == "COMPLETE":
            if len(all15) != 15:
                hard_failures.append(f"ALL15_COUNT={len(all15)}")
            hard_failures.extend(_missing_row_fields(all15, _ALL15_VISIBLE_FIELDS, "ALL15"))
            for index, row in enumerate(all15, start=1):
                if isinstance(row, Mapping) and str(row.get("action") or "").upper() not in _ALLOWED_ALL15_ACTIONS:
                    hard_failures.append(f"ALL15_ACTION_INVALID={index}")
        else:
            degradation, meta_hard = _section_degradation(
                section="ALL15",
                meta=all15_meta,
                actual_count=len(all15),
                expected_count=15,
                require_count=True,
            )
            hard_failures.extend(meta_hard)
            if degradation:
                section_degradations.append(degradation)

        watchlist = list(payload.get("watchlist20") or [])
        watch_meta = _section_state(payload, "WATCHLIST20")
        watch_state = str(watch_meta.get("state") or "").upper()
        hard_failures.extend(_duplicate_id_failure(watchlist, "WATCHLIST20"))
        hard_failures.extend(_placeholder_rows(watchlist, "WATCHLIST20"))
        if any(bool(row.get("owned")) for row in watchlist if isinstance(row, Mapping)):
            hard_failures.append("WATCHLIST20_OWNED_PLAYER_PRESENT")
        if watch_state == "COMPLETE":
            if len(watchlist) != 20:
                hard_failures.append(f"WATCHLIST20_COUNT={len(watchlist)}")
            hard_failures.extend(_missing_row_fields(watchlist, _WATCHLIST_VISIBLE_FIELDS, "WATCHLIST20"))
            positions = Counter(
                str(row.get("position") or "").upper()
                for row in watchlist
                if isinstance(row, Mapping)
            )
            for position in ("GK", "DEF", "MID", "FWD"):
                if positions.get(position, 0) != 5:
                    hard_failures.append(f"WATCHLIST20_{position}={positions.get(position, 0)}")
            if payload.get("watchlist_full_universe_derived") is not True:
                hard_failures.append("WATCHLIST20_FULL_UNIVERSE_LINEAGE_MISSING")
        else:
            degradation, meta_hard = _section_degradation(
                section="WATCHLIST20",
                meta=watch_meta,
                actual_count=len(watchlist),
                expected_count=20,
                require_count=True,
            )
            hard_failures.extend(meta_hard)
            if degradation:
                section_degradations.append(degradation)

        for section, key in (("RISE20", "rise20"), ("FALL20", "fall20")):
            rows = list(payload.get(key) or [])
            meta = _section_state(payload, section)
            state = str(meta.get("state") or "").upper()
            hard_failures.extend(_duplicate_id_failure(rows, section))
            hard_failures.extend(_placeholder_rows(rows, section))
            if state == "COMPLETE":
                if key in payload and len(rows) != 20:
                    hard_failures.append(f"{section}_COUNT={len(rows)}")
            else:
                degradation, meta_hard = _section_degradation(
                    section=section,
                    meta=meta,
                    actual_count=len(rows),
                    expected_count=20,
                    require_count=True,
                )
                hard_failures.extend(meta_hard)
                if degradation:
                    section_degradations.append(degradation)

        routes = list(payload.get("package_routes") or [])
        package_meta = _section_state(payload, "PACKAGE_FRONTIER")
        package_state = str(package_meta.get("state") or "").upper()
        route_names = [str(row.get("route") or "") for row in routes if isinstance(row, Mapping)]
        if len(route_names) != len(set(route_names)):
            hard_failures.append("PACKAGE_ROUTE_DUPLICATE")
        hard_failures.extend(_placeholder_rows(routes, "PACKAGE"))
        if package_state == "COMPLETE":
            hard_failures.extend(_missing_row_fields(routes, _PACKAGE_VISIBLE_FIELDS, "PACKAGE"))
            if payload.get("serious_comparison") is True and not routes:
                hard_failures.append("PACKAGE_SERIOUS_COMPARISON_MISSING")
            if routes and not any(name.upper() == "HOLD" for name in route_names):
                hard_failures.append("PACKAGE_HOLD_BASELINE_MISSING")
        else:
            degradation, meta_hard = _section_degradation(
                section="PACKAGE_FRONTIER",
                meta=package_meta,
                actual_count=len(routes),
                expected_count=None,
                require_count=False,
            )
            hard_failures.extend(meta_hard)
            if degradation:
                section_degradations.append(degradation)
        if (
            str(payload.get("search_authority") or "").upper() == "PARTIAL"
            and payload.get("search_authority_visible") is not True
        ):
            hard_failures.append("PARTIAL_SEARCH_AUTHORITY_NOT_VISIBLE")

    if mode == "FINAL":
        lock = payload.get("gw_lock_package")
        lock_meta = _section_state(payload, "GW_LOCK_PACKAGE")
        lock_state = str(lock_meta.get("state") or "").upper()
        if lock_state == "COMPLETE":
            if not isinstance(lock, Mapping):
                hard_failures.append("GW_LOCK_PACKAGE_MISSING")
            else:
                missing = [field for field in _FINAL_LOCK_FIELDS if field not in lock]
                if missing:
                    hard_failures.append(f"GW_LOCK_PACKAGE_SCHEMA_MISSING={','.join(missing)}")
        else:
            degradation, meta_hard = _section_degradation(
                section="GW_LOCK_PACKAGE",
                meta=lock_meta,
                require_count=False,
            )
            hard_failures.extend(meta_hard)
            if degradation:
                section_degradations.append(degradation)
            if not list(lock_meta.get("missing_fields") or []):
                hard_failures.append("GW_LOCK_PACKAGE_DEGRADED_MISSING_FIELDS_UNDECLARED")

        if isinstance(lock, Mapping):
            xi_present = "xi_exact11" in lock
            xi = list(lock.get("xi_exact11") or [])
            outfield_present = "outfield_bench_priority_1_3" in lock
            outfield = list(lock.get("outfield_bench_priority_1_3") or [])
            if xi_present and (len(xi) != 11 or len(set(map(str, xi))) != 11):
                hard_failures.append("GW_LOCK_PACKAGE_XI_INVALID")
            if outfield_present and (len(outfield) != 3 or len(set(map(str, outfield))) != 3):
                hard_failures.append("GW_LOCK_PACKAGE_OUTFIELD_BENCH_INVALID")
            if outfield_present and lock.get("bench_gk") in outfield:
                hard_failures.append("GW_LOCK_PACKAGE_GK_IN_OUTFIELD_PRIORITY")
            if (
                xi_present
                and lock.get("captain") is not None
                and lock.get("vice_captain") is not None
                and (
                    lock.get("captain") not in xi
                    or lock.get("vice_captain") not in xi
                    or lock.get("captain") == lock.get("vice_captain")
                )
            ):
                hard_failures.append("GW_LOCK_PACKAGE_CVC_INVALID")
        if lock_state == "COMPLETE" and payload.get("selected_package_unambiguous") is not True:
            hard_failures.append("GW_LOCK_PACKAGE_SELECTION_AMBIGUOUS")

    if mode == "POST_ALL_MATCH":
        order = tuple(str(value).strip().upper() for value in payload.get("visible_order") or [])
        if order != tuple(value.upper() for value in _POST_ALL_MATCH_ORDER):
            hard_failures.append("POST_ALL_MATCH_VISIBLE_ORDER_INVALID")
        completed = [str(value) for value in payload.get("completed_fixture_ids") or []]
        scout = list(payload.get("match_scout") or [])
        scout_meta = _section_state(payload, "MATCH_SCOUT")
        scout_state = str(scout_meta.get("state") or "").upper()
        scout_ids = [
            str(row.get("fixture_id"))
            for row in scout
            if isinstance(row, Mapping) and row.get("fixture_id") is not None
        ]
        if len(scout_ids) != len(scout):
            hard_failures.append("MATCH_SCOUT_IDENTITY_MISSING")
        if len(scout_ids) != len(set(scout_ids)):
            hard_failures.append("MATCH_SCOUT_FIXTURE_DUPLICATE")
        hard_failures.extend(_placeholder_rows(scout, "MATCH_SCOUT"))
        if scout_state == "COMPLETE":
            hard_failures.extend(_missing_row_fields(scout, _MATCH_SCOUT_FIELDS, "MATCH_SCOUT"))
            if set(scout_ids) != set(completed) or len(scout_ids) != len(completed):
                hard_failures.append("MATCH_SCOUT_FIXTURE_COVERAGE_MISMATCH")
        else:
            degradation, meta_hard = _section_degradation(
                section="MATCH_SCOUT",
                meta=scout_meta,
                actual_count=len(scout),
                expected_count=len(completed),
                require_count=True,
            )
            hard_failures.extend(meta_hard)
            if degradation:
                section_degradations.append(degradation)

    if mode == "PRICE":
        order = tuple(str(value).strip().upper() for value in payload.get("visible_order") or [])
        if order != tuple(value.upper() for value in _PRICE_VISIBLE_ORDER):
            hard_failures.append("PRICE_VISIBLE_ORDER_INVALID")
        rows = list(payload.get("price_waiting_comparison") or [])
        hard_failures.extend(_missing_row_fields(rows, _PRICE_WAIT_FIELDS, "PRICE_WAITING"))
        if payload.get("material_price_route_count") and not rows:
            hard_failures.append("PRICE_WAITING_COMPARISON_MISSING")

    if mode in {"DEEP", "FULL"} and str(payload.get("checkpoint_time") or "") == "04:30":
        if str(payload.get("deep_emphasis") or "").upper() != "OVERNIGHT_RESET_BASELINE":
            hard_failures.append("0430_DEEP_EMPHASIS_INVALID")
    if mode in {"DEEP", "FULL"} and str(payload.get("checkpoint_time") or "") == "12:30":
        if str(payload.get("deep_emphasis") or "").upper() != "DELTA_SINCE_04:30":
            hard_failures.append("1230_DEEP_EMPHASIS_INVALID")
        if "press_news_probability_changes" not in payload:
            hard_failures.append("1230_PRESS_NEWS_DELTA_MISSING")
    if mode in {"DEEP", "FULL"} and str(payload.get("checkpoint_time") or "") == "21:30":
        if str(payload.get("deep_emphasis") or "").upper() != "LATE_NEWS_OVERNIGHT_PRICE_DEADLINE_RISK":
            hard_failures.append("2130_DEEP_EMPHASIS_INVALID")
        rows = list(payload.get("overnight_risk_board") or [])
        if not rows:
            hard_failures.append("OVERNIGHT_RISK_BOARD_MISSING")
        hard_failures.extend(_missing_row_fields(rows, _OVERNIGHT_RISK_FIELDS, "OVERNIGHT_RISK"))

    if mode == "OVERLAP":
        block_ids = [str(value) for value in payload.get("visible_block_ids") or []]
        if len(block_ids) != len(set(block_ids)):
            hard_failures.append("FULL_MATCH_DUPLICATED_REPORT_BLOCK")

    degraded_count_labels = sorted(
        {
            _SECTION_TO_COUNT_LABEL[row["section"]]
            for row in section_degradations
            if row.get("section") in _SECTION_TO_COUNT_LABEL
        }
    )
    degraded_compute_sections = sorted(
        {
            _SECTION_TO_COMPUTE_SECTION[row["section"]]
            for row in section_degradations
            if row.get("section") in _SECTION_TO_COMPUTE_SECTION
        }
    )
    report_can_continue = not hard_failures
    severity = "FAIL" if hard_failures else "DEGRADED" if section_degradations else "PASS"
    return {
        "status": "FAIL" if hard_failures else "PASS",
        "severity": severity,
        "failures": hard_failures,
        "hard_failures": hard_failures,
        "section_degradations": section_degradations,
        "warnings": warnings,
        "report_can_continue": report_can_continue,
        "report_mode": mode,
        "degraded_count_labels": degraded_count_labels,
        "degraded_compute_sections": degraded_compute_sections,
        "contract_fingerprint": _content_fingerprint(payload),
    }


def _validate_v12_rendered_body(
    *,
    report_mode: str,
    rendered_body: str,
    content_contract: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(content_contract, Mapping):
        return []
    failures: list[str] = []
    body = str(rendered_body or "")
    lower = body.casefold()
    for phrase in _DEBUG_VISIBLE_PHRASES:
        if phrase.casefold() in lower:
            failures.append(f"VISIBLE_DEBUG_LANGUAGE={phrase}")

    has_actual_update = any(
        isinstance(row, Mapping)
        and str(row.get("status") or "").upper() == "ACTUAL_MODEL_UPDATE"
        and isinstance(row.get("execution_proof"), Mapping)
        and row["execution_proof"].get("executed") is True
        for row in content_contract.get("calibration_items") or []
    )
    if not has_actual_update and any(claim.casefold() in lower for claim in _MODEL_UPDATE_CLAIMS):
        failures.append("UNPROVEN_MODEL_RECOMPUTATION_CLAIM")

    mode = str(report_mode or "").upper()
    if mode == "MATCH":
        positions = []
        for marker in _MATCH_VISIBLE_ORDER:
            needle = marker if marker != "ICON+ LIVE" else "ICON+"
            positions.append(body.upper().find(needle.upper()))
        if any(position < 0 for position in positions) or positions != sorted(positions):
            failures.append("PURE_MATCH_RENDER_ORDER_INVALID")
        if "BENCH GK" not in body.upper() or "OUTFIELD AUTOSUB PRIORITY" not in body.upper():
            failures.append("VISIBLE_BENCH_SEPARATION_MISSING")

    if content_contract.get("prior_visible_report"):
        if "DECISION DELTA" not in body.upper() and "NO MATERIAL DECISION CHANGE" not in body.upper():
            failures.append("VISIBLE_DECISION_DELTA_MISSING")

    if mode == "FINAL" and "GW LOCK PACKAGE" not in body.upper():
        failures.append("VISIBLE_GW_LOCK_PACKAGE_MISSING")
    if mode == "POST_ALL_MATCH" and "GW COMPLETED MATCH-BY-MATCH SCOUT" not in body.upper():
        failures.append("VISIBLE_MATCH_SCOUT_MISSING")
    if str(content_contract.get("search_authority") or "").upper() == "PARTIAL":
        if "SEARCH PARTIAL" not in body.upper():
            failures.append("VISIBLE_PARTIAL_SEARCH_LABEL_MISSING")
    contract_validation = validate_v12_visible_content_contract(
        report_mode=report_mode,
        content_contract=content_contract,
    )
    failures.extend(
        _validate_visible_degradation_labels(
            rendered_body=body,
            section_degradations=contract_validation.get("section_degradations", []),
        )
    )
    return failures


def _expected_visible_catalog(report_mode: str, generated_section_ids: Sequence[str]) -> list[str]:
    mode = str(report_mode or "LEGACY").strip().upper() or "LEGACY"
    if mode == "MATCH":
        return list(_MATCH_SECTION_IDS)
    if mode in _FULL_BACKBONE_CATALOG_MODES:
        return list(MANDATORY_SECTIONS)
    return list(generated_section_ids)


def _expected_visible_counts(report_mode: str) -> dict[str, int]:
    mode = str(report_mode or "LEGACY").strip().upper() or "LEGACY"
    if mode == "MATCH":
        return dict(_MATCH_COUNT_TARGETS)
    return dict(_FULL_COUNT_TARGETS)


def _required_visible_markers(report_mode: str) -> list[str]:
    mode = str(report_mode or "").strip().upper()
    if mode == "POST_ALL_MATCH":
        return ["GW COMPLETED MATCH-BY-MATCH SCOUT"]
    return []


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _section_sort_key(section_id: str) -> tuple[int, int | str]:
    if section_id in _MANDATORY_ORDER:
        return (0, _MANDATORY_ORDER[section_id])
    return (1, section_id)


def _canonical_section_manifest(
    section_manifest: Sequence[Mapping[str, Any]],
    *,
    expected_section_ids: Sequence[str],
) -> tuple[
    list[dict[str, str]],
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
]:
    rows: list[dict[str, str]] = []
    ids: list[str] = []
    invalid_states: list[str] = []
    partial_not_allowed: list[str] = []
    partial_sections: list[str] = []
    expected_order = {
        str(section_id).strip().upper(): index
        for index, section_id in enumerate(expected_section_ids)
    }

    def sort_key(section_id: str) -> tuple[int, int | str]:
        if section_id in expected_order:
            return (0, expected_order[section_id])
        return (1, section_id)

    for row in section_manifest:
        section_id = str(row.get("section_id") or "").strip().upper()
        state = str(row.get("status") or "").strip().upper()
        ids.append(section_id)
        rows.append({"section_id": section_id, "status": state})
        if not section_id:
            invalid_states.append("<missing>:SECTION_ID_MISSING")
        if state not in _VALID_SECTION_STATES:
            invalid_states.append(f"{section_id or '<missing>'}:{state or '<empty>'}")
        if state == "PARTIAL":
            partial_sections.append(section_id)
            if section_id not in PARTIAL_ALLOWED_SECTIONS:
                partial_not_allowed.append(section_id)

    counts = Counter(ids)
    duplicates = sorted(
        (section_id for section_id, count in counts.items() if section_id and count > 1),
        key=sort_key,
    )
    present = set(ids)
    missing = [
        section_id
        for section_id in expected_section_ids
        if section_id not in present
    ]
    canonical_rows = sorted(rows, key=lambda row: sort_key(row["section_id"]))
    canonical_ids = [row["section_id"] for row in canonical_rows if row["section_id"]]
    return (
        canonical_rows,
        canonical_ids,
        missing,
        duplicates,
        sorted(partial_sections, key=sort_key),
        sorted(partial_not_allowed, key=sort_key),
        invalid_states,
    )


def _compute_handoff_failures(
    compute_contract: Mapping[str, Any],
    *,
    degradable_count_labels: Sequence[str] = (),
    degradable_compute_sections: Sequence[str] = (),
) -> list[str]:
    """Hard-fail only non-degradable compute contradictions for a due report."""
    failures: list[str] = []
    soft_count = {str(value).upper() for value in degradable_count_labels}
    soft_sections = {str(value).upper() for value in degradable_compute_sections}

    fingerprint = compute_contract.get("compute_fingerprint")
    if not _is_sha256(fingerprint):
        failures.append("COMPUTE_FINGERPRINT_INVALID")

    for label, target in _FULL_COUNT_TARGETS.items():
        row = compute_contract.get(label)
        if label in soft_count:
            continue
        if not isinstance(row, Mapping) or row.get("status") != "PASS":
            failures.append(f"COMPUTE_CHECK_FAILED={label}")
            continue
        if row.get("total") != target:
            failures.append(f"COMPUTE_COUNT_MISMATCH={label}:{row.get('total')}!={target}")

    fact_model = compute_contract.get("FACT_MODEL")
    if not isinstance(fact_model, Mapping) or fact_model.get("status") != "PASS":
        failures.append("FACT_MODEL_CONTRACT_FAILED")
    elif fact_model.get("overlap"):
        failures.append("FACT_MODEL_CONTRACT_OVERLAP")

    section_contract = compute_contract.get("SECTION_CONTRACT")
    if isinstance(section_contract, Mapping) and section_contract.get("status") != "PASS":
        failed_sections = {
            str(value).upper()
            for value in section_contract.get("failures", [])
            if str(value).strip()
        }
        hard_sections = sorted(failed_sections - soft_sections)
        if hard_sections:
            failures.append(f"SECTION_CONTRACT_HARD_FAIL={','.join(hard_sections)}")

    underlying = {
        str(value).upper()
        for value in compute_contract.get("failures", [])
        if str(value).strip()
    }
    if underlying & {"PROVENANCE", "MANDATORY_SEMANTIC"}:
        failures.append(
            "COMPUTE_HARD_FAILURE="
            + ",".join(sorted(underlying & {"PROVENANCE", "MANDATORY_SEMANTIC"}))
        )

    ready_contract = (
        compute_contract.get("status") == "PASS"
        and compute_contract.get("compute_ready") is True
        and compute_contract.get("next_action") == "PRE_RENDER_QA"
        and compute_contract.get("delivery_ready") is False
        and compute_contract.get("legacy_fallback_allowed") is False
    )
    if not ready_contract:
        soft_only_underlying = bool(underlying) and underlying <= {"SECTION_CONTRACT"}
        section_soft_only = (
            isinstance(section_contract, Mapping)
            and {
                str(value).upper()
                for value in section_contract.get("failures", [])
                if str(value).strip()
            }
            <= soft_sections
        )
        if not (soft_only_underlying and section_soft_only and not failures):
            failures.append("COMPUTE_CONTRACT_NOT_READY")
    return list(dict.fromkeys(failures))


def _normalize_weather_contract(
    *,
    report_mode: str | None,
    weather_contract_state: str | None,
    weather_required: bool,
    weather_direct_chat_present: bool,
) -> tuple[str, str, bool, bool, str | None]:
    """Resolve new mode-aware weather semantics while preserving legacy callers."""
    explicit_mode = report_mode is not None or weather_contract_state is not None
    if not explicit_mode:
        mode = "LEGACY"
        if weather_direct_chat_present:
            state = "DIRECT_CHATGPT"
            valid = True
        elif not weather_required:
            state = "NOT_REQUIRED"
            valid = True
        else:
            state = "MISSING"
            valid = False
        failure = None if valid else "MANDATORY_WEATHER_MISSING"
        return mode, state, bool(weather_required), bool(weather_direct_chat_present), failure

    mode = str(report_mode or "").strip().upper()
    state = str(weather_contract_state or "MISSING").strip().upper() or "MISSING"
    allowed = _WEATHER_STATES_BY_MODE.get(mode)
    valid = bool(allowed and state in allowed)
    failure = None if valid else f"WEATHER_CONTRACT_INVALID={mode or '<empty>'}:{state}"
    direct_present = state in {"DIRECT_CHATGPT", "MATCH_CURRENT"}
    return mode, state, True, direct_present, failure


def _render_contract_token(
    *,
    compute_fingerprint: str,
    canonical_manifest: Sequence[Mapping[str, str]],
    mini_league_denominator_complete: bool,
    mini_league_contract_state: str,
    report_mode: str,
    weather_contract_state: str,
    weather_required: bool,
    weather_direct_chat_present: bool,
    expected_counts: Mapping[str, int],
    expected_fact_keys: Sequence[str],
    expected_model_keys: Sequence[str],
    expected_inference_keys: Sequence[str],
    required_visible_markers: Sequence[str],
    visible_content_contract_fingerprint: str = "",
) -> str:
    payload = {
        "compute_fingerprint": compute_fingerprint,
        "section_manifest": list(canonical_manifest),
        "mini_league_denominator_complete": bool(mini_league_denominator_complete),
        "mini_league_contract_state": mini_league_contract_state,
        "report_mode": report_mode,
        "weather_contract_state": weather_contract_state,
        "weather_required": bool(weather_required),
        "weather_direct_chat_present": bool(weather_direct_chat_present),
        "expected_counts": dict(expected_counts),
        "expected_fact_keys": list(expected_fact_keys),
        "expected_model_keys": list(expected_model_keys),
        "expected_inference_keys": list(expected_inference_keys),
        "required_visible_markers": list(required_visible_markers),
        "visible_content_contract_fingerprint": visible_content_contract_fingerprint,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def validate_pre_render_qa(
    *,
    compute_contract: Mapping[str, Any],
    section_manifest: Sequence[Mapping[str, Any]],
    mini_league_denominator_complete: bool,
    weather_required: bool = True,
    weather_direct_chat_present: bool = False,
    report_mode: str | None = None,
    weather_contract_state: str | None = None,
    visible_content_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate hard correctness while allowing truthful section degradation to render."""
    generated_section_ids = [
        str(row.get("section_id") or "").strip().upper()
        for row in section_manifest
        if str(row.get("section_id") or "").strip()
    ]

    (
        resolved_report_mode,
        resolved_weather_state,
        resolved_weather_required,
        resolved_weather_direct_present,
        weather_failure,
    ) = _normalize_weather_contract(
        report_mode=report_mode,
        weather_contract_state=weather_contract_state,
        weather_required=weather_required,
        weather_direct_chat_present=weather_direct_chat_present,
    )
    expected_section_ids = _expected_visible_catalog(
        resolved_report_mode,
        generated_section_ids,
    )
    (
        canonical_manifest,
        canonical_section_ids,
        missing_sections,
        duplicate_sections,
        partial_sections,
        partial_not_allowed_sections,
        invalid_section_states,
    ) = _canonical_section_manifest(
        section_manifest,
        expected_section_ids=expected_section_ids,
    )

    visible_content_validation = None
    visible_content_contract_fingerprint = ""
    section_degradations: list[dict[str, Any]] = []
    warnings: list[str] = []
    degraded_count_labels: list[str] = []
    degraded_compute_sections: list[str] = []
    visible_hard_failures: list[str] = []
    if visible_content_contract is not None:
        visible_content_validation = validate_v12_visible_content_contract(
            report_mode=resolved_report_mode,
            content_contract=visible_content_contract,
        )
        visible_content_contract_fingerprint = str(
            visible_content_validation.get("contract_fingerprint") or ""
        )
        section_degradations = [
            dict(row)
            for row in visible_content_validation.get("section_degradations", [])
            if isinstance(row, Mapping)
        ]
        warnings = [
            str(value)
            for value in visible_content_validation.get("warnings", [])
        ]
        degraded_count_labels = [
            str(value)
            for value in visible_content_validation.get("degraded_count_labels", [])
        ]
        degraded_compute_sections = [
            str(value)
            for value in visible_content_validation.get("degraded_compute_sections", [])
        ]
        visible_hard_failures = [
            f"VISIBLE_CONTENT_CONTRACT:{failure}"
            for failure in visible_content_validation.get("hard_failures", [])
        ]

    compute_failures = _compute_handoff_failures(
        compute_contract,
        degradable_count_labels=degraded_count_labels,
        degradable_compute_sections=degraded_compute_sections,
    )

    icon_degraded = any(
        str(row.get("section") or "") == "ICON+"
        for row in section_degradations
    )
    s14b_state = next(
        (
            str(row.get("status") or "").strip().upper()
            for row in canonical_manifest
            if str(row.get("section_id") or "").strip().upper() == "S14B"
        ),
        "MISSING",
    )
    if icon_degraded:
        mini_league_contract_state = "DEGRADED"
    elif mini_league_denominator_complete:
        mini_league_contract_state = "COMPLETE"
    elif s14b_state == "PARTIAL":
        mini_league_contract_state = "DEGRADED"
    else:
        mini_league_contract_state = "INCOMPLETE"

    hard_failures = list(compute_failures)
    if generated_section_ids != expected_section_ids:
        hard_failures.append("VISIBLE_CATALOG_MISMATCH")
    if canonical_section_ids != expected_section_ids and not missing_sections and not duplicate_sections:
        hard_failures.append("CANONICAL_CATALOG_MISMATCH")
    if missing_sections:
        hard_failures.append(f"MANDATORY_SECTIONS_MISSING={','.join(missing_sections)}")
    if duplicate_sections:
        hard_failures.append(f"SECTION_IDENTITY_DUPLICATE={','.join(duplicate_sections)}")
    if partial_not_allowed_sections:
        hard_failures.append(f"PARTIAL_NOT_ALLOWED={','.join(partial_not_allowed_sections)}")
    if invalid_section_states:
        hard_failures.append(f"SECTION_STATUS_INVALID={','.join(invalid_section_states)}")
    if mini_league_contract_state == "INCOMPLETE":
        hard_failures.append("MINI_LEAGUE_DENOMINATOR_INCOMPLETE")
    if weather_failure:
        hard_failures.append(weather_failure)
    hard_failures.extend(visible_hard_failures)
    hard_failures = list(dict.fromkeys(hard_failures))

    fact_model = compute_contract.get("FACT_MODEL")
    expected_fact_keys = (
        sorted(str(key) for key in fact_model.get("fact_keys", []))
        if isinstance(fact_model, Mapping)
        else []
    )
    expected_model_keys = (
        sorted(str(key) for key in fact_model.get("model_keys", []))
        if isinstance(fact_model, Mapping)
        else []
    )
    expected_inference_keys = (
        sorted(str(key) for key in fact_model.get("inference_keys", []))
        if isinstance(fact_model, Mapping)
        else []
    )
    expected_counts = _expected_visible_counts(resolved_report_mode)
    for label in degraded_count_labels:
        expected_counts.pop(label, None)
    required_visible_markers = _required_visible_markers(resolved_report_mode)
    compute_fingerprint = str(compute_contract.get("compute_fingerprint") or "")

    qa_passed = not hard_failures
    report_can_continue = qa_passed
    qa_severity = (
        "FAIL"
        if hard_failures
        else "DEGRADED"
        if section_degradations
        else "PASS"
    )
    token = (
        _render_contract_token(
            compute_fingerprint=compute_fingerprint,
            canonical_manifest=canonical_manifest,
            mini_league_denominator_complete=bool(mini_league_denominator_complete),
            mini_league_contract_state=mini_league_contract_state,
            report_mode=resolved_report_mode,
            weather_contract_state=resolved_weather_state,
            weather_required=resolved_weather_required,
            weather_direct_chat_present=resolved_weather_direct_present,
            expected_counts=expected_counts,
            expected_fact_keys=expected_fact_keys,
            expected_model_keys=expected_model_keys,
            expected_inference_keys=expected_inference_keys,
            required_visible_markers=required_visible_markers,
            visible_content_contract_fingerprint=visible_content_contract_fingerprint,
        )
        if qa_passed
        else None
    )
    next_action = (
        "RECOMPUTE"
        if compute_failures
        else "RENDER_REPORT"
        if qa_passed
        else "PRE_RENDER_RECOVERY"
    )

    return {
        "status": "PASS" if qa_passed else "FAIL",
        "qa_severity": qa_severity,
        "qa_stage": "PRE_RENDER",
        "qa_passed": qa_passed,
        "report_can_continue": report_can_continue,
        "render_allowed": report_can_continue,
        "post_render_required": report_can_continue,
        "delivery_ready": False,
        "report_state": "BUILDING" if report_can_continue else "QA_FAILED",
        "next_action": next_action,
        "legacy_fallback_allowed": False,
        "failures": hard_failures,
        "hard_failures": hard_failures,
        "section_degradations": section_degradations,
        "warnings": warnings,
        "compute_fingerprint": compute_fingerprint,
        "render_contract_token": token,
        "required_section_count": len(expected_section_ids),
        "manifest_section_count": len(section_manifest),
        "expected_section_ids": expected_section_ids,
        "generated_section_ids": generated_section_ids,
        "section_manifest": canonical_manifest,
        "missing_sections": missing_sections,
        "duplicate_sections": duplicate_sections,
        "partial_sections": partial_sections,
        "partial_not_allowed_sections": partial_not_allowed_sections,
        "invalid_section_states": invalid_section_states,
        "mini_league_denominator_complete": bool(mini_league_denominator_complete),
        "mini_league_contract_state": mini_league_contract_state,
        "report_mode": resolved_report_mode,
        "weather_contract_state": resolved_weather_state,
        "weather_required": resolved_weather_required,
        "weather_direct_chat_present": resolved_weather_direct_present,
        "expected_counts": expected_counts,
        "degraded_count_labels": degraded_count_labels,
        "expected_fact_keys": expected_fact_keys,
        "expected_model_keys": expected_model_keys,
        "expected_inference_keys": expected_inference_keys,
        "required_visible_markers": required_visible_markers,
        "visible_content_contract": (
            dict(visible_content_contract)
            if isinstance(visible_content_contract, Mapping)
            else None
        ),
        "visible_content_contract_fingerprint": visible_content_contract_fingerprint,
        "visible_content_validation": visible_content_validation,
    }


def validate_post_render_qa(
    *,
    pre_render_qa: Mapping[str, Any],
    rendered_body: str,
    rendered_section_ids: Sequence[str],
    rendered_section_states: Mapping[str, str],
    rendered_compute_fingerprint: str | None,
    render_contract_token: str | None,
    rendered_counts: Mapping[str, int],
    rendered_fact_keys: Sequence[str],
    rendered_model_keys: Sequence[str],
    rendered_mini_league_denominator_complete: bool,
    rendered_weather_direct_chat_present: bool = False,
    rendered_weather_contract_state: str | None = None,
    rendered_visible_content_contract: Mapping[str, Any] | None = None,
    truncated: bool,
) -> dict[str, Any]:
    """Verify both the actual visible body and renderer metadata against pre-render QA."""
    if not (
        pre_render_qa.get("status") == "PASS"
        and pre_render_qa.get("qa_stage") == "PRE_RENDER"
        and pre_render_qa.get("qa_passed") is True
        and pre_render_qa.get("render_allowed") is True
        and pre_render_qa.get("delivery_ready") is False
    ):
        return {
            "status": "BLOCKED",
            "qa_stage": "POST_RENDER",
            "qa_passed": False,
            "delivery_ready": False,
            "report_state": "QA_FAILED",
            "next_action": "PRE_RENDER_QA",
            "legacy_fallback_allowed": False,
            "failures": ["PRE_RENDER_QA_NOT_PASSED"],
            "hard_failures": ["PRE_RENDER_QA_NOT_PASSED"],
            "section_degradations": [],
            "warnings": [],
            "report_can_continue": False,
            "visible_body_validated": False,
        }

    expected_sections = list(pre_render_qa.get("expected_section_ids", []))
    rendered_sections = [str(section_id or "").strip().upper() for section_id in rendered_section_ids]
    rendered_counts_by_id = Counter(rendered_sections)
    duplicate_sections = sorted(
        (section_id for section_id, count in rendered_counts_by_id.items() if section_id and count > 1),
        key=_section_sort_key,
    )
    rendered_set = set(rendered_sections)
    expected_set = set(expected_sections)
    missing_sections = sorted(expected_set - rendered_set, key=_section_sort_key)
    unexpected_sections = sorted(rendered_set - expected_set, key=_section_sort_key)

    expected_section_states = {
        str(row.get("section_id") or "").strip().upper(): str(row.get("status") or "").strip().upper()
        for row in pre_render_qa.get("section_manifest", [])
        if str(row.get("section_id") or "").strip()
    }
    actual_section_states = {
        str(section_id or "").strip().upper(): str(status or "").strip().upper()
        for section_id, status in rendered_section_states.items()
    }
    unexpected_state_sections = sorted(set(actual_section_states) - expected_set, key=_section_sort_key)

    expected_compute_fingerprint = str(pre_render_qa.get("compute_fingerprint") or "")
    expected_counts = dict(pre_render_qa.get("expected_counts", {}))
    expected_fact_keys = sorted(str(key) for key in pre_render_qa.get("expected_fact_keys", []))
    expected_model_keys = sorted(str(key) for key in pre_render_qa.get("expected_model_keys", []))
    expected_inference_keys = sorted(str(key) for key in pre_render_qa.get("expected_inference_keys", []))
    required_visible_markers = [
        str(marker)
        for marker in pre_render_qa.get("required_visible_markers", [])
        if str(marker).strip()
    ]
    expected_report_mode = str(pre_render_qa.get("report_mode") or "LEGACY").strip().upper()
    expected_mini_league_state = str(
        pre_render_qa.get("mini_league_contract_state")
        or ("COMPLETE" if pre_render_qa.get("mini_league_denominator_complete") else "INCOMPLETE")
    ).strip().upper()
    expected_weather_state = str(
        pre_render_qa.get("weather_contract_state")
        or ("DIRECT_CHATGPT" if pre_render_qa.get("weather_direct_chat_present") else "MISSING")
    ).strip().upper()
    expected_weather_required = bool(pre_render_qa.get("weather_required", True))
    expected_weather_present = bool(pre_render_qa.get("weather_direct_chat_present", False))

    canonical_pre_manifest = [
        {
            "section_id": str(row.get("section_id") or "").strip().upper(),
            "status": str(row.get("status") or "").strip().upper(),
        }
        for row in pre_render_qa.get("section_manifest", [])
    ]
    recomputed_pre_token = _render_contract_token(
        compute_fingerprint=expected_compute_fingerprint,
        canonical_manifest=canonical_pre_manifest,
        mini_league_denominator_complete=bool(pre_render_qa.get("mini_league_denominator_complete")),
        mini_league_contract_state=expected_mini_league_state,
        report_mode=expected_report_mode,
        weather_contract_state=expected_weather_state,
        weather_required=expected_weather_required,
        weather_direct_chat_present=expected_weather_present,
        expected_counts=expected_counts,
        expected_fact_keys=expected_fact_keys,
        expected_model_keys=expected_model_keys,
        expected_inference_keys=expected_inference_keys,
        required_visible_markers=required_visible_markers,
        visible_content_contract_fingerprint=str(pre_render_qa.get("visible_content_contract_fingerprint") or ""),
    )
    stored_pre_token = pre_render_qa.get("render_contract_token")

    if rendered_weather_contract_state is not None:
        actual_weather_state = str(rendered_weather_contract_state or "MISSING").strip().upper() or "MISSING"
    elif expected_report_mode == "LEGACY":
        if rendered_weather_direct_chat_present:
            actual_weather_state = "DIRECT_CHATGPT"
        elif not expected_weather_required:
            actual_weather_state = "NOT_REQUIRED"
        else:
            actual_weather_state = "MISSING"
    else:
        actual_weather_state = "DIRECT_CHATGPT" if rendered_weather_direct_chat_present else "MISSING"

    visible_body = validate_visible_report_body(
        rendered_body=rendered_body,
        expected_section_ids=expected_sections,
        expected_counts=expected_counts,
        expected_fact_keys=expected_fact_keys,
        expected_model_keys=expected_model_keys,
        expected_inference_keys=expected_inference_keys,
        expected_weather_state=expected_weather_state,
        mini_league_denominator_complete_required=expected_mini_league_state == "COMPLETE",
        expected_mini_league_state=expected_mini_league_state,
        required_visible_markers=required_visible_markers,
    )

    section_degradations = [
        dict(row)
        for row in pre_render_qa.get("section_degradations", [])
        if isinstance(row, Mapping)
    ]
    degraded_sections = {
        str(row.get("section") or "")
        for row in section_degradations
    }
    visible_body_failures: list[str] = []
    for failure in visible_body["failures"]:
        if (
            "ALL15" in degraded_sections
            and str(failure).startswith("VISIBLE_COUNT_MISMATCH=ALL15_TACTICAL:")
        ):
            continue
        visible_body_failures.append(str(failure))
    failures: list[str] = visible_body_failures
    warnings = [
        str(value)
        for value in pre_render_qa.get("warnings", [])
    ]
    expected_visible_contract = pre_render_qa.get("visible_content_contract")
    if isinstance(expected_visible_contract, Mapping):
        actual_visible_contract = (
            rendered_visible_content_contract
            if isinstance(rendered_visible_content_contract, Mapping)
            else expected_visible_contract
        )
        rendered_contract_validation = validate_v12_visible_content_contract(
            report_mode=expected_report_mode,
            content_contract=actual_visible_contract,
        )
        if rendered_contract_validation.get("status") != "PASS":
            failures.extend(
                f"VISIBLE_CONTENT_CONTRACT:{failure}"
                for failure in rendered_contract_validation.get("hard_failures", [])
            )
        section_degradations = [
            dict(row)
            for row in rendered_contract_validation.get("section_degradations", [])
            if isinstance(row, Mapping)
        ]
        warnings = [
            str(value)
            for value in rendered_contract_validation.get("warnings", [])
        ]
        if _content_fingerprint(actual_visible_contract) != str(pre_render_qa.get("visible_content_contract_fingerprint") or ""):
            failures.append("VISIBLE_CONTENT_CONTRACT_FINGERPRINT_MISMATCH")
        failures.extend(
            _validate_v12_rendered_body(
                report_mode=expected_report_mode,
                rendered_body=rendered_body,
                content_contract=actual_visible_contract,
            )
        )
    if stored_pre_token != recomputed_pre_token:
        failures.append("PRE_RENDER_CONTRACT_TOKEN_INVALID")
    if truncated:
        failures.append("RENDER_TRUNCATED")
    if missing_sections:
        failures.append(f"RENDER_SECTIONS_MISSING={','.join(missing_sections)}")
    if duplicate_sections:
        failures.append(f"RENDER_SECTION_DUPLICATE={','.join(duplicate_sections)}")
    if unexpected_sections:
        failures.append(f"RENDER_SECTION_UNEXPECTED={','.join(unexpected_sections)}")
    if rendered_sections != expected_sections:
        failures.append("SECTION_SEQUENCE_MISMATCH")

    for section_id in expected_sections:
        expected_state = expected_section_states.get(section_id, "<missing>")
        actual_state = actual_section_states.get(section_id, "<missing>")
        if actual_state != expected_state:
            failures.append(f"SECTION_STATUS_MISMATCH={section_id}:{actual_state}!={expected_state}")
    if unexpected_state_sections:
        failures.append(f"SECTION_STATUS_UNEXPECTED={','.join(unexpected_state_sections)}")

    if rendered_compute_fingerprint != expected_compute_fingerprint:
        failures.append("COMPUTE_FINGERPRINT_MISMATCH")
    if render_contract_token != recomputed_pre_token:
        failures.append("RENDER_CONTRACT_TOKEN_MISMATCH")

    for label, target in expected_counts.items():
        actual = rendered_counts.get(label)
        if actual != target:
            failures.append(f"COUNT_MISMATCH={label}:{actual}!={target}")

    for degradation in section_degradations:
        section = str(degradation.get("section") or "")
        label = _SECTION_TO_RENDER_COUNT_LABEL.get(section)
        if not label:
            continue
        expected_available = degradation.get("available_count")
        actual_available = rendered_counts.get(label)
        if actual_available is None:
            failures.append(f"DEGRADED_RENDER_COUNT_MISSING={section}")
            continue
        try:
            if int(actual_available) != int(expected_available):
                failures.append(
                    f"DEGRADED_RENDER_COUNT_MISMATCH={section}:{actual_available}!={expected_available}"
                )
        except (TypeError, ValueError):
            failures.append(f"DEGRADED_RENDER_COUNT_INVALID={section}")

    actual_fact_keys = sorted(str(key) for key in rendered_fact_keys)
    actual_model_keys = sorted(str(key) for key in rendered_model_keys)
    if set(actual_fact_keys) & set(actual_model_keys):
        failures.append("FACT_MODEL_BLEED")
    if actual_fact_keys != expected_fact_keys:
        failures.append("FACT_KEYS_MISMATCH")
    if actual_model_keys != expected_model_keys:
        failures.append("MODEL_KEYS_MISMATCH")

    expected_mini_complete = expected_mini_league_state == "COMPLETE"
    if bool(rendered_mini_league_denominator_complete) != expected_mini_complete:
        failures.append(
            "MINI_LEAGUE_METADATA_STATE_MISMATCH="
            f"{bool(rendered_mini_league_denominator_complete)}!={expected_mini_complete}"
        )
    if actual_weather_state != expected_weather_state:
        if (
            expected_report_mode == "LEGACY"
            and expected_weather_required
            and actual_weather_state == "MISSING"
        ):
            failures.append("MANDATORY_WEATHER_MISSING")
        else:
            failures.append(
                f"WEATHER_CONTRACT_STATE_MISMATCH={actual_weather_state}!={expected_weather_state}"
            )

    hard_failures = list(dict.fromkeys(failures))
    qa_passed = not hard_failures
    report_can_continue = qa_passed
    qa_severity = (
        "FAIL"
        if hard_failures
        else "DEGRADED"
        if section_degradations
        else "PASS"
    )
    return {
        "status": "PASS" if qa_passed else "FAIL",
        "qa_severity": qa_severity,
        "qa_stage": "POST_RENDER",
        "qa_passed": qa_passed,
        "report_can_continue": report_can_continue,
        "delivery_ready": False,
        "report_state": "BUILDING" if report_can_continue else "QA_FAILED",
        "next_action": "BUILD_DELIVERY_PROOF" if report_can_continue else "RENDER_RECOVERY",
        "legacy_fallback_allowed": False,
        "failures": hard_failures,
        "hard_failures": hard_failures,
        "section_degradations": section_degradations,
        "warnings": warnings,
        "compute_fingerprint": expected_compute_fingerprint,
        "render_contract_token": recomputed_pre_token,
        "expected_section_ids": expected_sections,
        "rendered_section_ids": rendered_sections,
        "expected_section_states": expected_section_states,
        "rendered_section_states": actual_section_states,
        "missing_sections": missing_sections,
        "duplicate_sections": duplicate_sections,
        "unexpected_sections": unexpected_sections,
        "unexpected_state_sections": unexpected_state_sections,
        "expected_counts": expected_counts,
        "rendered_counts": dict(rendered_counts),
        "expected_fact_keys": expected_fact_keys,
        "expected_model_keys": expected_model_keys,
        "expected_inference_keys": expected_inference_keys,
        "required_visible_markers": required_visible_markers,
        "rendered_fact_keys": actual_fact_keys,
        "rendered_model_keys": actual_model_keys,
        "mini_league_denominator_complete": bool(rendered_mini_league_denominator_complete),
        "mini_league_contract_state": expected_mini_league_state,
        "report_mode": expected_report_mode,
        "weather_contract_state": actual_weather_state,
        "weather_required": expected_weather_required,
        "weather_direct_chat_present": actual_weather_state in {"DIRECT_CHATGPT", "MATCH_CURRENT"},
        "truncated": bool(truncated),
        "visible_body_validated": visible_body["status"] == "PASS",
        "visible_body_sha256": visible_body["body_sha256"],
        "visible_section_ids": visible_body["section_ids"],
        "visible_counts": visible_body["counts"],
        "visible_fact_keys": visible_body["fact_keys"],
        "visible_model_keys": visible_body["model_keys"],
        "visible_inference_keys": visible_body["inference_keys"],
        "visible_weather_contract_state": visible_body["weather_contract_state"],
        "visible_mini_league_denominator_complete": visible_body[
            "mini_league_denominator_complete"
        ],
        "visible_mini_league_contract_state": visible_body["mini_league_contract_state"],
    }


def validate_v12_decision_semantics(
    decision_proof: Mapping[str, Any] | None,
    *,
    serious_decision_required: bool,
) -> dict[str, Any]:
    """Validate V12 mathematics in the existing report-plane QA subsystem.

    A semantic failure degrades the affected decision scope but remains
    fail-operational for the due visible report.
    """
    if not serious_decision_required and not decision_proof:
        return {
            "status": "NOT_REQUIRED",
            "canonical_v12_compliant": None,
            "report_can_continue": True,
            "failures": [],
            "warnings": [],
        }

    proof = dict(decision_proof or {})
    failures: list[str] = []
    warnings: list[str] = []
    if not proof:
        failures.append("V12_DECISION_PROOF_MISSING")
        return {
            "status": "PARTIAL",
            "canonical_v12_compliant": False,
            "report_can_continue": True,
            "failures": failures,
            "warnings": ["SERIOUS_DECISION_SCOPE_MUST_RENDER_DEGRADED"],
        }

    authority = proof.get("canonical_authority")
    if not isinstance(authority, Mapping):
        failures.append("V12__V12_CANONICAL_AUTHORITY_PROOF_MISSING")
    else:
        if authority.get("path") != _V12_CANONICAL_AUTHORITY:
            failures.append("V12__V12_CANONICAL_AUTHORITY_PATH_INVALID")
        if not _is_sha256(authority.get("sha256")):
            failures.append("V12__V12_CANONICAL_AUTHORITY_SHA256_INVALID")
        if not str(authority.get("version") or "").strip():
            failures.append("V12__V12_CANONICAL_AUTHORITY_VERSION_MISSING")

    try:
        universe_n = int(proof.get("official_fpl_universe_denominator") or 0)
        evaluated_n = int(proof.get("evaluated_denominator") or -1)
    except (TypeError, ValueError):
        universe_n, evaluated_n = 0, -1
    if universe_n <= 0 or evaluated_n < 0 or evaluated_n > universe_n:
        failures.append("V12_UNIVERSE_DENOMINATOR_INVALID")

    gate0 = proof.get("gate0")
    if not isinstance(gate0, Mapping) or gate0.get("status") != "PASS":
        failures.append("V12_GATE0_NOT_PASS")

    football = proof.get("football_score")
    if not isinstance(football, Mapping):
        failures.append("V12_FOOTBALL_SCORE_PROOF_MISSING")
    else:
        weights = football.get("weights")
        if not isinstance(weights, Mapping):
            failures.append("V12_20_25_30_25_WEIGHTS_MISSING")
        else:
            for key, expected in _V12_CANONICAL_WEIGHTS.items():
                try:
                    actual = float(weights.get(key))
                except (TypeError, ValueError):
                    actual = -1.0
                if abs(actual - expected) > 1e-12:
                    failures.append(f"V12_WEIGHT_MISMATCH={key}")
        components = football.get("component_scores")
        if not isinstance(components, Mapping) or set(components) != set(_V12_CANONICAL_WEIGHTS):
            failures.append("V12_COMPONENT_SCORE_PROOF_INVALID")
        if football.get("transfer_economics_included") is not False:
            failures.append("V12_ECONOMICS_DOUBLE_COUNT_RISK")

    lineage = proof.get("bayesian_shrinkage_lineage")
    if not isinstance(lineage, Mapping) or not lineage:
        failures.append("V12_BAYESIAN_SHRINKAGE_LINEAGE_MISSING")

    probability = proof.get("probability_state")
    if not isinstance(probability, Mapping):
        failures.append("V12_PROBABILITY_STATE_MISSING")
    else:
        unconditional = probability.get("unconditional")
        conditional = probability.get("conditional")
        if not isinstance(unconditional, Mapping) or not isinstance(conditional, Mapping):
            failures.append("V12_HIERARCHICAL_PROBABILITY_SEMANTICS_MISSING")
        else:
            for key in (
                "p_available",
                "p_start",
                "p_bench",
                "p_cameo",
                "p_late_cameo",
                "p_dnp",
            ):
                if unconditional.get(key) is None:
                    failures.append(f"V12_{key.upper()}_MISSING")
            for key in (
                "p_start_given_available",
                "p_bench_given_available_not_start",
                "p_cameo_given_bench",
                "p_late_cameo_given_cameo",
            ):
                if conditional.get(key) is None:
                    failures.append(f"V12_{key.upper()}_MISSING")
        if probability.get("bench_is_overlapping_state") is not True:
            failures.append("V12_BENCH_OVERLAP_SEMANTICS_MISSING")

    xmins = proof.get("xmins_distribution")
    if not isinstance(xmins, Mapping) or xmins.get("mean") is None:
        failures.append("V12_XMINS_DISTRIBUTION_MISSING")
    else:
        states = {
            str(row.get("state") or "").upper()
            for row in xmins.get("states") or []
            if isinstance(row, Mapping)
        }
        if not {"START", "CAMEO", "LATE_CAMEO", "ZERO_MINUTES"} <= states:
            failures.append("V12_XMINS_STATE_MIXTURE_INCOMPLETE")

    horizons = proof.get("horizons")
    horizon_rows = (
        horizons.get("horizons")
        if isinstance(horizons, Mapping)
        else None
    )
    if not isinstance(horizon_rows, Mapping):
        failures.append("V12_HORIZON_PROOF_MISSING")
    else:
        if not {"GW+1", "3GW", "5GW"} <= set(horizon_rows):
            failures.append("V12_GW1_3_5_HORIZONS_MISSING")
        route_type = str(proof.get("route_type") or "").upper()
        if route_type in {"ONE_GW_PUNT", "RENTAL", "EXIT"} and "2GW" not in horizon_rows:
            failures.append("V12_2GW_RENTAL_EXIT_HORIZON_MISSING")

    economics = proof.get("transfer_economics")
    if not isinstance(economics, Mapping):
        failures.append("V12_TRANSFER_ECONOMICS_MISSING")
    else:
        if economics.get("decision_chain_stage") != "TRANSFER_ECONOMICS":
            failures.append("V12_TRANSFER_ECONOMICS_STAGE_INVALID")
        if economics.get("included_in_football_score") is not False:
            failures.append("V12_TRANSFER_ECONOMICS_NOT_DOWNSTREAM")
        if economics.get("ft_shadow_semantics") == "LEGACY_HEURISTIC_NOT_CANONICAL":
            warnings.append("LEGACY_FT_HEURISTIC_PRESENT_NOT_CANONICAL_FT_SHADOW")

    robustness = proof.get("robustness")
    if not isinstance(robustness, Mapping) or not robustness:
        failures.append("V12_ROBUSTNESS_PROOF_MISSING")
    else:
        if robustness.get("expected_regret") is None and proof.get("expected_regret") is None:
            failures.append("V12_EXPECTED_REGRET_MISSING")
        if robustness.get("lineup_relevant") is True:
            for key in (
                "conditional_floor",
                "upper_tail",
                "p_outperform",
                "lineup_optionality",
                "auto_sub_preservation_value",
                "cameo_auto_sub_blocking_cost",
            ):
                if robustness.get(key) is None:
                    failures.append(f"V12_LINEUP_{key.upper()}_MISSING")
    if proof.get("information_value_of_waiting") is None:
        failures.append("V12_INFORMATION_VALUE_OF_WAITING_MISSING")

    overlay = proof.get("icon_overlay")
    if isinstance(overlay, Mapping) and overlay:
        if overlay.get("applied_after_football_optimal_baseline") is not True:
            failures.append("V12_ICON_OVERLAY_ORDER_INVALID")

    search_authority = str(proof.get("search_authority") or "").upper()
    optimization_claim = str(proof.get("optimization_claim") or "").upper()
    if search_authority not in {"FULL", "PARTIAL"}:
        failures.append("V12_SEARCH_AUTHORITY_INVALID")
    if search_authority == "PARTIAL" and optimization_claim == "FULL_UNIVERSE_OPTIMIZED":
        failures.append("V12_PARTIAL_SEARCH_FALSE_FULL_OPTIMIZATION_CLAIM")

    mc = proof.get("monte_carlo")
    if not isinstance(mc, Mapping):
        failures.append("V12_MONTE_CARLO_STATE_MISSING")
    else:
        state = str(mc.get("execution_state") or "").upper()
        if state == "EXECUTED":
            if mc.get("canonical_pass") is not True:
                failures.append("V12_MC_EXECUTED_WITHOUT_CANONICAL_PASS")
            try:
                actual_paths = int(mc.get("actual_paths") or 0)
            except (TypeError, ValueError):
                actual_paths = 0
            if actual_paths < 500000:
                failures.append("V12_MC_ACTUAL_PATHS_LT_500000")
            if mc.get("correlated") is not True:
                failures.append("V12_MC_CORRELATED_FLAG_MISSING")
            for key in (
                "method",
                "correlation_model",
                "seed_policy",
                "input_snapshot_ids",
                "input_freshness",
                "convergence_evidence",
                "output_fingerprint",
            ):
                if mc.get(key) in (None, "", {}, []):
                    failures.append(f"V12_MC_{key.upper()}_MISSING")
        elif state == "NOT_RUN":
            if not str(mc.get("reason") or "").strip():
                failures.append("V12_MC_NOT_RUN_REASON_MISSING")
        elif state == "PARTIAL":
            if not str(mc.get("degradation_reason") or "").strip():
                failures.append("V12_MC_PARTIAL_REASON_MISSING")
        else:
            failures.append("V12_MC_EXECUTION_STATE_INVALID")

    execution = proof.get("execution_provenance")
    if not isinstance(execution, Mapping) or not execution:
        failures.append("V12_EXECUTION_PROVENANCE_MISSING")
    elif execution.get("repository_python_executed") is True:
        if not execution.get("actual_execution_evidence"):
            failures.append("V12_PYTHON_EXECUTION_CLAIM_UNPROVEN")

    if failures:
        warnings.append("SERIOUS_DECISION_SCOPE_MUST_RENDER_PARTIAL_OR_DEGRADED")
    return {
        "status": "PASS" if not failures else "PARTIAL",
        "canonical_v12_compliant": not failures,
        "report_can_continue": True,
        "failures": list(dict.fromkeys(failures)),
        "warnings": list(dict.fromkeys(warnings)),
        "search_authority": search_authority or None,
        "optimization_claim": optimization_claim or None,
        "mc_execution_state": (
            str(mc.get("execution_state") or "").upper()
            if isinstance(mc, Mapping)
            else None
        ),
    }


# P0.5 strict Deadline/Final report-plane gates. These wrappers deliberately reuse
# the existing R6 validators above rather than creating a second QA implementation.
_P05_CONTRACT_VERSION = "P0.5"


def _p05_timestamp(value: Any, *, label: str):
    from .temporal import try_parse_timestamp
    parsed = try_parse_timestamp(value)
    if parsed is None:
        raise ValueError(f"{label} must be timezone-aware ISO-8601")
    return parsed


def _p05_gate_token(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _p05_weather_evidence(
    weather_evidence: Mapping[str, Any],
) -> tuple[bool, str, list[str], dict[str, Any]]:
    evidence = dict(weather_evidence or {})
    attempted = evidence.get("weather_attempted") is True
    result = str(evidence.get("weather_result") or "").strip().upper()
    source = str(evidence.get("source") or "").strip()
    provenance = evidence.get("provenance")
    evaluated_at = evidence.get("evaluated_at")
    failures: list[str] = []
    if not attempted:
        failures.append("WEATHER_NOT_ATTEMPTED")
    if result not in {"AVAILABLE", "DEGRADED_AFTER_ATTEMPT"}:
        failures.append("WEATHER_RESULT_INVALID")
    if not source:
        failures.append("WEATHER_SOURCE_MISSING")
    if provenance in (None, "", {}, []):
        failures.append("WEATHER_PROVENANCE_MISSING")
    try:
        _p05_timestamp(evaluated_at, label="weather.evaluated_at")
    except ValueError:
        failures.append("WEATHER_EVALUATED_AT_INVALID")
    state = "DIRECT_CHATGPT" if result == "AVAILABLE" else "SOURCE_DEGRADED"
    return not failures, state, failures, {
        "weather_attempted": attempted,
        "weather_result": result or None,
        "source": source or None,
        "provenance": provenance,
        "evaluated_at": evaluated_at,
    }


def validate_p05_pre_render_qa(
    *,
    report_slot_id: str,
    evaluated_at: str,
    compute_contract: Mapping[str, Any],
    section_manifest: Sequence[Mapping[str, Any]],
    mini_league_denominator_complete: bool,
    report_mode: str,
    decision_context: Mapping[str, Any],
    prefetch_readiness: Mapping[str, Any],
    weather_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Strict P0.5 PRE_RENDER_QA for canonical Deadline/Final report occurrences."""
    slot_id = str(report_slot_id or "").strip()
    failures: list[str] = []
    try:
        evaluated = _p05_timestamp(evaluated_at, label="evaluated_at")
    except ValueError:
        evaluated = None
        failures.append("EVALUATED_AT_INVALID")
    if not slot_id or "|" not in slot_id:
        failures.append("REPORT_SLOT_ID_INVALID")

    context = dict(decision_context or {})
    context_pass = bool(
        context.get("status") == "PASS"
        and context.get("context_kind") == "CURRENT_DECISION_CONTEXT"
        and context.get("report_slot_id") == slot_id
        and context.get("context_fingerprint")
    )
    if not context_pass:
        failures.append("DECISION_CONTEXT_GATE_FAILED")

    prefetch = dict(prefetch_readiness or {})
    prefetch_identity_pass = bool(
        prefetch.get("ready") is True
        and prefetch.get("report_kind_match") is True
        and prefetch.get("target_logical_slot_match") is True
        and prefetch.get("scope_match") is True
        and str(prefetch.get("selected_report_prefetch_run_id") or "").strip()
    )
    if not prefetch_identity_pass:
        failures.append("PREFETCH_IDENTITY_GATE_FAILED")

    weather_pass, weather_state, weather_failures, normalized_weather = _p05_weather_evidence(
        weather_evidence
    )
    failures.extend(weather_failures)

    base = validate_pre_render_qa(
        compute_contract=compute_contract,
        section_manifest=section_manifest,
        mini_league_denominator_complete=mini_league_denominator_complete,
        weather_required=True,
        weather_direct_chat_present=weather_state == "DIRECT_CHATGPT",
        report_mode=report_mode,
        weather_contract_state=weather_state,
    )
    failures.extend(
        failure for failure in base.get("failures", []) if failure not in failures
    )

    mandatory_scope_pass = bool(
        compute_contract.get("status") == "PASS"
        and compute_contract.get("compute_ready") is True
        and not base.get("missing_sections")
        and not base.get("duplicate_sections")
    )
    semantic_acceptance = compute_contract.get("MANDATORY_SEMANTIC")
    semantic_required = isinstance(semantic_acceptance, Mapping)
    semantic_acceptance_pass = bool(
        not semantic_required
        or (
            semantic_acceptance.get("status") == "PASS"
            and semantic_acceptance.get("report_contract_pass") is True
            and semantic_acceptance.get("can_emit") is True
        )
    )
    decision_proof = compute_contract.get("DECISION_PROOF")
    serious_decision_required = bool(
        compute_contract.get("serious_decision_required")
        or context.get("serious_decision_required")
        or isinstance(decision_proof, Mapping)
    )
    v12_semantic = validate_v12_decision_semantics(
        decision_proof if isinstance(decision_proof, Mapping) else None,
        serious_decision_required=serious_decision_required,
    )
    v12_report_continuation_pass = v12_semantic.get("report_can_continue") is True
    input_completeness_pass = bool(
        mandatory_scope_pass
        and semantic_acceptance_pass
        and v12_report_continuation_pass
        and all(
            isinstance(compute_contract.get(label), Mapping)
            and compute_contract[label].get("status") == "PASS"
            for label in ("OUR15", "XI", "BENCH", "WATCHLIST20", "RISE20", "FALL20")
        )
    )
    if not mandatory_scope_pass:
        failures.append("MANDATORY_SCOPE_GATE_FAILED")
    if semantic_required and not semantic_acceptance_pass:
        failures.append("MANDATORY_SEMANTIC_ACCEPTANCE_FAILED")
    semantic_warnings = list(v12_semantic.get("warnings") or [])
    if v12_semantic.get("status") == "PARTIAL":
        semantic_warnings.extend(
            f"V12_SEMANTIC:{failure}"
            for failure in (v12_semantic.get("failures") or [])
        )
    if not input_completeness_pass:
        failures.append("INPUT_COMPLETENESS_GATE_FAILED")
    failures = list(dict.fromkeys(failures))
    qa_passed = bool(base.get("status") == "PASS" and not failures)

    gate_payload = {
        "contract_version": _P05_CONTRACT_VERSION,
        "report_slot_id": slot_id,
        "evaluated_at": evaluated_at,
        "base_render_contract_token": base.get("render_contract_token"),
        "decision_context_fingerprint": context.get("context_fingerprint"),
        "active_scenario_ids": list(context.get("active_scenario_ids") or []),
        "prefetch_identity": prefetch.get("selected_report_prefetch_run_id"),
        "prefetch_slot": prefetch.get("selected_target_logical_report_slot"),
        "weather_attempt": normalized_weather,
        "mandatory_scope_gate_pass": mandatory_scope_pass,
        "input_completeness_pass": input_completeness_pass,
        "mandatory_semantic_acceptance": (
            dict(semantic_acceptance) if semantic_required else {"status": "LEGACY_NOT_PROVIDED"}
        ),
        "v12_decision_semantic": dict(v12_semantic),
    }
    strict_token = _p05_gate_token(gate_payload) if qa_passed else None

    return {
        **base,
        "status": "PASS" if qa_passed else "FAIL",
        "qa_stage": "PRE_RENDER",
        "qa_passed": qa_passed,
        "render_allowed": qa_passed,
        "can_render": qa_passed,
        "can_emit": False,
        "report_contract_pass": False,
        "report_slot_id": slot_id,
        "evaluated_at": evaluated_at,
        "contract_version": _P05_CONTRACT_VERSION,
        "mandatory_scope_gate": {"status": "PASS" if mandatory_scope_pass else "FAIL"},
        "input_completeness": {"status": "PASS" if input_completeness_pass else "FAIL"},
        "mandatory_semantic_acceptance": (
            dict(semantic_acceptance)
            if semantic_required
            else {"status": "LEGACY_NOT_PROVIDED", "report_contract_pass": None, "can_emit": None}
        ),
        "v12_decision_semantic": dict(v12_semantic),
        "v12_decision_canonical_pass": v12_semantic.get("canonical_v12_compliant") is True,
        "decision_context": context,
        "prefetch_identity": {
            "status": "PASS" if prefetch_identity_pass else "FAIL",
            "report_prefetch_run_id": prefetch.get("selected_report_prefetch_run_id"),
            "logical_slot": prefetch.get("selected_target_logical_report_slot"),
        },
        "weather_attempt": normalized_weather,
        "failed_checks": failures,
        "failures": failures,
        "warnings": list(dict.fromkeys(semantic_warnings)),
        "evidence": {
            "compute_fingerprint": base.get("compute_fingerprint"),
            "render_contract_token": base.get("render_contract_token"),
            "decision_context_fingerprint": context.get("context_fingerprint"),
            "prefetch_refresh_identity": prefetch.get("refresh_identity"),
        },
        "p05_gate_payload": gate_payload,
        "p05_render_gate_token": strict_token,
        "strict_report_plane_contract": True,
        "next_action": "RENDER_REPORT" if qa_passed else "PRE_RENDER_RECOVERY",
    }


def validate_p05_post_render_qa(
    *,
    pre_render_qa: Mapping[str, Any],
    report_slot_id: str,
    evaluated_at: str,
    render_completed_at: str,
    rendered_report_mode: str,
    rendered_body: str,
    rendered_section_ids: Sequence[str],
    rendered_section_states: Mapping[str, str],
    rendered_compute_fingerprint: str | None,
    render_contract_token: str | None,
    rendered_counts: Mapping[str, int],
    rendered_fact_keys: Sequence[str],
    rendered_model_keys: Sequence[str],
    rendered_mini_league_denominator_complete: bool,
    rendered_weather_direct_chat_present: bool = False,
    rendered_weather_contract_state: str | None = None,
    truncated: bool = False,
    status_only: bool = False,
) -> dict[str, Any]:
    """Strict P0.5 POST_RENDER_QA and the sole CAN_EMIT gate."""
    base = validate_post_render_qa(
        pre_render_qa=pre_render_qa,
        rendered_body=rendered_body,
        rendered_section_ids=rendered_section_ids,
        rendered_section_states=rendered_section_states,
        rendered_compute_fingerprint=rendered_compute_fingerprint,
        render_contract_token=render_contract_token,
        rendered_counts=rendered_counts,
        rendered_fact_keys=rendered_fact_keys,
        rendered_model_keys=rendered_model_keys,
        rendered_mini_league_denominator_complete=rendered_mini_league_denominator_complete,
        rendered_weather_direct_chat_present=rendered_weather_direct_chat_present,
        rendered_weather_contract_state=rendered_weather_contract_state,
        truncated=truncated,
    )
    failures = list(base.get("failures", []))
    expected_slot = str(pre_render_qa.get("report_slot_id") or "").strip()
    if str(report_slot_id or "").strip() != expected_slot:
        failures.append("REPORT_SLOT_ID_MISMATCH")
    expected_mode = str(pre_render_qa.get("report_mode") or "").strip().upper()
    if str(rendered_report_mode or "").strip().upper() != expected_mode:
        failures.append("REPORT_KIND_MISMATCH")
    if status_only:
        failures.append("STATUS_ONLY_NOT_CANONICAL_REPORT")

    v12_semantic = pre_render_qa.get("v12_decision_semantic")
    if isinstance(v12_semantic, Mapping) and v12_semantic.get("status") == "PARTIAL":
        body_upper = str(rendered_body or "").upper()
        if "PARTIAL" not in body_upper and "DEGRADED" not in body_upper:
            failures.append("V12_PARTIAL_DECISION_SCOPE_NOT_VISIBLY_LABELLED")

    semantic_acceptance = pre_render_qa.get("mandatory_semantic_acceptance")
    if (
        isinstance(semantic_acceptance, Mapping)
        and semantic_acceptance.get("status") not in {"PASS", "LEGACY_NOT_PROVIDED"}
    ):
        failures.append("MANDATORY_SEMANTIC_ACCEPTANCE_FAILED")

    stored_payload = pre_render_qa.get("p05_gate_payload")
    stored_token = pre_render_qa.get("p05_render_gate_token")
    if not isinstance(stored_payload, Mapping) or not stored_token:
        failures.append("P05_PRE_RENDER_GATE_MISSING")
    elif _p05_gate_token(stored_payload) != stored_token:
        failures.append("P05_PRE_RENDER_GATE_TAMPERED")

    context = pre_render_qa.get("decision_context")
    active_scenarios = (
        list(context.get("active_scenarios") or [])
        if isinstance(context, Mapping)
        else []
    )
    body_lower = str(rendered_body or "").lower()
    missing_active: list[str] = []
    invalid_active: list[str] = []
    for row in active_scenarios:
        if str(row.get("state") or "").strip().upper() != "CONTEMPLATED":
            invalid_active.append(str(row.get("scenario_id") or "<missing>"))
            continue
        marker = str(row.get("visible_marker") or row.get("scenario_id") or "").strip()
        if not marker or marker.lower() not in body_lower:
            missing_active.append(str(row.get("scenario_id") or marker or "<missing>"))
    if invalid_active:
        failures.append(f"ACTIVE_SCENARIO_STATE_INVALID={','.join(invalid_active)}")
    if missing_active:
        failures.append(f"ACTIVE_SCENARIOS_MISSING={','.join(missing_active)}")

    try:
        pre_time = _p05_timestamp(pre_render_qa.get("evaluated_at"), label="pre_render.evaluated_at")
        render_time = _p05_timestamp(render_completed_at, label="render_completed_at")
        post_time = _p05_timestamp(evaluated_at, label="evaluated_at")
        if not (pre_time <= render_time <= post_time):
            failures.append("RENDER_QA_CHRONOLOGY_INVALID")
    except ValueError:
        failures.append("RENDER_QA_TIMESTAMP_INVALID")

    failures = list(dict.fromkeys(failures))
    passed = bool(base.get("status") == "PASS" and not failures)
    return {
        **base,
        "status": "PASS" if passed else "FAIL",
        "qa_stage": "POST_RENDER",
        "qa_passed": passed,
        "report_slot_id": expected_slot,
        "evaluated_at": evaluated_at,
        "render_completed_at": render_completed_at,
        "contract_version": _P05_CONTRACT_VERSION,
        "failed_checks": failures,
        "failures": failures,
        "warnings": [],
        "provenance": {
            "compute_fingerprint": pre_render_qa.get("compute_fingerprint"),
            "render_contract_token": pre_render_qa.get("render_contract_token"),
            "p05_render_gate_token": stored_token,
        },
        "mandatory_scope_gate_pass": pre_render_qa.get("mandatory_scope_gate", {}).get("status") == "PASS",
        "input_completeness_pass": pre_render_qa.get("input_completeness", {}).get("status") == "PASS",
        "mandatory_semantic_acceptance_pass": (
            not isinstance(semantic_acceptance, Mapping)
            or semantic_acceptance.get("status") in {"PASS", "LEGACY_NOT_PROVIDED"}
        ),
        "v12_decision_semantic": (
            dict(v12_semantic) if isinstance(v12_semantic, Mapping) else {"status": "NOT_REQUIRED"}
        ),
        "v12_decision_canonical_pass": (
            isinstance(v12_semantic, Mapping)
            and v12_semantic.get("canonical_v12_compliant") is True
        ),
        "decision_context_gate_pass": pre_render_qa.get("decision_context", {}).get("status") == "PASS",
        "prefetch_identity_pass": pre_render_qa.get("prefetch_identity", {}).get("status") == "PASS",
        "weather_attempt_gate_pass": pre_render_qa.get("weather_attempt", {}).get("weather_attempted") is True,
        "pre_render_qa_pass": pre_render_qa.get("status") == "PASS",
        "post_render_qa_pass": passed,
        "report_contract_pass": passed,
        "can_emit": passed and not status_only,
        "visible_emitted": False,
        "status_only": bool(status_only),
        "active_scenario_ids_expected": list(
            pre_render_qa.get("decision_context", {}).get("active_scenario_ids") or []
        ),
        "active_scenario_ids_missing": missing_active,
        "next_action": "BUILD_DELIVERY_PROOF" if passed else "RENDER_RECOVERY",
    }
