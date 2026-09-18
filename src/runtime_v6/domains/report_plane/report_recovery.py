from __future__ import annotations

"""Same-slot report recovery and deterministic catch-up planning.

R7 owns fail-safe report-plane recovery between R6 POST_RENDER QA and
acknowledged delivery. It never changes the V6 data plane directly, never
weakens QA or receipt requirements, and never creates a replacement report
slot identity for failed or late work.
"""

from datetime import datetime
from typing import Any, Mapping, Sequence

from .delivery_integrity import (
    DeliveryIntegrityError,
    build_report_slot_id,
    plan_exact_scope_retrieval,
    resolve_report_slot_decision,
    validate_rank20,
    validate_retrieval_reassembly,
)
from .report_delivery import is_post_render_delivery_ready
from .temporal import (
    TemporalError,
    canonical_timestamp,
    compare_temporal_window,
    parse_timestamp,
)


_ALLOWED_RECOVERY_ACTIONS = frozenset(
    {
        "SAME_V6_RETRIEVAL_RECOVERY",
        "RECOMPUTE",
        "PRE_RENDER_RECOVERY",
        "RENDER_RECOVERY",
        "DELIVERY_PROOF_RECOVERY",
    }
)


def _parse_aware_timestamp(value: str | datetime, *, label: str) -> datetime:
    try:
        return parse_timestamp(value, label=label)
    except TemporalError as exc:
        if "timezone-aware" in str(exc):
            raise DeliveryIntegrityError(f"{label} must include timezone offset") from exc
        raise DeliveryIntegrityError(str(exc)) from exc


def _canonical_timestamp(value: datetime) -> str:
    return canonical_timestamp(value, timespec="seconds")


def _validate_retry_budget(*, attempt_count: int, max_attempts: int) -> tuple[int, int]:
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int):
        raise DeliveryIntegrityError("attempt_count must be an integer")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise DeliveryIntegrityError("max_attempts must be an integer")
    if attempt_count < 0:
        raise DeliveryIntegrityError("attempt_count must be non-negative")
    if max_attempts <= 0:
        raise DeliveryIntegrityError("max_attempts must be positive")
    return attempt_count, max_attempts


def _validate_recovery_action(recovery_action: str) -> str:
    action = str(recovery_action or "").strip().upper()
    if action not in _ALLOWED_RECOVERY_ACTIONS:
        raise DeliveryIntegrityError(f"invalid same-run recovery action: {action or '<empty>'}")
    return action


def _resolve_report_plane_slot(
    *,
    logical_slot: str | datetime,
    report_type: str,
    report_state: str,
    delivered_report_slot_id: str | None,
    delivery_proof_valid: bool,
) -> dict[str, Any]:
    """Reuse the canonical report-slot resolver without exporting a V6 fact."""
    decision = resolve_report_slot_decision(
        logical_slot=logical_slot,
        report_type=report_type,
        report_state=report_state,
        v6_already_published=False,
        delivered_report_slot_id=delivered_report_slot_id,
        delivery_proof_valid=delivery_proof_valid,
    )
    decision.pop("v6_already_published", None)
    return decision


