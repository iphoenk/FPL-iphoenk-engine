from __future__ import annotations

"""Deterministic V12 runtime conformance helpers.

This module is downstream report-plane logic only. It does not acquire/publish V6,
change methodology, or become authority. Canonical V12 remains authoritative.
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

ALLOWED_OPERATIONAL_ACTIONS = frozenset({"WAIT", "PREPARE", "ACT"})
CONTENT_SEVERITIES = frozenset({"PASS", "DEGRADED", "FAIL"})
DEGRADED_STATES = frozenset({"PARTIAL", "DEGRADED", "UNAVAILABLE"})
EXECUTION_STATES = frozenset({"EXECUTED", "NOT_EXECUTED"})


class RuntimeConformanceError(ValueError):
    pass


def _parse_iso(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise RuntimeConformanceError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeConformanceError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RuntimeConformanceError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


V12_CANONICAL_PATH = "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
V12_STATE_PATH = "control/fpl_master_v12/FPL_MASTER_STATE_V12.json"
CORE_TRANSPORT = "ISSUE_431_EXISTING_GOVERNED_TRANSPORT"
CORE_REASON = "chatgpt_hourly_master"
LEGACY_LIBRARY_AUTHORITY_BASENAMES = frozenset(
    {
        "FPL_MASTER_RUNTIME_CONTRACT.txt",
        "FPL_MASTER_RUNTIME_CONTRACT_P04_FINAL.txt",
        "FPL_MASTER_SPEC_V11.txt",
        "FPL_MASTER_SPEC_V11(1).txt",
        "FPL_MASTER_SPEC_V11_P04_FINAL.txt",
        "ACTIVE_DECISION_CONTEXT.json",
    }
)


def _parse_local_occurrence(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise RuntimeConformanceError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeConformanceError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RuntimeConformanceError(f"{label} must be timezone-aware")
    return parsed


def plan_hourly_core_upkeep(
    *,
    report_occurrence: str,
    observed_at: str,
    report_due: bool,
    same_slot_authoritative_fulfilled: bool = False,
    authoritative_runtime_snapshot: bool = False,
    fulfillment_reason: str | None = None,
    acquisition_in_progress: bool = False,
    previous_core_attempts: int = 0,
    supplied_core_logical_slot: str | None = None,
    report_prefetch_complete: bool = False,
) -> dict[str, Any]:
    """Plan mandatory natural-hourly V6 core upkeep independently from report routing."""
    occurrence = _parse_local_occurrence(report_occurrence, label="report_occurrence")
    observed = _parse_local_occurrence(observed_at, label="observed_at")
    if occurrence.minute != 30 or occurrence.second != 0:
        raise RuntimeConformanceError("natural FPL Master occurrence must be an exact HH:30 slot")
    attempts = int(previous_core_attempts)
    if attempts < 0 or attempts > 1:
        raise RuntimeConformanceError("previous_core_attempts must be 0 or 1")

    logical_slot = occurrence.replace(minute=0, second=0, microsecond=0)
    if supplied_core_logical_slot is not None:
        supplied = _parse_local_occurrence(
            supplied_core_logical_slot,
            label="supplied_core_logical_slot",
        )
        if supplied != logical_slot:
            raise RuntimeConformanceError(
                "core logical slot must equal the current occurrence HH:00; backfill/future-fill forbidden"
            )

    logical_slot_text = logical_slot.isoformat()
    observed_text = observed.isoformat()
    reason = str(fulfillment_reason or "").strip().lower()
    valid_existing = bool(
        same_slot_authoritative_fulfilled
        and authoritative_runtime_snapshot
        and reason == CORE_REASON
    )
    base = {
        "report_occurrence": occurrence.isoformat(),
        "core_logical_slot": logical_slot_text,
        "observed_at": observed_text,
        "core_upkeep_due": True,
        "report_due": bool(report_due),
        "transport": CORE_TRANSPORT,
        "transport_reason": CORE_REASON,
        "report_prefetch_fulfills_core_slot": False,
        "report_prefetch_observed_complete": bool(report_prefetch_complete),
        "duplicate_acquisition_forbidden": True,
        "duplicate_publication_forbidden": True,
        "backfill_future_fill_allowed": False,
        "v6_master_acquire_allowed": False,
        "alternate_transport_allowed": False,
        "refresh_attempt_count": attempts,
    }

    if valid_existing:
        return {
            **base,
            "status": "ALREADY_FULFILLED",
            "same_slot_fulfilled": True,
            "attempt_governed_refresh": False,
            "authoritative_runtime_snapshot": True,
        }
    if acquisition_in_progress:
        return {
            **base,
            "status": "RE_READ_CURRENT_SLOT_IN_PROGRESS",
            "same_slot_fulfilled": False,
            "attempt_governed_refresh": False,
            "bounded_terminal_reread_required": True,
        }
    if attempts >= 1:
        return {
            **base,
            "status": "ATTEMPT_ALREADY_MADE",
            "same_slot_fulfilled": False,
            "attempt_governed_refresh": False,
            "core_upkeep": "DEGRADED",
        }

    mutation_title = (
        "FPL_MASTER_SLOT "
        f"reason={CORE_REASON} "
        f"logical_slot={logical_slot_text} "
        "audit=FPL_MASTER_HOURLY "
        f"observed_at={observed_text}"
    )
    return {
        **base,
        "status": "GOVERNED_CURRENT_SLOT_ATTEMPT_REQUIRED",
        "same_slot_fulfilled": False,
        "attempt_governed_refresh": True,
        "refresh_attempt_count": 1,
        "issue_431_title": mutation_title,
        "exact_readback_required": True,
        "bounded_terminal_reread_required": True,
    }


def resolve_hourly_core_upkeep_result(
    plan: Mapping[str, Any],
    *,
    result: str,
) -> dict[str, Any]:
    """Resolve one core-upkeep attempt without turning it into a report-delivery barrier."""
    row = dict(plan or {})
    if row.get("attempt_governed_refresh") is not True:
        raise RuntimeConformanceError("core-upkeep result requires an actual governed attempt")
    outcome = str(result or "").strip().upper()
    if outcome in {"SUCCESS", "PASS", "COMPLETED", "ALREADY_PUBLISHED"}:
        row.update(
            {
                "completion_result": "SUCCESS",
                "core_upkeep": "PASS",
                "same_slot_fulfilled": True,
            }
        )
    elif outcome in {"FAILED", "BLOCKED", "TIMEOUT", "ERROR", "PUBLICATION_FAILED"}:
        row.update(
            {
                "completion_result": outcome,
                "core_upkeep": "DEGRADED",
                "same_slot_fulfilled": False,
            }
        )
    else:
        raise RuntimeConformanceError("unsupported core-upkeep result")
    row["report_can_continue"] = bool(row.get("report_due"))
    row["emit_visible_report"] = bool(row.get("report_due"))
    row["silent_occurrence_complete"] = not bool(row.get("report_due"))
    return row


def build_hourly_core_upkeep_proof(
    *,
    report_occurrence: str,
    core_logical_slot: str,
    observed_at: str,
    transport: str,
    mutation_readback_state: str,
    acquisition_run_ids: Sequence[Any] = (),
    publication_run_ids: Sequence[Any] = (),
    runtime_data_v6_publication_sha: str | None = None,
    runtime_data_v6_generation: str | int | None = None,
    publish_integrity: str | None = None,
    authoritative_runtime_snapshot: bool = False,
    fulfillment_reason: str | None = None,
) -> dict[str, Any]:
    """Package transient same-slot core evidence and reject duplicate/manual-recovery proof."""
    occurrence = _parse_local_occurrence(report_occurrence, label="report_occurrence")
    logical_slot = _parse_local_occurrence(core_logical_slot, label="core_logical_slot")
    observed = _parse_local_occurrence(observed_at, label="observed_at")
    expected_slot = occurrence.replace(minute=0, second=0, microsecond=0)
    failures: list[str] = []
    if occurrence.minute != 30 or occurrence.second != 0:
        failures.append("REPORT_OCCURRENCE_NOT_HH30")
    if logical_slot != expected_slot:
        failures.append("CORE_SLOT_NOT_CURRENT_HH00")
    if str(transport or "") != CORE_TRANSPORT:
        failures.append("INVALID_CORE_TRANSPORT")

    acquisition_ids = [str(v) for v in acquisition_run_ids if str(v).strip()]
    publication_ids = [str(v) for v in publication_run_ids if str(v).strip()]
    if len(set(acquisition_ids)) > 1:
        failures.append("DUPLICATE_ACQUISITION_FOR_SLOT")
    if len(set(publication_ids)) > 1:
        failures.append("DUPLICATE_PUBLICATION_FOR_SLOT")

    reason = str(fulfillment_reason or "").strip().lower()
    mutation_ok = str(mutation_readback_state or "").strip().upper() in {"PASS", "MATCH", "EXACT_MATCH"}
    integrity_ok = str(publish_integrity or "").strip().upper() == "PASS"
    natural_reason = reason == CORE_REASON
    same_slot_fulfilled = bool(
        not failures
        and mutation_ok
        and integrity_ok
        and authoritative_runtime_snapshot
        and natural_reason
    )
    if authoritative_runtime_snapshot and not natural_reason:
        failures.append("NON_NATURAL_REASON_CANNOT_BE_AUTHORITATIVE_HOURLY_PROOF")

    return {
        "proof_kind": "TRANSIENT_HOURLY_CORE_UPKEEP_PROOF",
        "authoritative": False,
        "durable_state": False,
        "report_occurrence": occurrence.isoformat(),
        "core_logical_slot": logical_slot.isoformat(),
        "observed_at": observed.isoformat(),
        "transport": str(transport or ""),
        "mutation_readback_state": str(mutation_readback_state or ""),
        "acquisition_run_id": acquisition_ids[0] if len(set(acquisition_ids)) == 1 else None,
        "publication_run_id": publication_ids[0] if len(set(publication_ids)) == 1 else None,
        "runtime_data_v6_publication_sha": runtime_data_v6_publication_sha,
        "runtime_data_v6_generation": runtime_data_v6_generation,
        "publish_integrity": publish_integrity,
        "authoritative_runtime_snapshot": bool(authoritative_runtime_snapshot),
        "same_slot_fulfilled": same_slot_fulfilled,
        "duplicate_acquisition": len(set(acquisition_ids)) > 1,
        "duplicate_publication": len(set(publication_ids)) > 1,
        "fulfillment_reason": reason or None,
        "hard_failures": failures,
        "completion_result": "FULFILLED" if same_slot_fulfilled else "NOT_AUTHORITATIVE",
    }


def validate_v12_authority_sources(*, authority_path: str, state_path: str) -> dict[str, Any]:
    """Allow only current GitHub V12 authority/state paths for V12 bootstrap."""
    if str(authority_path or "") != V12_CANONICAL_PATH:
        raise RuntimeConformanceError("V12 authority must be the GitHub Canonical V12 path")
    if str(state_path or "") != V12_STATE_PATH:
        raise RuntimeConformanceError("V12 durable state must be the GitHub State V12 path")
    return {
        "status": "PASS",
        "authority_path": V12_CANONICAL_PATH,
        "state_path": V12_STATE_PATH,
        "legacy_library_authority_allowed": False,
    }


def hydrate_v12_player_identities(
    state_players: Sequence[Mapping[str, Any]],
    *,
    official_players: Sequence[Mapping[str, Any]],
    state_source: str = V12_STATE_PATH,
    legacy_library_players: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Hydrate identities only from current V12 state/latest explicit state plus Official FPL/V6."""
    if state_source not in {V12_STATE_PATH, "LATEST_EXPLICIT_USER_STATE"}:
        raise RuntimeConformanceError("legacy Library state cannot hydrate V12 player identities")
    official_by_id = {
        int(row["element_id"]): dict(row)
        for row in official_players
        if row.get("element_id") is not None
    }
    rows: list[dict[str, Any]] = []
    for raw in state_players:
        row = dict(raw)
        if row.get("element_id") is None:
            raise RuntimeConformanceError("V12 state player identity requires element_id")
        element_id = int(row["element_id"])
        official = official_by_id.get(element_id)
        if official is None:
            raise RuntimeConformanceError(
                f"V12 state element_id {element_id} missing from current Official FPL/V6 universe"
            )
        rows.append(
            {
                **row,
                "element_id": element_id,
                "official_identity": official,
            }
        )
    ids = [row["element_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeConformanceError("V12 identity hydration contains duplicate element_id")
    return {
        "status": "PASS",
        "rows": rows,
        "identity_source": "OFFICIAL_FPL_V6_PLUS_CURRENT_V12_STATE",
        "legacy_library_input_count": len(list(legacy_library_players)),
        "legacy_library_input_ignored": True,
        "legacy_library_identity_hydration_allowed": False,
    }


def plan_due_report_refresh(
    *,
    report_due: bool,
    report_mode: str,
    required_scope_age_minutes: float | None,
    canonical_freshness_threshold_minutes: float | None,
    acquisition_in_progress: bool = False,
    acquisition_just_completed: bool = False,
    recent_result_reusable: bool = False,
    same_logical_data_slot_fulfilled: bool = False,
    previous_refresh_attempts: int = 0,
) -> dict[str, Any]:
    """Plan at most one existing #431 refresh for a stale due-report scope."""
    mode = str(report_mode or "").strip().upper()
    attempts = int(previous_refresh_attempts)
    if attempts < 0 or attempts > 1:
        raise RuntimeConformanceError("previous_refresh_attempts must be 0 or 1")
    if not report_due:
        return {
            "status": "NOT_DUE",
            "report_mode": mode,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "transport": "ISSUE_431_EXISTING_GOVERNED_TRANSPORT",
            "report_can_continue": False,
            "duplicate_acquisition_forbidden": True,
        }
    if required_scope_age_minutes is None or canonical_freshness_threshold_minutes is None:
        return {
            "status": "FRESHNESS_UNRESOLVED",
            "report_mode": mode,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "transport": "ISSUE_431_EXISTING_GOVERNED_TRANSPORT",
            "report_can_continue": True,
            "core_refresh": "DEGRADED",
            "reason": "required scope age/threshold unavailable; continue evidence ladder",
            "duplicate_acquisition_forbidden": True,
        }

    age = float(required_scope_age_minutes)
    threshold = float(canonical_freshness_threshold_minutes)
    stale = age > threshold
    if not stale:
        return {
            "status": "REUSE_CURRENT",
            "report_mode": mode,
            "scope_age_minutes": age,
            "freshness_threshold_minutes": threshold,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "report_can_continue": True,
            "duplicate_acquisition_forbidden": True,
        }

    reuse_reason = None
    if acquisition_in_progress:
        reuse_reason = "RELEVANT_ACQUISITION_IN_PROGRESS"
    elif acquisition_just_completed:
        reuse_reason = "RELEVANT_ACQUISITION_JUST_COMPLETED"
    elif recent_result_reusable:
        reuse_reason = "RECENT_RESULT_REUSABLE"
    elif same_logical_data_slot_fulfilled:
        reuse_reason = "SAME_LOGICAL_DATA_SLOT_FULFILLED"

    if reuse_reason:
        return {
            "status": "RE_READ_EXISTING_RESULT",
            "report_mode": mode,
            "scope_age_minutes": age,
            "freshness_threshold_minutes": threshold,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "reason": reuse_reason,
            "report_can_continue": True,
            "duplicate_acquisition_forbidden": True,
        }

    if attempts >= 1:
        return {
            "status": "REFRESH_ATTEMPT_EXHAUSTED",
            "report_mode": mode,
            "scope_age_minutes": age,
            "freshness_threshold_minutes": threshold,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "core_refresh": "DEGRADED",
            "report_can_continue": True,
            "duplicate_acquisition_forbidden": True,
        }

    return {
        "status": "GOVERNED_REFRESH_REQUIRED",
        "report_mode": mode,
        "scope_age_minutes": age,
        "freshness_threshold_minutes": threshold,
        "attempt_governed_refresh": True,
        "refresh_attempt_count": 1,
        "transport": "ISSUE_431_EXISTING_GOVERNED_TRANSPORT",
        "alternate_transport_allowed": False,
        "v6_master_acquire_allowed": False,
        "backfill_future_fill_allowed": False,
        "report_can_continue": True,
        "duplicate_acquisition_forbidden": True,
    }


def resolve_governed_refresh_result(plan: Mapping[str, Any], *, result: str) -> dict[str, Any]:
    """Bind refresh outcome without turning refresh success into a report barrier."""
    row = dict(plan or {})
    outcome = str(result or "").strip().upper()
    if row.get("attempt_governed_refresh") is not True:
        raise RuntimeConformanceError("refresh result requires an actual planned attempt")
    if outcome in {"SUCCESS", "PASS", "COMPLETED"}:
        row.update(
            {
                "refresh_result": "SUCCESS",
                "core_refresh": "PASS",
                "next_action": "RE_READ_AND_CONTINUE_ORIGINAL_REPORT_SLOT",
                "report_can_continue": True,
            }
        )
    elif outcome in {"FAILED", "BLOCKED", "TIMEOUT", "ERROR"}:
        row.update(
            {
                "refresh_result": outcome,
                "core_refresh": "DEGRADED",
                "next_action": "CONTINUE_CANONICAL_EVIDENCE_LADDER_SAME_REPORT_SLOT",
                "report_can_continue": True,
            }
        )
    else:
        raise RuntimeConformanceError("unsupported refresh result")
    return row


def apply_scenario_lifecycle(
    scenario: Mapping[str, Any],
    *,
    observed_at: str,
    official_deadlines: Mapping[int, str],
) -> dict[str, Any]:
    """Expire only explicit target-GW execution routes whose window is closed."""
    row = dict(scenario or {})
    state = str(row.get("scenario_state") or row.get("state") or "").strip().upper()
    execution_state = str(row.get("execution_state") or "NOT_EXECUTED").strip().upper()
    if execution_state not in EXECUTION_STATES:
        raise RuntimeConformanceError("scenario execution_state must be EXECUTED/NOT_EXECUTED")
    target = row.get("target_gw")
    if target is None:
        row["currently_valid"] = bool(row.get("currently_valid", state == "CONTEMPLATED"))
        return row

    target_gw = int(target)
    deadline_raw = official_deadlines.get(target_gw)
    if not deadline_raw:
        row["currently_valid"] = bool(row.get("currently_valid", state == "CONTEMPLATED"))
        return row
    deadline = _parse_iso(deadline_raw, label=f"GW{target_gw} deadline")
    observed = _parse_iso(observed_at, label="observed_at")
    execution_window = str(row.get("execution_window") or "").upper()
    bounded = execution_window in {
        "UNTIL_TARGET_GW_DEADLINE",
        "TARGET_GW_ONLY",
        "GW_DEADLINE",
    } or str(row.get("route_type") or "").upper() in {"ONE_GW_PUNT", "GW_SPECIFIC_ACTION"}

    if (
        state == "CONTEMPLATED"
        and execution_state != "EXECUTED"
        and bounded
        and observed >= deadline
    ):
        row["state"] = "EXPIRED"
        row["scenario_state"] = "EXPIRED"
        row["currently_valid"] = False
        row["active_for_merge"] = False
        row["expired_at"] = deadline.isoformat().replace("+00:00", "Z")
        row["expiry_reason"] = "TARGET_GW_EXECUTION_WINDOW_CLOSED_NOT_EXECUTED"
        row["historical_review_available"] = True
        row["counterfactual_available"] = True
    else:
        row["currently_valid"] = state == "CONTEMPLATED"
    return row


def scenario_is_active(row: Mapping[str, Any]) -> bool:
    state = str(row.get("scenario_state") or row.get("state") or "").strip().upper()
    return state == "CONTEMPLATED" and row.get("currently_valid", True) is True


def future_transfer_economics_inputs(scenario: Mapping[str, Any], *, target_gw: int) -> dict[str, Any]:
    """Return only assumptions allowed to flow into a future-GW economics calculation."""
    row = dict(scenario or {})
    if str(row.get("scenario_state") or row.get("state") or "").upper() == "EXPIRED":
        return {
            "target_gw": int(target_gw),
            "historical_route_id": row.get("scenario_id"),
            "carried_hit_points_assumption": None,
            "fresh_full_universe_rescan_required": True,
            "historical_assumptions_excluded": True,
        }
    return {
        "target_gw": int(target_gw),
        "historical_route_id": row.get("scenario_id"),
        "carried_hit_points_assumption": row.get("hit_points_assumption"),
        "fresh_full_universe_rescan_required": False,
        "historical_assumptions_excluded": False,
    }


def build_all15_identity_rows(
    owned_players: Sequence[Mapping[str, Any]],
    *,
    model_by_element: Mapping[int | str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Always materialize 15 owned identities; unavailable model fields stay explicit."""
    players = [dict(row) for row in owned_players]
    ids = [row.get("element_id") for row in players]
    if len(players) != 15 or any(value is None for value in ids) or len(set(map(str, ids))) != 15:
        raise RuntimeConformanceError("ALL15 identity source must contain exactly 15 unique element_id values")
    model_map = dict(model_by_element or {})
    fields = (
        "p_available",
        "p_start",
        "p_cameo",
        "p_dnp",
        "xmins",
        "gw_plus_1",
        "three_gw",
        "five_gw",
        "uncertainty_floor_upside",
    )
    rows = []
    unavailable_fields = 0
    for player in players:
        eid = player["element_id"]
        model = dict(model_map.get(eid) or model_map.get(str(eid)) or {})
        row = {
            "element_id": eid,
            "player": player.get("player") or player.get("display_name"),
            "opponent": player.get("opponent", "UNAVAILABLE"),
            "recommended_or_locked_role": player.get("recommended_or_locked_role")
            or player.get("locked_role")
            or "OWNED",
            "tactical_role": player.get("tactical_role", "UNAVAILABLE"),
            "set_piece_penalty_role": player.get("set_piece_penalty_role", "UNAVAILABLE"),
            "matchup": player.get("matchup", "UNAVAILABLE"),
            "action": player.get("action", "HOLD"),
        }
        for field in fields:
            if field in model and model[field] is not None:
                row[field] = model[field]
            else:
                row[field] = "MODEL UPDATE PENDING NEXT COMPUTE"
                unavailable_fields += 1
        rows.append(row)
    return {
        "state": "COMPLETE" if unavailable_fields == 0 else "DEGRADED",
        "identity_state": "COMPLETE",
        "identity_available_count": 15,
        "identity_expected_count": 15,
        "model_state": "COMPLETE" if unavailable_fields == 0 else "DEGRADED",
        "rows": rows,
        "no_identity_fabrication": True,
    }


_DECISION_DELTA_FIELDS = (
    "decision_item",
    "previous_state",
    "current_state",
    "material_change",
    "reason",
    "evidence_time",
)


def validate_decision_delta_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    for index, raw in enumerate(rows, start=1):
        row = dict(raw)
        missing = [field for field in _DECISION_DELTA_FIELDS if field not in row]
        if missing:
            failures.append(f"ROW_{index}_MISSING={','.join(missing)}")
        if "material_change" in row and not isinstance(row.get("material_change"), bool):
            failures.append(f"ROW_{index}_MATERIAL_CHANGE_NOT_BOOL")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


_SIGNAL_DELTA_FIELDS = (
    "signal",
    "baseline_state",
    "current_state",
    "change",
    "evidence",
    "decision_effect",
)


def validate_1230_signal_delta(
    rows: Sequence[Mapping[str, Any]],
    *,
    baseline_available: bool,
) -> dict[str, Any]:
    failures: list[str] = []
    for index, raw in enumerate(rows, start=1):
        row = dict(raw)
        missing = [field for field in _SIGNAL_DELTA_FIELDS if field not in row]
        if missing:
            failures.append(f"ROW_{index}_MISSING={','.join(missing)}")
        if not baseline_available and str(row.get("baseline_state") or "").upper() != "BASELINE UNAVAILABLE":
            failures.append(f"ROW_{index}_BASELINE_MUST_BE_UNAVAILABLE")
        signal = str(row.get("signal") or "").upper()
        if signal in {"P(START)", "XMINs".upper()}:
            evidence = str(row.get("evidence") or "").upper()
            change = str(row.get("change") or "").upper()
            if any(token in change for token in ("+", "-", "%")) and not any(
                token in evidence for token in ("RECOMPUTE", "EXECUTED MODEL", "EXECUTION PROOF")
            ):
                failures.append(f"ROW_{index}_UNPROVEN_MODEL_NUMERIC_CHANGE")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


def split_bench_for_display(
    bench_players: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [dict(row) for row in bench_players]
    if len(rows) != 4:
        raise RuntimeConformanceError("bench display requires exactly four locked bench players")
    gks = [
        row for row in rows
        if str(row.get("position") or row.get("position_name") or "").upper() in {"GK", "GKP"}
    ]
    if len(gks) != 1:
        raise RuntimeConformanceError("bench display requires exactly one reserve goalkeeper")
    outfield = [row for row in rows if row is not gks[0]]
    outfield.sort(
        key=lambda row: (
            int(row.get("bench_order")) if row.get("bench_order") is not None else 99,
            int(row.get("squad_position")) if row.get("squad_position") is not None else 99,
        )
    )
    return {
        "bench_gk": gks[0],
        "outfield_autosub_priority": outfield,
        "gk_in_outfield_queue": False,
    }


def compose_operational_action(
    *,
    football_action: str,
    operational_action: str,
    trigger: str,
    reversal_or_abort: str,
    next_checkpoint: str,
) -> dict[str, Any]:
    op = str(operational_action or "").strip().upper()
    if op not in ALLOWED_OPERATIONAL_ACTIONS:
        raise RuntimeConformanceError("operational_action must be WAIT/PREPARE/ACT")
    return {
        "football_action": str(football_action or "").strip().upper(),
        "operational_action": op,
        "trigger": str(trigger or ""),
        "reversal_or_abort": str(reversal_or_abort or ""),
        "next_checkpoint": str(next_checkpoint or ""),
        "football_and_operational_actions_separate": True,
    }


def content_contract_severity(value: str) -> str:
    severity = str(value or "").strip().upper()
    if severity not in CONTENT_SEVERITIES:
        raise RuntimeConformanceError("content contract severity must be PASS/DEGRADED/FAIL")
    return severity


def compose_icon_subscopes(
    *,
    picks_scope: Mapping[str, Any] | None,
    standings_scope: Mapping[str, Any] | None,
    eo_scope: Mapping[str, Any] | None = None,
    rival_live_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve healthy ICON+ sub-scopes instead of blanking the whole section."""
    scopes = {
        "SUBMITTED_PICKS_EXPOSURE": dict(picks_scope or {}),
        "LIVE_STANDINGS_RANK": dict(standings_scope or {}),
        "EO_CAPTAINCY": dict(eo_scope or {}),
        "RIVAL_LIVE_POINTS": dict(rival_live_scope or {}),
    }
    states = []
    for name, row in scopes.items():
        state = str(row.get("state") or "UNAVAILABLE").strip().upper()
        if state not in {"COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE", "STALE"}:
            raise RuntimeConformanceError(f"invalid ICON+ sub-scope state {name}={state}")
        row["state"] = state
        scopes[name] = row
        states.append(state)
    overall = "COMPLETE" if all(state == "COMPLETE" for state in states) else "DEGRADED"
    return {
        "state": overall,
        "subscopes": scopes,
        "healthy_subscopes_retained": True,
        "cross_gw_mix_forbidden": True,
    }


def compute_pick_exposure(
    manager_pick_entries: Mapping[str, Mapping[str, Any]],
    *,
    element_id: int,
) -> dict[str, Any]:
    """Compute submitted-picks exposure only from a complete manager-picks denominator."""
    entries = [dict(row) for row in manager_pick_entries.values() if isinstance(row, Mapping)]
    denominator = len(entries)
    if denominator <= 0:
        raise RuntimeConformanceError("manager-picks denominator must be positive")
    owned = started = captain = vice = 0
    for entry in entries:
        picks = [dict(row) for row in entry.get("picks") or [] if isinstance(row, Mapping)]
        target = next((row for row in picks if int(row.get("element_id", -1)) == int(element_id)), None)
        if target is None:
            continue
        owned += 1
        if int(target.get("multiplier") or 0) > 0:
            started += 1
        if target.get("captain") is True:
            captain += 1
        if target.get("vice_captain") is True:
            vice += 1

    def metric(value: int) -> dict[str, Any]:
        return {
            "numerator": value,
            "denominator": denominator,
            "percentage": round(value * 100.0 / denominator, 1),
        }

    return {
        "state": "COMPLETE",
        "denominator": denominator,
        "ownership": metric(owned),
        "starter_share": metric(started),
        "captain_share": metric(captain),
        "vice_share": metric(vice),
        "eo": None,
        "eo_status": "UNAVAILABLE_UNLESS_EXACT_MULTIPLIER_CHIP_INPUTS_SUPPORT_IT",
    }
