from __future__ import annotations

"""Deterministic V12 runtime conformance helpers.

This module is downstream report-plane logic only. It does not acquire/publish V6,
change methodology, or become authority. Canonical V12 remains authoritative.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

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
    preliminary_due = bool(row.get("report_due"))
    row["preliminary_report_due"] = preliminary_due
    row["report_can_continue"] = True
    row["emit_visible_report"] = preliminary_due
    row["preliminary_silence_candidate"] = not preliminary_due
    row["silent_occurrence_complete"] = False
    row["final_report_due_required"] = True
    row["same_occurrence_dynamic_evaluation_required"] = True
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



NATURAL_CORE_TERMINAL_STATES = frozenset(
    {
        "ALREADY_FULFILLED",
        "BOUND_IN_PROGRESS_SUCCESS",
        "ATTEMPT_SUCCESS",
        "ATTEMPT_FAILED",
        "ATTEMPT_BLOCKED",
    }
)

POST_CORE_ROUTING_STAGES = frozenset(
    {
        "SAME_OCCURRENCE_FINALIZATION",
        "PRICE_WATCH",
        "MATCH",
        "DEEP",
        "PRICE",
        "DEADLINE",
        "FINAL",
        "POST_MATCH",
        "POST_ALL_MATCH",
        "FULL",
        "GENERIC_ACTION",
        "CONTENT_QA",
        "DELIVERY_OR_SILENCE",
    }
)


def plan_natural_core_upkeep_gate(
    *,
    scheduler_occurrence: str,
    observed_at: str,
    report_due: bool,
    same_slot_authoritative_fulfilled: bool = False,
    same_slot_fulfillment_reason: str | None = None,
    same_slot_publish_integrity: str | None = None,
    same_slot_authoritative_runtime_snapshot: bool = False,
    same_slot_provenance_valid: bool = False,
    same_slot_in_progress_run_id: Any | None = None,
    issue_431_title_before: str | None = None,
) -> dict[str, Any]:
    """Plan the mandatory occurrence-level natural core gate before any terminal routing."""
    occurrence = _parse_local_occurrence(
        scheduler_occurrence, label="scheduler_occurrence"
    )
    observed = _parse_local_occurrence(observed_at, label="observed_at")
    if occurrence.minute != 30 or occurrence.second != 0:
        raise RuntimeConformanceError(
            "natural FPL occurrence must preserve exact scheduler HH:30 identity"
        )
    logical_slot = occurrence.replace(minute=0, second=0, microsecond=0)
    reason = str(same_slot_fulfillment_reason or "").strip().lower()
    integrity = str(same_slot_publish_integrity or "").strip().upper()
    fulfilled = bool(
        same_slot_authoritative_fulfilled
        and reason == CORE_REASON
        and integrity == "PASS"
        and same_slot_authoritative_runtime_snapshot
        and same_slot_provenance_valid
    )

    base = {
        "proof_kind": "TRANSIENT_NATURAL_CORE_UPKEEP_GATE",
        "authoritative": False,
        "durable_state": False,
        "scheduler_occurrence": occurrence.isoformat(),
        "logical_core_slot": logical_slot.isoformat(),
        "observed_at": observed.isoformat(),
        "report_due": bool(report_due),
        "preliminary_report_due": bool(report_due),
        "core_gate_executed": False,
        "gate_terminal": False,
        "resolution_state": None,
        "same_slot_fulfilled": False,
        "existing_run_bound": False,
        "attempt_required": False,
        "attempt_performed": False,
        "mutation_result": None,
        "readback_result": None,
        "bound_v6_run_id": None,
        "publish_integrity": same_slot_publish_integrity,
        "authoritative_runtime_snapshot": bool(
            same_slot_authoritative_runtime_snapshot
        ),
        "duplicate_acquisition": False,
        "terminal_core_result": None,
        "transport": CORE_TRANSPORT,
        "issue_431_title_before": issue_431_title_before,
        "backfill_allowed": False,
        "future_fill_allowed": False,
        "second_scheduler_allowed": False,
        "report_prefetch_fulfills_core_slot": False,
        "recovery_guard_fulfills_core_slot": False,
        "post_core_routing_allowed": False,
        "occurrence_may_complete": False,
        "execution_order": [
            "OCCURRENCE_IDENTITY",
            "LOAD_AUTHORITY_STATE",
            "DETERMINE_PRELIMINARY_REPORT_DUE",
            "NATURAL_CORE_UPKEEP_GATE",
            "FINALIZE_REPORT_DUE_FROM_SAME_OCCURRENCE_DYNAMIC_EVIDENCE",
            "SAME_OCCURRENCE_VISIBLE_EVIDENCE_FINALIZATION_IF_DUE",
            "REPORT_PRICE_MATCH_DEEP_ROUTING",
            "CONTENT_QA_PROOF",
            "DELIVERY_OR_LEGITIMATE_SILENCE",
        ],
    }

    if fulfilled:
        return {
            **base,
            "core_gate_executed": True,
            "gate_terminal": True,
            "resolution_state": "ALREADY_FULFILLED",
            "same_slot_fulfilled": True,
            "readback_result": "EXISTING_SAME_SLOT_AUTHORITATIVE_PROOF",
            "publish_integrity": "PASS",
            "authoritative_runtime_snapshot": True,
            "terminal_core_result": "PASS",
            "post_core_routing_allowed": True,
            "occurrence_may_complete": True,
        }

    if same_slot_in_progress_run_id is not None:
        return {
            **base,
            "action": "BIND_EXISTING_RUN_AND_TERMINAL_REREAD",
            "existing_run_bound": True,
            "bound_v6_run_id": str(same_slot_in_progress_run_id),
            "bounded_terminal_reread_required": True,
        }

    issue_title = (
        "FPL_MASTER_SLOT "
        f"reason={CORE_REASON} "
        f"logical_slot={logical_slot.isoformat()} "
        "audit=FPL_MASTER_HOURLY "
        f"observed_at={observed.isoformat()}"
    )
    return {
        **base,
        "action": "EXECUTE_EXACTLY_ONE_ISSUE_431_TITLE_MUTATION",
        "attempt_required": True,
        "issue_431_title_required": issue_title,
        "exact_readback_required": True,
        "max_attempts_this_occurrence": 1,
    }


def finalize_natural_core_upkeep_gate(
    plan: Mapping[str, Any],
    *,
    attempt_performed: bool = False,
    mutation_result: str | None = None,
    readback_result: str | None = None,
    bound_v6_run_id: Any | None = None,
    terminal_run_result: str | None = None,
    publish_integrity: str | None = None,
    authoritative_runtime_snapshot: bool = False,
    failure_reason: str | None = None,
    duplicate_acquisition: bool = False,
) -> dict[str, Any]:
    """Finalize the mandatory core gate into one allowed terminal resolution state."""
    row = dict(plan or {})
    if row.get("proof_kind") != "TRANSIENT_NATURAL_CORE_UPKEEP_GATE":
        raise RuntimeConformanceError("natural core finalization requires gate plan")
    if duplicate_acquisition:
        raise RuntimeConformanceError(
            "duplicate full-core acquisition is forbidden for one natural occurrence"
        )

    if row.get("gate_terminal") is True:
        if row.get("resolution_state") != "ALREADY_FULFILLED":
            raise RuntimeConformanceError("unexpected pre-terminal core gate state")
        return row

    action = str(row.get("action") or "")
    mutation = str(mutation_result or "").strip().upper()
    readback = str(readback_result or "").strip().upper()
    run_result = str(terminal_run_result or "").strip().upper()
    integrity = str(publish_integrity or "").strip().upper()
    run_id = bound_v6_run_id
    if run_id is None:
        run_id = row.get("bound_v6_run_id")

    success_terminal = run_result in {
        "SUCCESS",
        "PASS",
        "COMPLETED",
        "ALREADY_PUBLISHED",
    }
    failure_terminal = run_result in {
        "FAILED",
        "ERROR",
        "TIMEOUT",
        "CANCELLED",
        "PUBLICATION_FAILED",
    }
    blocked = mutation in {"BLOCKED", "SAFETY_BLOCKED", "DENIED"} or run_result in {
        "BLOCKED",
        "SAFETY_BLOCKED",
    }
    mutation_ok = mutation in {"SUCCESS", "PASS", "UPDATED", "APPLIED"}
    readback_ok = readback in {"PASS", "MATCH", "EXACT_MATCH"}

    if action == "BIND_EXISTING_RUN_AND_TERMINAL_REREAD":
        if run_id is None:
            raise RuntimeConformanceError("in-progress binding requires exact run id")
        if success_terminal and integrity == "PASS" and authoritative_runtime_snapshot:
            resolution = "BOUND_IN_PROGRESS_SUCCESS"
            terminal = "PASS"
            fulfilled = True
        elif blocked:
            resolution = "ATTEMPT_BLOCKED"
            terminal = "BLOCKED"
            fulfilled = False
        elif failure_terminal:
            resolution = "ATTEMPT_FAILED"
            terminal = "FAILED"
            fulfilled = False
        else:
            raise RuntimeConformanceError(
                "in-progress core run must reach a terminal reread result before occurrence completion"
            )
        return {
            **row,
            "core_gate_executed": True,
            "gate_terminal": True,
            "resolution_state": resolution,
            "same_slot_fulfilled": fulfilled,
            "existing_run_bound": True,
            "attempt_required": False,
            "attempt_performed": False,
            "mutation_result": mutation or None,
            "readback_result": readback or None,
            "bound_v6_run_id": str(run_id),
            "publish_integrity": publish_integrity,
            "authoritative_runtime_snapshot": bool(authoritative_runtime_snapshot),
            "duplicate_acquisition": False,
            "terminal_core_result": terminal,
            "failure_reason": failure_reason,
            "post_core_routing_allowed": True,
            "occurrence_may_complete": True,
        }

    if action != "EXECUTE_EXACTLY_ONE_ISSUE_431_TITLE_MUTATION":
        raise RuntimeConformanceError("unsupported natural core gate action")

    if blocked:
        resolution = "ATTEMPT_BLOCKED"
        terminal = "BLOCKED"
        fulfilled = False
    elif not attempt_performed:
        raise RuntimeConformanceError(
            "attempt-required core gate cannot terminate without an attempt or exact blocked proof"
        )
    elif not mutation_ok or not readback_ok or failure_terminal:
        resolution = "ATTEMPT_FAILED"
        terminal = "FAILED"
        fulfilled = False
    elif success_terminal and integrity == "PASS" and authoritative_runtime_snapshot:
        resolution = "ATTEMPT_SUCCESS"
        terminal = "PASS"
        fulfilled = True
    else:
        raise RuntimeConformanceError(
            "governed core attempt must have terminal workflow/publication evidence before completion"
        )

    return {
        **row,
        "core_gate_executed": True,
        "gate_terminal": True,
        "resolution_state": resolution,
        "same_slot_fulfilled": fulfilled,
        "existing_run_bound": False,
        "attempt_required": True,
        "attempt_performed": bool(attempt_performed),
        "mutation_result": mutation or None,
        "readback_result": readback or None,
        "bound_v6_run_id": None if run_id is None else str(run_id),
        "publish_integrity": publish_integrity,
        "authoritative_runtime_snapshot": bool(authoritative_runtime_snapshot),
        "duplicate_acquisition": False,
        "terminal_core_result": terminal,
        "failure_reason": failure_reason,
        "post_core_routing_allowed": True,
        "occurrence_may_complete": True,
    }


def validate_natural_occurrence_completion(
    core_proof: Mapping[str, Any],
    *,
    report_due: bool,
) -> dict[str, Any]:
    """Fail closed if a completed natural occurrence has no terminal core resolution."""
    proof = dict(core_proof or {})
    failures: list[str] = []
    if proof.get("core_gate_executed") is not True:
        failures.append("CORE_GATE_NOT_EXECUTED")
    state = str(proof.get("resolution_state") or "").strip().upper()
    if state not in NATURAL_CORE_TERMINAL_STATES:
        failures.append("CORE_RESOLUTION_NOT_TERMINAL")
    if proof.get("gate_terminal") is not True:
        failures.append("CORE_GATE_NOT_TERMINAL")
    if proof.get("duplicate_acquisition") is not False:
        failures.append("DUPLICATE_ACQUISITION_NOT_FALSE")
    if proof.get("occurrence_may_complete") is not True:
        failures.append("OCCURRENCE_COMPLETION_NOT_AUTHORIZED")
    if state in {"ALREADY_FULFILLED", "BOUND_IN_PROGRESS_SUCCESS", "ATTEMPT_SUCCESS"}:
        if proof.get("same_slot_fulfilled") is not True:
            failures.append("SUCCESS_STATE_WITHOUT_SAME_SLOT_FULFILLMENT")
        if str(proof.get("terminal_core_result") or "").upper() != "PASS":
            failures.append("SUCCESS_STATE_WITHOUT_PASS_RESULT")
    if state == "ATTEMPT_FAILED" and str(
        proof.get("terminal_core_result") or ""
    ).upper() != "FAILED":
        failures.append("FAILED_STATE_WITHOUT_FAILED_RESULT")
    if state == "ATTEMPT_BLOCKED" and str(
        proof.get("terminal_core_result") or ""
    ).upper() != "BLOCKED":
        failures.append("BLOCKED_STATE_WITHOUT_BLOCKED_RESULT")

    status = "PASS" if not failures else "FAIL"
    preliminary_due = bool(report_due)
    return {
        "status": status,
        "failures": failures,
        "occurrence_may_complete": status == "PASS",
        "preliminary_report_due": preliminary_due,
        "preliminary_silence_candidate": bool(status == "PASS" and not preliminary_due),
        "visible_silence_allowed": False,
        "final_report_due_required": status == "PASS",
        "same_occurrence_dynamic_evaluation_required": status == "PASS",
        "due_report_must_continue_fail_operationally": bool(
            status == "PASS"
            and preliminary_due
            and state in {"ATTEMPT_FAILED", "ATTEMPT_BLOCKED"}
        ),
    }


def authorize_post_core_stage(
    core_proof: Mapping[str, Any],
    *,
    stage: str,
) -> dict[str, Any]:
    """Authorize routing only after the mandatory natural core gate is terminal."""
    route = str(stage or "").strip().upper()
    if route not in POST_CORE_ROUTING_STAGES:
        raise RuntimeConformanceError("unsupported post-core routing stage")
    validation = validate_natural_occurrence_completion(
        core_proof,
        report_due=bool(core_proof.get("report_due")),
    )
    if validation["status"] != "PASS":
        raise RuntimeConformanceError(
            "post-core routing is forbidden until NATURAL_CORE_UPKEEP_GATE terminalizes"
        )
    return {
        "status": "PASS",
        "stage": route,
        "core_gate_terminal": True,
        "core_resolution_state": core_proof.get("resolution_state"),
        "same_core_run_reused": True,
        "second_full_core_acquisition_allowed": False,
    }



STATIC_REPORT_SLOT_MODES = {
    (4, 30): "DEEP",
    (5, 30): "PRICE",
    (12, 30): "DEEP",
    (21, 30): "DEEP",
}
REPORT_MODE_ORDER = (
    "FINAL",
    "DEADLINE",
    "DEEP",
    "PRICE",
    "FULL",
    "MATCH",
    "POST_MATCH",
    "POST_ALL_MATCH",
)


def _normalize_report_modes(value: Sequence[str] | str | None) -> list[str]:
    raw: list[str] = []
    if value is None:
        return []
    if isinstance(value, str):
        raw = [part for part in value.replace(",", "+").split("+") if part.strip()]
    else:
        for item in value:
            raw.extend(
                part for part in str(item or "").replace(",", "+").split("+")
                if part.strip()
            )
    out: list[str] = []
    for item in raw:
        mode = item.strip().upper().replace("-", "_")
        if mode == "POST_ALL_MATCH":
            canonical_mode = "POST_ALL_MATCH"
        elif mode == "POST_MATCH":
            canonical_mode = "POST_MATCH"
        else:
            canonical_mode = mode
        if canonical_mode and canonical_mode not in out:
            out.append(canonical_mode)
    order = {mode: index for index, mode in enumerate(REPORT_MODE_ORDER)}
    return sorted(out, key=lambda mode: (order.get(mode, len(order)), mode))


def determine_preliminary_report_due(
    *,
    report_occurrence: str,
    deadline_active: bool = False,
    deadline_mode: str = "DEADLINE",
    known_modes: Sequence[str] | str | None = None,
) -> dict[str, Any]:
    """Determine only the pre-core/static report route for one natural occurrence."""
    occurrence = _parse_local_occurrence(report_occurrence, label="report_occurrence")
    if occurrence.minute != 30 or occurrence.second != 0:
        raise RuntimeConformanceError("preliminary report due requires an exact HH:30 occurrence")
    modes = _normalize_report_modes(known_modes)
    slot_mode = STATIC_REPORT_SLOT_MODES.get((occurrence.hour, occurrence.minute))
    reasons: list[str] = []
    if slot_mode and slot_mode not in modes:
        modes.append(slot_mode)
        reasons.append(f"STATIC_SLOT_{slot_mode}")
    if deadline_active:
        mode = str(deadline_mode or "DEADLINE").strip().upper()
        if mode not in {"DEADLINE", "FINAL"}:
            raise RuntimeConformanceError("deadline_mode must be DEADLINE or FINAL")
        if mode not in modes:
            modes.append(mode)
        reasons.append("DEADLINE_ACTIVE")
    modes = _normalize_report_modes(modes)
    if known_modes:
        reasons.append("PRE_CORE_KNOWN_ROUTE")
    due = bool(modes)
    return {
        "proof_kind": "TRANSIENT_PRELIMINARY_REPORT_DUE",
        "authoritative": False,
        "durable_state": False,
        "report_occurrence": occurrence.isoformat(),
        "preliminary_report_due": due,
        "preliminary_reason": "+".join(reasons) if reasons else "NO_STATIC_OR_PRE_CORE_TRIGGER",
        "preliminary_modes": modes,
        "final_report_due": None,
        "same_occurrence_dynamic_recheck_required": True,
    }


def _fixture_id(row: Mapping[str, Any]) -> str:
    for key in ("fixture", "id", "code"):
        value = row.get(key)
        if value not in {None, ""}:
            return str(value)
    return "UNKNOWN_FIXTURE"


def _fixture_summary(
    fixtures: Sequence[Mapping[str, Any]] | None,
    *,
    scoring_gw: int | None,
) -> dict[str, Any] | None:
    if fixtures is None or scoring_gw is None:
        return None
    rows = [
        dict(row)
        for row in fixtures
        if int(row.get("event") or row.get("gw") or -1) == int(scoring_gw)
    ]
    if not rows:
        return {
            "scoring_gw": int(scoring_gw),
            "fixture_count": 0,
            "live_fixture_ids": [],
            "finished_fixture_ids": [],
            "unstarted_fixture_ids": [],
            "all_finished": False,
            "scope_complete": False,
        }
    live = [
        _fixture_id(row)
        for row in rows
        if row.get("started") is True and row.get("finished") is False
    ]
    finished = [_fixture_id(row) for row in rows if row.get("finished") is True]
    unstarted = [
        _fixture_id(row)
        for row in rows
        if row.get("started") is not True and row.get("finished") is not True
    ]
    return {
        "scoring_gw": int(scoring_gw),
        "fixture_count": len(rows),
        "live_fixture_ids": live,
        "finished_fixture_ids": finished,
        "unstarted_fixture_ids": unstarted,
        "all_finished": len(finished) == len(rows),
        "scope_complete": True,
    }


def finalize_report_due_after_core(
    core_proof: Mapping[str, Any],
    *,
    preliminary_report_due: bool,
    preliminary_reason: str | None,
    preliminary_modes: Sequence[str] | str | None,
    scoring_gw: int | None,
    preliminary_fixture_evidence: Sequence[Mapping[str, Any]] | None = None,
    post_core_fixture_evidence: Sequence[Mapping[str, Any]] | None = None,
    evidence_generated_at: str | None = None,
    dynamic_evidence_authority: str = "AUTHORITATIVE_SAME_OCCURRENCE",
) -> dict[str, Any]:
    """Promote/refine REPORT_DUE only after NATURAL_CORE_UPKEEP_GATE terminalizes.

    False->true is allowed when fresh same-occurrence lifecycle evidence creates a
    dynamic Match/Post-Match/Post-All-Match trigger. True->false is forbidden.
    """
    authorize_post_core_stage(core_proof, stage="SAME_OCCURRENCE_FINALIZATION")
    preliminary_due = bool(preliminary_report_due)
    core_preliminary = bool(
        core_proof.get("preliminary_report_due", core_proof.get("report_due"))
    )
    if core_preliminary != preliminary_due:
        raise RuntimeConformanceError(
            "preliminary REPORT_DUE must remain bound to the value used by the core gate"
        )

    authority = str(dynamic_evidence_authority or "").strip().upper()
    authority_ok = authority in {
        "AUTHORITATIVE_SAME_OCCURRENCE",
        "FRESHEST_VALID_FALLBACK",
    }
    evidence_checked = True
    timestamp = None
    if evidence_generated_at not in {None, ""}:
        timestamp = _parse_local_occurrence(
            evidence_generated_at, label="evidence_generated_at"
        ).isoformat()

    pre_summary = _fixture_summary(
        preliminary_fixture_evidence, scoring_gw=scoring_gw
    )
    post_summary = _fixture_summary(
        post_core_fixture_evidence, scoring_gw=scoring_gw
    )
    dynamic_trigger = "FALSE"
    dynamic_reason = "NO_DYNAMIC_LIFECYCLE_TRANSITION"
    dynamic_mode: str | None = None

    if (
        not authority_ok
        or post_summary is None
        or post_summary.get("scope_complete") is not True
        or timestamp is None
    ):
        dynamic_trigger = "UNRESOLVED"
        dynamic_reason = "DYNAMIC_EVIDENCE_UNRESOLVED_AFTER_CORE"
    else:
        live_ids = list(post_summary.get("live_fixture_ids") or [])
        if live_ids:
            dynamic_trigger = "TRUE"
            dynamic_reason = "SCORING_GW_LIVE_MATCH_AFTER_CORE"
            dynamic_mode = "MATCH"
        else:
            pre_live = bool((pre_summary or {}).get("live_fixture_ids"))
            pre_all_finished = bool((pre_summary or {}).get("all_finished"))
            post_all_finished = bool(post_summary.get("all_finished"))
            pre_finished_count = len((pre_summary or {}).get("finished_fixture_ids") or [])
            post_finished_count = len(post_summary.get("finished_fixture_ids") or [])
            preliminary_has_match = "MATCH" in _normalize_report_modes(preliminary_modes)
            if post_all_finished and (
                preliminary_has_match
                or (pre_summary is not None and not pre_all_finished)
            ):
                dynamic_trigger = "TRUE"
                dynamic_reason = "POST_ALL_MATCH_TRANSITION_AFTER_CORE"
                dynamic_mode = "POST_ALL_MATCH"
            elif (
                post_finished_count > pre_finished_count
                and (pre_live or preliminary_has_match)
            ):
                dynamic_trigger = "TRUE"
                dynamic_reason = "MATCH_COMPLETION_TRANSITION_AFTER_CORE"
                dynamic_mode = "POST_MATCH"

    final_due = bool(preliminary_due or dynamic_trigger == "TRUE")
    if preliminary_due and not final_due:
        raise RuntimeConformanceError("PRELIMINARY_REPORT_DUE=true may never become false")

    modes = _normalize_report_modes(preliminary_modes)
    previous_modes = list(modes)
    if dynamic_mode == "MATCH":
        modes = [
            mode for mode in modes
            if mode not in {"POST_MATCH", "POST_ALL_MATCH"}
        ]
        if "MATCH" not in modes:
            modes.append("MATCH")
    elif dynamic_mode in {"POST_MATCH", "POST_ALL_MATCH"}:
        modes = [mode for mode in modes if mode != "MATCH"]
        if dynamic_mode not in modes:
            modes.append(dynamic_mode)
    modes = _normalize_report_modes(modes)
    if not final_due:
        modes = []

    final_mode = "+".join(modes) if modes else None
    visible_silence = bool(
        not preliminary_due
        and dynamic_trigger == "FALSE"
        and not final_due
    )
    next_action = (
        "ROUTE_ONE_COHERENT_VISIBLE_REPORT"
        if final_due
        else "LEGITIMATE_SILENCE"
        if visible_silence
        else "CONTINUE_EXISTING_FRESHEST_VALID_EVIDENCE_LADDER"
    )
    return {
        "proof_kind": "TRANSIENT_TWO_STAGE_REPORT_DUE_FINALIZATION",
        "authoritative": False,
        "durable_state": False,
        "preliminary_report_due": preliminary_due,
        "preliminary_reason": str(preliminary_reason or ""),
        "preliminary_modes": previous_modes,
        "core_gate_resolution": core_proof.get("resolution_state"),
        "core_terminal_result": core_proof.get("terminal_core_result"),
        "same_core_run_reused": True,
        "second_full_core_acquisition_allowed": False,
        "dynamic_evidence_checked": evidence_checked,
        "dynamic_evidence_authority": authority,
        "dynamic_trigger": dynamic_trigger,
        "dynamic_trigger_reason": dynamic_reason,
        "dynamic_report_due": dynamic_trigger == "TRUE",
        "final_report_due": final_due,
        "final_modes": modes,
        "final_mode": final_mode,
        "due_monotonicity": {
            "false_to_false_allowed": True,
            "false_to_true_allowed": True,
            "true_to_true_required": True,
            "true_to_false_forbidden": True,
        },
        "mode_transition": {
            "preliminary_modes": previous_modes,
            "final_modes": modes,
            "due_sticky_not_mode_sticky": True,
        },
        "evidence_snapshot": {
            "preliminary": pre_summary,
            "post_core": post_summary,
            "raw_v6_payload_duplicated": False,
        },
        "evidence_generated_at": timestamp,
        "visible_silence_allowed": visible_silence,
        "visible_report_count": 1 if final_due else 0,
        "combined_report": bool(final_due and len(modes) > 1),
        "next_action": next_action,
    }


def validate_final_report_routing(
    core_proof: Mapping[str, Any],
    finalization: Mapping[str, Any],
) -> dict[str, Any]:
    """Final termination guard: preliminary false alone can never authorize silence."""
    core = validate_natural_occurrence_completion(
        core_proof,
        report_due=bool(
            finalization.get(
                "preliminary_report_due",
                core_proof.get("preliminary_report_due", core_proof.get("report_due")),
            )
        ),
    )
    failures: list[str] = []
    if core.get("status") != "PASS":
        failures.append("CORE_GATE_NOT_TERMINAL")
    if finalization.get("proof_kind") != "TRANSIENT_TWO_STAGE_REPORT_DUE_FINALIZATION":
        failures.append("FINAL_REPORT_DUE_PROOF_MISSING")
    if finalization.get("dynamic_evidence_checked") is not True:
        failures.append("DYNAMIC_EVIDENCE_NOT_CHECKED")
    preliminary = bool(finalization.get("preliminary_report_due"))
    final_due = bool(finalization.get("final_report_due"))
    trigger = str(finalization.get("dynamic_trigger") or "").upper()
    if preliminary and not final_due:
        failures.append("TRUE_TO_FALSE_REPORT_DUE_FORBIDDEN")
    if trigger == "TRUE" and not final_due:
        failures.append("DYNAMIC_TRIGGER_TRUE_WITH_FINAL_DUE_FALSE")
    if trigger not in {"TRUE", "FALSE", "UNRESOLVED"}:
        failures.append("INVALID_DYNAMIC_TRIGGER_STATE")
    silence = bool(
        not failures
        and not preliminary
        and trigger == "FALSE"
        and not final_due
    )
    if finalization.get("visible_silence_allowed") is True and not silence:
        failures.append("SILENCE_AUTHORIZED_WITHOUT_FINAL_FALSE_PROOF")
    unresolved = trigger == "UNRESOLVED"
    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "final_report_due": final_due,
        "final_mode": finalization.get("final_mode"),
        "visible_silence_allowed": silence,
        "dynamic_trigger_unresolved": unresolved,
        "report_can_continue": bool(final_due or unresolved),
        "next_action": (
            "ROUTE_ONE_COHERENT_VISIBLE_REPORT"
            if final_due
            else "CONTINUE_EXISTING_FRESHEST_VALID_EVIDENCE_LADDER"
            if unresolved
            else "LEGITIMATE_SILENCE"
        ),
        "second_full_core_acquisition_allowed": False,
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


PRICE_ROW_REQUIRED_FIELDS = (
    "player",
    "current_price",
    "direction",
    "official_or_provider_progress",
    "prediction_strength",
    "next_official_price_cycle_uk",
    "next_official_price_cycle_wib",
    "cycles_to_expected_change",
    "estimated_change_window",
    "estimate_source",
    "evidence_timestamp",
    "confidence",
    "impact_on_our_decision",
)
LONDON_TZ = ZoneInfo("Europe/London")
JAKARTA_TZ = ZoneInfo("Asia/Jakarta")


def derive_next_official_price_cycle(observed_at: str) -> dict[str, Any]:
    """Derive the strictly next daily 00:00 Europe/London price cycle in London and WIB."""
    observed = _parse_local_occurrence(observed_at, label="observed_at")
    london_observed = observed.astimezone(LONDON_TZ)
    next_date = london_observed.date() + timedelta(days=1)
    uk_cycle = datetime(
        next_date.year,
        next_date.month,
        next_date.day,
        0,
        0,
        0,
        tzinfo=LONDON_TZ,
    )
    wib_cycle = uk_cycle.astimezone(JAKARTA_TZ)
    return {
        "official_price_change_cadence": "DAILY_AT_00:00_EUROPE_LONDON",
        "predictor_refresh_cadence_minutes": 15,
        "predictor_refresh_is_price_change_cycle": False,
        "next_official_price_cycle_uk": uk_cycle.isoformat(),
        "next_official_price_cycle_wib": wib_cycle.isoformat(),
        "next_price_cycle_uk_label": uk_cycle.strftime("%H:%M %Z"),
        "next_price_cycle_wib_label": wib_cycle.strftime("%H:%M WIB"),
        "uk_utc_offset": uk_cycle.strftime("%z"),
    }


def validate_rise_fall_visible_row(
    row: Mapping[str, Any],
    *,
    section_state: str,
) -> dict[str, Any]:
    """Validate visible RISE/FALL timing semantics without converting predictions into guarantees."""
    data = dict(row or {})
    state = str(section_state or "").strip().upper()
    if state not in {"COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE"}:
        raise RuntimeConformanceError("RISE/FALL section state must be COMPLETE/PARTIAL/DEGRADED/UNAVAILABLE")

    missing = [
        field
        for field in PRICE_ROW_REQUIRED_FIELDS
        if field not in data or data.get(field) in {None, ""}
    ]
    unavailable = [
        field
        for field in PRICE_ROW_REQUIRED_FIELDS
        if str(data.get(field) or "").strip().upper() == "UNAVAILABLE"
    ]
    failures: list[str] = []
    if state == "COMPLETE" and missing:
        failures.append("COMPLETE_PRICE_ROW_MISSING=" + ",".join(missing))
    if state == "COMPLETE" and unavailable:
        failures.append("COMPLETE_PRICE_ROW_UNAVAILABLE=" + ",".join(unavailable))
    if state == "COMPLETE":
        for field in ("next_official_price_cycle_uk", "next_official_price_cycle_wib"):
            value = data.get(field)
            if value:
                try:
                    parsed = _parse_local_occurrence(value, label=field)
                except RuntimeConformanceError:
                    failures.append(f"{field.upper()}_NOT_ISO_TIMEZONE_AWARE")
                else:
                    if field.endswith("_uk"):
                        london = parsed.astimezone(LONDON_TZ)
                        if (london.hour, london.minute, london.second) != (0, 0, 0):
                            failures.append("UK_CYCLE_NOT_00_00_EUROPE_LONDON")

    if data.get("change_guaranteed") is True:
        failures.append("PRICE_PREDICTION_MUST_NOT_BE_GUARANTEED")
    if "GUARANTEED" in str(data.get("prediction_strength") or "").upper():
        failures.append("PRICE_PREDICTION_MUST_NOT_BE_GUARANTEED")

    provider_signals = [
        dict(signal)
        for signal in data.get("provider_signals") or []
        if isinstance(signal, Mapping)
    ]
    stances = {
        str(signal.get("stance") or "").strip().upper()
        for signal in provider_signals
        if str(signal.get("stance") or "").strip()
    }
    disagreement = len(stances) > 1
    if disagreement and data.get("predictor_disagreement") is not True:
        failures.append("PREDICTOR_DISAGREEMENT_NOT_VISIBLE")

    if state in {"PARTIAL", "DEGRADED", "UNAVAILABLE"} and (missing or unavailable):
        degradation_ok = bool(data.get("degradation_reason"))
        if not degradation_ok:
            failures.append("DEGRADED_PRICE_ROW_REQUIRES_REASON")

    return {
        "status": "PASS" if not failures else "FAIL",
        "section_state": state,
        "missing_fields": missing,
        "unavailable_fields": unavailable,
        "predictor_disagreement": disagreement,
        "failures": failures,
    }


def apply_owned_player_presentation(
    *,
    element_id: int,
    display_name: str,
    our15_element_ids: Sequence[int],
) -> dict[str, Any]:
    """Presentation-only bolding driven strictly by Official FPL element_id membership."""
    owned_ids = {int(value) for value in our15_element_ids}
    owned = int(element_id) in owned_ids
    name = str(display_name or "")
    return {
        "element_id": int(element_id),
        "is_owned": owned,
        "rendered_player_name": f"**{name}**" if owned else name,
        "identity_basis": "OFFICIAL_FPL_ELEMENT_ID",
        "name_matching_used_for_identity": False,
    }


def validate_exposure_metric(metric: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(metric or {})
    failures: list[str] = []
    try:
        numerator = float(data["numerator"])
        denominator = float(data["denominator"])
        percentage = float(data["percentage"])
    except (KeyError, TypeError, ValueError):
        return {"status": "FAIL", "failures": ["NUMERATOR_DENOMINATOR_PERCENTAGE_REQUIRED"]}
    if denominator <= 0:
        failures.append("DENOMINATOR_MUST_BE_POSITIVE")
    else:
        expected = round(numerator * 100.0 / denominator, 1)
        if abs(percentage - expected) > 0.05:
            failures.append("PERCENTAGE_ARITHMETIC_MISMATCH")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


def format_exposure_metric(metric: Mapping[str, Any]) -> str:
    validation = validate_exposure_metric(metric)
    if validation["status"] != "PASS":
        raise RuntimeConformanceError("invalid exposure metric arithmetic")
    numerator = metric["numerator"]
    denominator = metric["denominator"]
    percentage = float(metric["percentage"])
    return f"{numerator}/{denominator} = {percentage:.1f}%"



def _evidence_time(record: Mapping[str, Any], *, label: str) -> datetime | None:
    value = record.get("evidence_timestamp")
    if value in {None, ""}:
        return None
    return _parse_local_occurrence(str(value), label=label)


def finalize_same_occurrence_alert_evidence(
    *,
    report_occurrence: str,
    alert_triggered: bool,
    preliminary_public_evidence: Mapping[str, Any],
    post_publication_public_evidence: Mapping[str, Any] | None = None,
    authenticated_personal_evidence: Mapping[str, Any] | None = None,
    bound_core_run_id: Any | None = None,
    core_acquisition_in_progress: bool = False,
    publication_succeeded: bool = False,
    second_full_core_acquisition_requested: bool = False,
) -> dict[str, Any]:
    """Finalize a routed alert from the freshest authoritative same-occurrence evidence."""
    occurrence = _parse_local_occurrence(report_occurrence, label="report_occurrence")
    preliminary = dict(preliminary_public_evidence or {})
    final_public = dict(post_publication_public_evidence or {})
    personal = dict(authenticated_personal_evidence or {})

    if second_full_core_acquisition_requested:
        raise RuntimeConformanceError(
            "same-occurrence finalization must never launch a second full-core acquisition"
        )

    preliminary_time = _evidence_time(preliminary, label="preliminary evidence_timestamp")
    final_time = _evidence_time(final_public, label="post-publication evidence_timestamp")
    final_same_occurrence = (
        not final_public.get("report_occurrence")
        or str(final_public.get("report_occurrence")) == occurrence.isoformat()
    )
    final_authoritative = (
        final_public.get("authoritative_runtime_snapshot") is True
        and str(final_public.get("publish_integrity") or "").upper() == "PASS"
        and publication_succeeded
        and final_same_occurrence
    )
    newer_final = (
        final_time is not None
        and (preliminary_time is None or final_time >= preliminary_time)
    )

    if final_authoritative and newer_final:
        rendered_public = final_public
        public_evidence_state = "POST_PUBLICATION_SAME_OCCURRENCE"
    else:
        rendered_public = preliminary
        public_evidence_state = "PRELIMINARY_BEST_AVAILABLE"

    personal_time = _evidence_time(personal, label="personal evidence_timestamp")
    personal_same_occurrence = (
        not personal.get("report_occurrence")
        or str(personal.get("report_occurrence")) == occurrence.isoformat()
    )
    personal_usable = (
        bool(personal)
        and personal_same_occurrence
        and personal.get("authenticated") is True
        and (
            personal_time is None
            or preliminary_time is None
            or personal_time >= preliminary_time
        )
    )

    return {
        "report_occurrence": occurrence.isoformat(),
        "alert_triggered": bool(alert_triggered),
        "alert_visible": bool(alert_triggered),
        "trigger_evidence_preserved": True,
        "render_public_evidence": rendered_public,
        "render_public_evidence_state": public_evidence_state,
        "authenticated_personal_evidence": personal if personal_usable else None,
        "authenticated_personal_evidence_state": (
            "CURRENT_AUTHENTICATED" if personal_usable else "UNAVAILABLE_OR_STALE"
        ),
        "bound_core_run_id": bound_core_run_id,
        "bounded_terminal_reread_required": bool(core_acquisition_in_progress),
        "launch_second_full_core_acquisition": False,
        "preliminary_values_may_trigger_visibility": True,
        "preliminary_values_may_not_override_newer_same_occurrence_authoritative": True,
    }


def resolve_authenticated_affordability(
    *,
    target_current_price: float | int | None,
    selling_price: float | int | None,
    bank: float | int | None,
    current_price: float | int | None = None,
    purchase_price: float | int | None = None,
    free_transfers: int | None = None,
    hit_cost_points: int | None = None,
) -> dict[str, Any]:
    """Compute nominal affordability from authenticated selling value + bank only."""
    missing = [
        key
        for key, value in (
            ("target_current_price", target_current_price),
            ("selling_price", selling_price),
            ("bank", bank),
        )
        if value is None
    ]
    if missing:
        return {
            "affordability": "UNKNOWN",
            "missing_fields": missing,
            "ft_hit_economics": (
                "KNOWN" if free_transfers is not None else "UNKNOWN"
            ),
        }

    target = float(target_current_price)
    sell = float(selling_price)
    cash = float(bank)
    budget = round(sell + cash, 1)
    remaining = round(budget - target, 1)
    affordable = remaining >= -1e-9
    return {
        "current_price": None if current_price is None else float(current_price),
        "purchase_price": None if purchase_price is None else float(purchase_price),
        "selling_price": sell,
        "bank": cash,
        "target_current_price": target,
        "available_transfer_budget": budget,
        "nominal_affordability": affordable,
        "remaining_if_bought": remaining,
        "affordability": "TRUE" if affordable else "FALSE",
        "free_transfers": free_transfers,
        "hit_cost_points": hit_cost_points,
        "ft_hit_economics": (
            "UNKNOWN"
            if free_transfers is None
            else "KNOWN"
        ),
    }


def resolve_temporary_price_watch_lifecycle(
    *,
    target_match_date: str,
    match_complete: bool,
    immediate_post_match_evidence_available: bool,
    final_assessment: str | None = None,
) -> dict[str, Any]:
    """Resolve one temporary standalone price-watch lifecycle without creating scheduling."""
    action = str(final_assessment or "").strip().upper()
    if action and action not in {"WAIT", "PREPARE", "ACT"}:
        raise RuntimeConformanceError("final_assessment must be WAIT/PREPARE/ACT")
    if not match_complete:
        state = "ACTIVE"
    elif not immediate_post_match_evidence_available:
        state = "AWAITING_POST_MATCH_EVIDENCE"
    elif not action:
        state = "FINAL_ASSESSMENT_REQUIRED"
    else:
        state = "EXPIRED"
    return {
        "target_match_date": str(target_match_date),
        "state": state,
        "final_assessment": action or None,
        "standalone_alerts_allowed": state != "EXPIRED",
        "return_to_canonical_routing": state == "EXPIRED",
        "new_scheduler_required": False,
    }


def validate_identity_production_acceptance(
    *,
    deployed_repair_sha: str,
    production_run_head_sha: str,
    production_run_contains_repair: bool,
    branch_ci_green: bool,
    publish_integrity: str | None = None,
    authoritative_runtime_snapshot: bool = False,
    official_fpl_identity_health: str | None = None,
    official_price_predictor_join_health: str | None = None,
    canonical_identity_health: str | None = None,
    fuzzy_or_name_matching_used: bool = False,
    silent_identity_conflict_accepted: bool = False,
    duplicate_acquisition: bool = False,
) -> dict[str, Any]:
    failures: list[str] = []
    if not production_run_contains_repair:
        failures.append("PRODUCTION_RUN_DOES_NOT_CONTAIN_REPAIR")
    if str(publish_integrity or "").upper() != "PASS":
        failures.append("PUBLISH_INTEGRITY_NOT_PASS")
    if not authoritative_runtime_snapshot:
        failures.append("AUTHORITATIVE_RUNTIME_SNAPSHOT_FALSE")
    if str(official_fpl_identity_health or "").upper() != "GREEN":
        failures.append("OFFICIAL_FPL_IDENTITY_NOT_GREEN")
    if str(official_price_predictor_join_health or "").upper() != "GREEN":
        failures.append("OFFICIAL_PRICE_PREDICTOR_JOIN_NOT_GREEN")
    if str(canonical_identity_health or "").upper() != "GREEN":
        failures.append("CANONICAL_IDENTITY_NOT_GREEN")
    if fuzzy_or_name_matching_used:
        failures.append("FUZZY_OR_NAME_IDENTITY_JOIN_USED")
    if silent_identity_conflict_accepted:
        failures.append("IDENTITY_CONFLICT_SILENTLY_ACCEPTED")
    if duplicate_acquisition:
        failures.append("DUPLICATE_ACQUISITION")
    if branch_ci_green and not production_run_contains_repair:
        failures.append("BRANCH_CI_CANNOT_PROVE_PRODUCTION_ACCEPTANCE")
    return {
        "status": "PASS" if not failures else "FAIL",
        "deployed_repair_sha": str(deployed_repair_sha),
        "production_run_head_sha": str(production_run_head_sha),
        "production_run_contains_repair": bool(production_run_contains_repair),
        "branch_ci_green": bool(branch_ci_green),
        "failures": failures,
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
    expected_manager_count: int | None = None,
    eo_effective_numerator: float | int | None = None,
    eo_inputs_complete: bool = False,
) -> dict[str, Any]:
    """Compute exposure with explicit collected-vs-league denominator discipline."""
    entries = [dict(row) for row in manager_pick_entries.values() if isinstance(row, Mapping)]
    denominator = len(entries)
    if denominator <= 0:
        raise RuntimeConformanceError("manager-picks denominator must be positive")
    expected = denominator if expected_manager_count is None else int(expected_manager_count)
    if expected <= 0 or expected < denominator:
        raise RuntimeConformanceError("expected_manager_count must be >= collected manager count")
    coverage_complete = denominator == expected

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

    def metric(value: float | int) -> dict[str, Any]:
        return {
            "numerator": value,
            "denominator": denominator,
            "percentage": round(float(value) * 100.0 / denominator, 1),
        }

    if eo_effective_numerator is not None and not eo_inputs_complete:
        raise RuntimeConformanceError("EO cannot be claimed without complete multiplier/chip inputs")
    if eo_effective_numerator is not None and not coverage_complete:
        raise RuntimeConformanceError("EO requires complete current mini-league manager coverage")

    eo = metric(eo_effective_numerator) if eo_inputs_complete and eo_effective_numerator is not None else None
    eo_status = "COMPLETE" if eo is not None else "UNAVAILABLE"

    return {
        "state": "COMPLETE" if coverage_complete else "DEGRADED",
        "denominator": denominator,
        "expected_manager_count": expected,
        "coverage": {
            "collected": denominator,
            "expected": expected,
            "complete": coverage_complete,
            "label": f"{denominator}/{expected} managers",
        },
        "metric_denominator_scope": "FULL_LEAGUE" if coverage_complete else "COLLECTED_MANAGERS",
        "ownership": metric(owned),
        "starter_share": metric(started),
        "captain_share": metric(captain),
        "vice_share": metric(vice),
        "eo": eo,
        "eo_status": eo_status,
        "eo_requires_multiplier_chip_inputs": True,
    }