def plan_same_run_recovery(
    *,
    logical_slot: str | datetime,
    report_type: str,
    report_state: str,
    delivered_report_slot_id: str | None,
    delivery_proof_valid: bool,
    recovery_action: str,
    attempt_count: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Retry failed report work immediately while preserving the exact report slot."""
    attempt, maximum = _validate_retry_budget(
        attempt_count=attempt_count,
        max_attempts=max_attempts,
    )
    action = _validate_recovery_action(recovery_action)
    decision = _resolve_report_plane_slot(
        logical_slot=logical_slot,
        report_type=report_type,
        report_state=report_state,
        delivered_report_slot_id=delivered_report_slot_id,
        delivery_proof_valid=delivery_proof_valid,
    )

    if decision["report_delivered"]:
        return {
            **decision,
            "recovery_mode": "SAME_RUN",
            "retry_now": False,
            "retry_exhausted": False,
            "attempt_count": attempt,
            "next_attempt_count": attempt,
            "max_attempts": maximum,
            "next_action": "NONE",
            "catch_up_eligible": False,
            "legacy_fallback_allowed": False,
            "v6_data_plane_mutation_allowed": False,
        }

    reason = decision["reason"]
    if reason not in {"SAME_SLOT_RECOVERY", "DELIVERY_PROOF_RECOVERY"}:
        raise DeliveryIntegrityError(
            f"same-run recovery requires a failed/recoverable report state, got {reason}"
        )
    if reason == "DELIVERY_PROOF_RECOVERY" and action != "DELIVERY_PROOF_RECOVERY":
        raise DeliveryIntegrityError(
            "invalid delivered-state recovery action: delivery proof must recover in place"
        )

    exhausted = attempt >= maximum
    retry_now = not exhausted
    return {
        **decision,
        "recovery_mode": "SAME_RUN",
        "retry_now": retry_now,
        "retry_exhausted": exhausted,
        "attempt_count": attempt,
        "next_attempt_count": attempt + 1 if retry_now else attempt,
        "max_attempts": maximum,
        "next_action": action if retry_now else "SCHEDULE_CATCH_UP",
        "catch_up_eligible": exhausted,
        "legacy_fallback_allowed": False,
        "v6_data_plane_mutation_allowed": False,
    }


def _normalize_failed_scopes(failed_healthy_scopes: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_scope in failed_healthy_scopes:
        scope = str(raw_scope or "").strip()
        if not scope:
            raise DeliveryIntegrityError("failed healthy scope id must be non-empty")
        if scope in seen:
            raise DeliveryIntegrityError(f"duplicate failed healthy scope: {scope}")
        seen.add(scope)
        normalized.append(scope)
    return normalized


def _delivery_failure_is_recoverable(
    *,
    delivery_result: Mapping[str, Any],
    expected_report_slot_id: str,
) -> bool:
    return bool(
        delivery_result.get("status") == "FAIL"
        and delivery_result.get("delivery_state") == "FAILED"
        and delivery_result.get("delivery_proof_valid") is False
        and delivery_result.get("report_delivered") is False
        and delivery_result.get("report_state") == "BUILDING"
        and delivery_result.get("next_action") == "DELIVERY_PROOF_RECOVERY"
        and delivery_result.get("legacy_fallback_allowed") is False
        and str(delivery_result.get("report_slot_id") or "").strip() == expected_report_slot_id
    )


def plan_fail_safe_recovery(
    *,
    logical_slot: str | datetime,
    report_type: str,
    report_state: str,
    delivered_report_slot_id: str | None,
    delivery_proof_valid: bool,
    post_render_qa: Mapping[str, Any],
    delivery_result: Mapping[str, Any] | None,
    failed_healthy_scopes: Sequence[str],
    attempt_count: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Derive the narrowest safe same-slot recovery path from actual evidence.

    Precedence is strict:
    1) failed healthy source assertions require exact-scope V6 recovery and a
       full downstream rebuild/re-render/re-QA;
    2) invalid R6 output requires rerender and post-render QA;
    3) a receipt-only failure after valid R6 QA may retry the immutable artifact.
    """
    attempt, maximum = _validate_retry_budget(
        attempt_count=attempt_count,
        max_attempts=max_attempts,
    )
    failed_scopes = _normalize_failed_scopes(failed_healthy_scopes)
    decision = _resolve_report_plane_slot(
        logical_slot=logical_slot,
        report_type=report_type,
        report_state=report_state,
        delivered_report_slot_id=delivered_report_slot_id,
        delivery_proof_valid=delivery_proof_valid,
    )
    slot_id = str(decision["report_slot_id"])

    if decision["report_delivered"]:
        return {
            **decision,
            "recovery_mode": "SAME_RUN",
            "retry_now": False,
            "retry_exhausted": False,
            "attempt_count": attempt,
            "next_attempt_count": attempt,
            "max_attempts": maximum,
            "next_action": "NONE",
            "catch_up_eligible": False,
            "same_artifact_retry": False,
            "exact_scope_recovery_required": False,
            "failed_healthy_scopes": [],
            "recovery_steps": [],
            "compute_fingerprint": None,
            "render_contract_token": None,
            "legacy_fallback_allowed": False,
            "v6_data_plane_mutation_allowed": False,
        }

    if failed_scopes:
        base = plan_same_run_recovery(
            logical_slot=logical_slot,
            report_type=report_type,
            report_state=report_state,
            delivered_report_slot_id=delivered_report_slot_id,
            delivery_proof_valid=delivery_proof_valid,
            recovery_action="SAME_V6_RETRIEVAL_RECOVERY",
            attempt_count=attempt,
            max_attempts=maximum,
        )
        recovery_steps = [
            "SAME_V6_RETRIEVAL_RECOVERY",
            "RETRIEVE",
            "RECOMPUTE",
            "RERENDER",
            "POST_RENDER_QA",
            "BUILD_DELIVERY_PROOF",
            "DELIVER",
            "ACKNOWLEDGED_RECEIPT",
        ]
        return {
            **base,
            "same_artifact_retry": False,
            "exact_scope_recovery_required": True,
            "failed_healthy_scopes": failed_scopes,
            "recovery_steps": recovery_steps,
            "compute_fingerprint": None,
            "render_contract_token": None,
        }

    post_render_ready = is_post_render_delivery_ready(post_render_qa)
    if not post_render_ready:
        base = plan_same_run_recovery(
            logical_slot=logical_slot,
            report_type=report_type,
            report_state=report_state,
            delivered_report_slot_id=delivered_report_slot_id,
            delivery_proof_valid=delivery_proof_valid,
            recovery_action="RENDER_RECOVERY",
            attempt_count=attempt,
            max_attempts=maximum,
        )
        return {
            **base,
            "same_artifact_retry": False,
            "exact_scope_recovery_required": False,
            "failed_healthy_scopes": [],
            "recovery_steps": [
                "RENDER_RECOVERY",
                "POST_RENDER_QA",
                "BUILD_DELIVERY_PROOF",
                "DELIVER",
                "ACKNOWLEDGED_RECEIPT",
            ],
            "compute_fingerprint": None,
            "render_contract_token": None,
        }

    if delivery_result is None or not _delivery_failure_is_recoverable(
        delivery_result=delivery_result,
        expected_report_slot_id=slot_id,
    ):
        raise DeliveryIntegrityError(
            "valid post-render artifact requires explicit recoverable delivery failure evidence"
        )
    if decision["reason"] != "SAME_SLOT_BUILD_IN_PROGRESS":
        raise DeliveryIntegrityError(
            "receipt-only retry requires the R6-approved report artifact to remain BUILDING"
        )

    exhausted = attempt >= maximum
    retry_now = not exhausted
    recovery_steps = [
        "DELIVERY_PROOF_RECOVERY",
        "DELIVER",
        "ACKNOWLEDGED_RECEIPT",
    ]
    return {
        **decision,
        "recovery_mode": "SAME_RUN",
        "retry_now": retry_now,
        "retry_exhausted": exhausted,
        "attempt_count": attempt,
        "next_attempt_count": attempt + 1 if retry_now else attempt,
        "max_attempts": maximum,
        "next_action": "DELIVERY_PROOF_RECOVERY" if retry_now else "SCHEDULE_CATCH_UP",
        "catch_up_eligible": exhausted,
        "same_artifact_retry": True,
        "exact_scope_recovery_required": False,
        "failed_healthy_scopes": [],
        "recovery_steps": recovery_steps,
        "compute_fingerprint": str(post_render_qa["compute_fingerprint"]),
        "render_contract_token": str(post_render_qa["render_contract_token"]),
        "legacy_fallback_allowed": False,
        "v6_data_plane_mutation_allowed": False,
    }



_SAME_REQUEST_PIPELINE = (
    "REQUEST",
    "RETRIEVE",
    "RECOVERY",
    "READY",
    "INPUT_READINESS",
    "COMPUTE",
    "PRE_RENDER_QA",
    "RENDER",
    "POST_RENDER_QA",
    "EMIT",
    "DELIVERY_RECEIPT",
)
_SAME_REQUEST_RECOVERY_SEQUENCE = (
    "SAME_V6_RETRY",
    "GRANULAR_RETRIEVAL",
    "REASSEMBLE",
    "VALIDATE_COMPLETENESS",
    "EXACT_SCOPE_DIRECT_FRESH_IF_PERMITTED",
)
_ALLOWED_TRIGGER_KINDS = frozenset({"SCHEDULED", "AD_HOC"})


def _validate_recovered_rank20_snapshot(
    rows: Sequence[Mapping[str, Any]],
    *,
    label: str,
    observed_at: str | datetime,
    maximum_age_minutes: float,
) -> dict[str, Any]:
    """Apply the canonical J1 row schema, then add snapshot coherence/currentness."""
    if maximum_age_minutes < 0:
        raise DeliveryIntegrityError("rank20_max_age_minutes must be non-negative")

    schema = validate_rank20(rows, label=label)
    sources = {str(row.get("source") or "").strip() for row in rows}
    hashes = {str(row.get("raw_payload_hash") or "").strip() for row in rows}
    snapshot_times = {str(row.get("observed_at") or "").strip() for row in rows}

    provenance_coherent = bool(
        len(rows) == 20
        and len(sources) == 1
        and "" not in sources
        and len(hashes) == 1
        and "" not in hashes
        and len(snapshot_times) == 1
        and "" not in snapshot_times
    )

    snapshot_observed_at = None
    age_minutes = None
    freshness_status = "INVALID"
    current = False
    if provenance_coherent:
        try:
            snapshot_time = _parse_aware_timestamp(
                next(iter(snapshot_times)),
                label=f"{label} observed_at",
            )
            observed = _parse_aware_timestamp(observed_at, label="observed_at")
        except DeliveryIntegrityError:
            freshness_status = "INVALID"
        else:
            age_minutes = round((observed - snapshot_time).total_seconds() / 60.0, 3)
            snapshot_observed_at = _canonical_timestamp(snapshot_time)
            if age_minutes < 0:
                freshness_status = "FUTURE"
            elif age_minutes <= maximum_age_minutes:
                freshness_status = "CURRENT"
                current = True
            else:
                freshness_status = "STALE"

    passed = bool(
        schema["status"] == "PASS"
        and provenance_coherent
        and current
    )
    return {
        "label": str(label or "").strip().upper(),
        "status": "PASS" if passed else "FAIL",
        "schema_status": schema["status"],
        "schema_failures": list(schema.get("failures") or []),
        "row_schema_complete": bool(schema.get("row_schema_complete")),
        "total": len(rows),
        "provenance_coherent": provenance_coherent,
        "source": next(iter(sources)) if len(sources) == 1 else None,
        "raw_payload_hash": next(iter(hashes)) if len(hashes) == 1 else None,
        "snapshot_observed_at": snapshot_observed_at,
        "freshness_status": freshness_status,
        "age_minutes": age_minutes,
        "maximum_age_minutes": float(maximum_age_minutes),
    }


def plan_same_request_recovery_pipeline(
    *,
    request_id: str,
    logical_slot: str | datetime,
    report_type: str,
    trigger_kind: str,
    mode: str,
    v6_scope_id: str,
    v6_scope_state: str,
    retrieval_state: str,
    expected_ids: Sequence[int | str],
    retrieved_chunks: Sequence[Sequence[int | str]],
    rise_rows: Sequence[Mapping[str, Any]],
    fall_rows: Sequence[Mapping[str, Any]],
    observed_at: str | datetime,
    rank20_max_age_minutes: float,
    same_v6_retry_exhausted: bool,
    direct_fresh_contract_permitted: bool,
) -> dict[str, Any]:
    """Integrate existing recovery primitives without creating a parallel pipeline.

    This is a control-plane plan only. It may advance a recovered request to
    COMPUTE, but never claims render/emit/delivery success on behalf of later
    canonical owners.
    """
    canonical_request_id = str(request_id or "").strip()
    if not canonical_request_id:
        raise DeliveryIntegrityError("request_id must be non-empty")

    trigger = str(trigger_kind or "").strip().upper()
    if trigger not in _ALLOWED_TRIGGER_KINDS:
        raise DeliveryIntegrityError(f"invalid trigger_kind: {trigger or '<empty>'}")
    report_mode = str(mode or "").strip().upper()
    if not report_mode:
        raise DeliveryIntegrityError("mode must be non-empty")

    report_slot_id = build_report_slot_id(
        logical_slot=logical_slot,
        report_type=report_type,
    )
    retrieval_plan = plan_exact_scope_retrieval(
        v6_scope_id=v6_scope_id,
        v6_scope_state=v6_scope_state,
        retrieval_state=retrieval_state,
    )

    reassembly = None
    retrieval_complete = retrieval_plan["action"] == "READ_V6_ONLY"
    if retrieval_plan["action"] == "SAME_V6_RETRIEVAL_RECOVERY":
        reassembly = validate_retrieval_reassembly(
            v6_scope_id=v6_scope_id,
            expected_ids=expected_ids,
            retrieved_chunks=retrieved_chunks,
        )
        retrieval_complete = bool(reassembly["complete"])

    direct_fresh_allowed = False
    if not retrieval_complete and bool(same_v6_retry_exhausted):
        direct_fresh_allowed = bool(direct_fresh_contract_permitted)

    rise = _validate_recovered_rank20_snapshot(
        rise_rows,
        label="RISE20",
        observed_at=observed_at,
        maximum_age_minutes=rank20_max_age_minutes,
    )
    fall = _validate_recovered_rank20_snapshot(
        fall_rows,
        label="FALL20",
        observed_at=observed_at,
        maximum_age_minutes=rank20_max_age_minutes,
    )

    input_ready = bool(
        retrieval_complete
        and rise["status"] == "PASS"
        and fall["status"] == "PASS"
    )

    if input_ready:
        next_action = "COMPUTE"
    elif direct_fresh_allowed:
        next_action = "EXACT_SCOPE_DIRECT_FRESH"
    elif not retrieval_complete and not same_v6_retry_exhausted:
        next_action = "SAME_V6_RETRIEVAL_RECOVERY"
    elif not retrieval_complete:
        next_action = "RECOVERY_EXHAUSTED_FAIL_CLOSED"
    else:
        next_action = "SAME_REQUEST_INPUT_RECOVERY"

    return {
        "request_id": canonical_request_id,
        "original_request_id": canonical_request_id,
        "request_identity_preserved": True,
        "report_slot_id": report_slot_id,
        "replacement_report_identity_allowed": False,
        "trigger_kind": trigger,
        "mode": report_mode,
        "ad_hoc_bypass_allowed": False,
        "pipeline": list(_SAME_REQUEST_PIPELINE),
        "recovery_sequence": list(_SAME_REQUEST_RECOVERY_SEQUENCE),
        "v6_scope_id": str(v6_scope_id),
        "retrieval_plan": retrieval_plan,
        "reassembly": reassembly,
        "retrieval_complete": retrieval_complete,
        "same_v6_retry_exhausted": bool(same_v6_retry_exhausted),
        "direct_fresh_contract_permitted": bool(direct_fresh_contract_permitted),
        "direct_fresh_allowed": direct_fresh_allowed,
        "legacy_fallback_allowed": False,
        "v3_v4_v5_fallback_allowed": False,
        "RISE20": rise,
        "FALL20": fall,
        "input_ready": input_ready,
        "next_action": next_action,
        "compute_allowed": input_ready,
        "pre_render_qa_allowed": False,
        "render_allowed": False,
        "post_render_qa_allowed": False,
        "can_emit": False,
        "visible_emitted": False,
        "visible_body_allowed": False,
        "visible_placeholder_allowed": False,
        "delivery_receipt_required": True,
    }


def plan_report_catch_up(
    *,
    logical_slot: str | datetime,
    report_type: str,
    observed_at: str | datetime,
    report_state: str,
    delivered_report_slot_id: str | None,
    delivery_proof_valid: bool,
    catch_up_deadline: str | datetime | None = None,
) -> dict[str, Any]:
    """Plan late report work against the original canonical report-slot identity.

    Late catch-up is fail-closed: every invocation after the logical slot must
    provide an explicit timezone-aware deadline. Work after that deadline is a
    truthful no-op while preserving the original report-slot identity.
    """
    logical = _parse_aware_timestamp(logical_slot, label="logical_slot")
    observed = _parse_aware_timestamp(observed_at, label="observed_at")
    if observed < logical:
        raise DeliveryIntegrityError("observed_at cannot precede logical_slot")
    if observed > logical and catch_up_deadline is None:
        raise DeliveryIntegrityError(
            "late catch-up requires explicit catch_up_deadline"
        )

    deadline: datetime | None = None
    if catch_up_deadline is not None:
        deadline = _parse_aware_timestamp(catch_up_deadline, label="catch_up_deadline")
        if deadline < logical:
            raise DeliveryIntegrityError("catch_up_deadline cannot precede logical_slot")

    window = compare_temporal_window(
        logical_at=logical,
        observed_at=observed,
        deadline=deadline,
    )
    report_slot_id = build_report_slot_id(
        logical_slot=logical_slot,
        report_type=report_type,
    )
    decision = _resolve_report_plane_slot(
        logical_slot=logical_slot,
        report_type=report_type,
        report_state=report_state,
        delivered_report_slot_id=delivered_report_slot_id,
        delivery_proof_valid=delivery_proof_valid,
    )
    if decision["report_slot_id"] != report_slot_id:
        raise DeliveryIntegrityError("catch-up report-slot identity drift")

    common = {
        **decision,
        "recovery_mode": "CATCH_UP",
        "observed_at": _canonical_timestamp(observed),
        "catch_up_deadline": _canonical_timestamp(deadline) if deadline is not None else None,
        "catch_up_window_open": window.window_open,
        "catch_up_required": False,
        "legacy_fallback_allowed": False,
        "v6_data_plane_mutation_allowed": False,
        "underlying_reason": decision["reason"],
    }

    if decision["report_delivered"]:
        return {
            **common,
            "start_build": False,
            "next_action": "NONE",
        }

    if deadline is not None and window.window_open is False:
        return {
            **common,
            "start_build": False,
            "next_action": "CATCH_UP_WINDOW_EXPIRED",
        }

    if observed == logical:
        return {
            **common,
            "start_build": False,
            "next_action": "REGULAR_SLOT_DUE",
        }

    if decision["reason"] == "SAME_SLOT_BUILD_IN_PROGRESS":
        return {
            **common,
            "start_build": False,
            "next_action": "WAIT_FOR_ACTIVE_BUILD",
        }

    next_action_by_reason = {
        "DUE_REPORT": "CATCH_UP_BUILD",
        "SAME_SLOT_RECOVERY": "CATCH_UP_SAME_SLOT_RECOVERY",
        "DELIVERY_PROOF_RECOVERY": "CATCH_UP_DELIVERY_PROOF_RECOVERY",
    }
    next_action = next_action_by_reason.get(decision["reason"])
    if next_action is None or not decision["report_required"] or not decision["start_build"]:
        raise DeliveryIntegrityError(
            f"report slot is not eligible for catch-up: {decision['reason']}"
        )

    return {
        **common,
        "catch_up_required": True,
        "start_build": True,
        "next_action": next_action,
    }
