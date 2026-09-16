from __future__ import annotations

"""Read-only observability projection for V6 data and report delivery planes.

Wave 9 deliberately does not make pipeline decisions. It projects evidence
already produced by the V6 data plane and Waves 3-8 into independently visible
stages so data health can never be mistaken for report-delivery health.
"""

from datetime import datetime
from typing import Any, Mapping

from .delivery_integrity import DeliveryIntegrityError, FINAL_UNAVAILABLE_REASONS


_STAGE_NAMES = (
    "data_plane",
    "retrieval",
    "compute",
    "pre_render_qa",
    "post_render_qa",
    "delivery",
    "recovery",
)


def _canonical_timestamp(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeliveryIntegrityError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DeliveryIntegrityError(f"{label} must include timezone offset")
    return parsed.isoformat(timespec="seconds")


def _timestamp_map(stage_timestamps: Mapping[str, Any] | None) -> dict[str, str | None]:
    supplied = dict(stage_timestamps or {})
    unknown = sorted(set(supplied) - set(_STAGE_NAMES))
    if unknown:
        raise DeliveryIntegrityError(
            f"unknown observability stage timestamp: {','.join(unknown)}"
        )
    return {
        stage: _canonical_timestamp(supplied.get(stage), label=f"{stage}_observed_at")
        for stage in _STAGE_NAMES
    }


def _upper(value: Any, *, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _base_stage(*, status: str, observed_at: str | None) -> dict[str, Any]:
    return {
        "status": status,
        "observed_at": observed_at,
        "legacy_fallback_allowed": False,
    }


def _data_plane_view(
    evidence: Mapping[str, Any] | None,
    *,
    observed_at: str | None,
) -> dict[str, Any]:
    if evidence is None:
        return _base_stage(status="UNKNOWN", observed_at=observed_at)
    result = _base_stage(status=_upper(evidence.get("status")), observed_at=observed_at)
    for key in (
        "reason",
        "generated_at",
        "completed_at",
        "age_min",
        "degraded_sections",
        "core_support_status",
        "health_readiness",
    ):
        if key in evidence:
            result[key] = evidence[key]
    return result


def _retrieval_view(
    evidence: Mapping[str, Any] | None,
    *,
    observed_at: str | None,
) -> dict[str, Any]:
    if evidence is None:
        return {
            **_base_stage(status="UNKNOWN", observed_at=observed_at),
            "source_failed": False,
            "action": None,
        }

    action = _upper(evidence.get("action"))
    scope_state = _upper(evidence.get("v6_scope_state"))
    retrieval_state = _upper(evidence.get("retrieval_state"))
    source_failed = scope_state in FINAL_UNAVAILABLE_REASONS

    if action == "SAME_V6_RETRIEVAL_RECOVERY":
        status = "RECOVERY_REQUIRED"
    elif action == "READ_V6_ONLY":
        status = "PASS" if retrieval_state == "COMPLETE" else "IN_PROGRESS"
    elif action == "SCOPED_DIRECT_FRESH_ALLOWED":
        status = "SOURCE_RECOVERY_REQUIRED"
    else:
        status = "UNKNOWN"

    return {
        **_base_stage(status=status, observed_at=observed_at),
        "v6_scope_id": evidence.get("v6_scope_id"),
        "v6_scope_state": scope_state,
        "retrieval_state": retrieval_state,
        "action": None if action == "UNKNOWN" else action,
        "source_failed": source_failed,
        "scope_lock_required": bool(evidence.get("scope_lock_required", False)),
        "direct_fresh_allowed": bool(evidence.get("direct_fresh_allowed", False)),
    }


def _generic_stage_view(
    evidence: Mapping[str, Any] | None,
    *,
    observed_at: str | None,
    extra_keys: tuple[str, ...],
) -> dict[str, Any]:
    if evidence is None:
        return _base_stage(status="UNKNOWN", observed_at=observed_at)
    result = _base_stage(status=_upper(evidence.get("status")), observed_at=observed_at)
    for key in extra_keys:
        if key in evidence:
            result[key] = evidence[key]
    return result


def _delivery_view(
    evidence: Mapping[str, Any] | None,
    *,
    report_slot_id: str,
    observed_at: str | None,
) -> dict[str, Any]:
    if evidence is None:
        return {
            **_base_stage(status="UNKNOWN", observed_at=observed_at),
            "same_slot_receipt": False,
            "delivered": False,
        }

    delivered_slot = str(
        evidence.get("delivered_report_slot_id")
        or evidence.get("report_slot_id")
        or ""
    ).strip()
    evidence_status = _upper(evidence.get("status"))
    same_slot_receipt = bool(
        evidence_status == "PASS"
        and evidence.get("delivery_proof_valid") is True
        and evidence.get("report_delivered") is True
        and evidence.get("report_state") == "DELIVERED"
        and delivered_slot == report_slot_id
    )
    if same_slot_receipt:
        status = "DELIVERED"
    elif evidence_status == "BLOCKED":
        status = "BLOCKED"
    else:
        status = "FAIL"
    return {
        **_base_stage(status=status, observed_at=observed_at),
        "same_slot_receipt": same_slot_receipt,
        "delivered": same_slot_receipt,
        "report_state": evidence.get("report_state"),
        "report_slot_id": evidence.get("report_slot_id"),
        "delivered_report_slot_id": evidence.get("delivered_report_slot_id"),
        "delivery_proof_valid": bool(evidence.get("delivery_proof_valid", False)),
        "delivery_proof_id": evidence.get("delivery_proof_id"),
        "delivered_at": evidence.get("delivered_at"),
        "next_action": evidence.get("next_action"),
        "failures": list(evidence.get("failures", [])),
    }


def _recovery_view(
    evidence: Mapping[str, Any] | None,
    *,
    observed_at: str | None,
) -> dict[str, Any]:
    if evidence is None:
        return {
            **_base_stage(status="UNKNOWN", observed_at=observed_at),
            "mode": None,
            "active": False,
        }

    mode = _upper(evidence.get("recovery_mode"))
    next_action = str(evidence.get("next_action") or "").upper()
    active = bool(
        evidence.get("retry_now") is True
        or evidence.get("catch_up_required") is True
        or (
            evidence.get("start_build") is True
            and (
                next_action.startswith("CATCH_UP")
                or next_action.startswith("AD_HOC")
            )
        )
    )
    if active:
        status = "ACTIVE"
    elif evidence.get("report_delivered") is True or evidence.get("next_action") == "NONE":
        status = "INACTIVE"
    else:
        status = "PENDING"

    return {
        **_base_stage(status=status, observed_at=observed_at),
        "mode": None if mode == "UNKNOWN" else mode,
        "active": active,
        "retry_now": bool(evidence.get("retry_now", False)),
        "retry_exhausted": bool(evidence.get("retry_exhausted", False)),
        "catch_up_required": bool(evidence.get("catch_up_required", False)),
        "catch_up_eligible": bool(evidence.get("catch_up_eligible", False)),
        "next_action": evidence.get("next_action"),
        "underlying_reason": evidence.get("underlying_reason") or evidence.get("reason"),
        "v6_data_plane_mutation_allowed": False,
    }


def _trigger_view(
    trigger_context: Mapping[str, Any] | None,
    *,
    report_slot_id: str,
) -> dict[str, Any] | None:
    if trigger_context is None:
        return None
    trigger_kind = _upper(trigger_context.get("trigger_kind"))
    trigger_slot_id = str(trigger_context.get("report_slot_id") or "").strip()
    if trigger_slot_id and trigger_slot_id != report_slot_id:
        raise DeliveryIntegrityError("trigger context report-slot identity mismatch")
    if trigger_kind == "AD_HOC":
        if not trigger_context.get("request_id"):
            raise DeliveryIntegrityError("AD_HOC trigger context requires request_id")
        return {
            "trigger_kind": "AD_HOC",
            "request_id": trigger_context.get("request_id"),
            "requested_at": trigger_context.get("requested_at"),
            "report_type": trigger_context.get("report_type"),
            "report_slot_id": report_slot_id,
            "scheduler_proof_required": False,
            "scheduler_proof_status": "N/A",
            "missed_cycle_status": "N/A",
            "legacy_fallback_allowed": False,
        }
    return {
        "trigger_kind": trigger_kind,
        "report_slot_id": report_slot_id,
        "scheduler_proof_required": trigger_context.get("scheduler_proof_required"),
        "scheduler_proof_status": trigger_context.get("scheduler_proof_status"),
        "missed_cycle_status": trigger_context.get("missed_cycle_status"),
        "legacy_fallback_allowed": False,
    }


def _report_plane_status(
    *,
    retrieval: Mapping[str, Any],
    compute: Mapping[str, Any],
    pre_render_qa: Mapping[str, Any],
    post_render_qa: Mapping[str, Any],
    delivery: Mapping[str, Any],
    recovery: Mapping[str, Any],
    any_report_evidence: bool,
) -> str:
    if delivery.get("delivered") is True:
        return "DELIVERED"
    if recovery.get("active") is True:
        return "RECOVERY_REQUIRED"
    if post_render_qa.get("status") in {"FAIL", "BLOCKED"}:
        return "QA_FAILED"
    if pre_render_qa.get("status") in {"FAIL", "BLOCKED"}:
        return "QA_FAILED"
    if delivery.get("status") == "FAIL":
        return "DELIVERY_FAILED"
    if delivery.get("status") == "BLOCKED":
        return "DELIVERY_BLOCKED"
    if compute.get("status") == "FAIL":
        return "COMPUTE_FAILED"
    if compute.get("status") == "BLOCKED":
        return "COMPUTE_BLOCKED"
    if retrieval.get("status") == "RECOVERY_REQUIRED":
        return "RETRIEVAL_RECOVERY"
    if retrieval.get("status") == "SOURCE_RECOVERY_REQUIRED":
        return "SOURCE_RECOVERY_REQUIRED"
    return "IN_PROGRESS" if any_report_evidence else "UNKNOWN"


def build_report_observability(
    *,
    report_slot_id: str,
    data_plane: Mapping[str, Any] | None,
    retrieval: Mapping[str, Any] | None,
    compute: Mapping[str, Any] | None,
    pre_render_qa: Mapping[str, Any] | None,
    post_render_qa: Mapping[str, Any] | None,
    delivery: Mapping[str, Any] | None,
    recovery: Mapping[str, Any] | None,
    trigger_context: Mapping[str, Any] | None = None,
    stage_timestamps: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project independent data/report-plane evidence without changing runtime state."""
    slot_id = str(report_slot_id or "").strip()
    if not slot_id:
        raise DeliveryIntegrityError("report_slot_id must be non-empty")

    timestamps = _timestamp_map(stage_timestamps)
    data_view = _data_plane_view(data_plane, observed_at=timestamps["data_plane"])
    retrieval_view = _retrieval_view(retrieval, observed_at=timestamps["retrieval"])
    compute_view = _generic_stage_view(
        compute,
        observed_at=timestamps["compute"],
        extra_keys=("compute_ready", "compute_fingerprint", "next_action", "failures"),
    )
    pre_qa_view = _generic_stage_view(
        pre_render_qa,
        observed_at=timestamps["pre_render_qa"],
        extra_keys=("qa_stage", "qa_passed", "report_state", "next_action", "failures"),
    )
    post_qa_view = _generic_stage_view(
        post_render_qa,
        observed_at=timestamps["post_render_qa"],
        extra_keys=("qa_stage", "qa_passed", "report_state", "next_action", "failures"),
    )
    delivery_view = _delivery_view(
        delivery,
        report_slot_id=slot_id,
        observed_at=timestamps["delivery"],
    )
    recovery_view = _recovery_view(recovery, observed_at=timestamps["recovery"])
    trigger_view = _trigger_view(trigger_context, report_slot_id=slot_id)

    stages = {
        "retrieval": retrieval_view,
        "compute": compute_view,
        "pre_render_qa": pre_qa_view,
        "post_render_qa": post_qa_view,
        "delivery": delivery_view,
        "recovery": recovery_view,
    }
    any_report_evidence = any(
        evidence is not None
        for evidence in (
            retrieval,
            compute,
            pre_render_qa,
            post_render_qa,
            delivery,
            recovery,
        )
    )
    report_status = _report_plane_status(
        retrieval=retrieval_view,
        compute=compute_view,
        pre_render_qa=pre_qa_view,
        post_render_qa=post_qa_view,
        delivery=delivery_view,
        recovery=recovery_view,
        any_report_evidence=any_report_evidence,
    )

    result = {
        "report_slot_id": slot_id,
        "data_plane": {
            **data_view,
            "legacy_fallback_allowed": False,
        },
        "report_plane": {
            "status": report_status,
            "delivered": bool(delivery_view.get("delivered")),
            "stages": stages,
            "legacy_fallback_allowed": False,
        },
        "invariants": {
            "v6_green_implies_report_green": False,
            "v6_failure_implies_report_failure": False,
            "retrieval_truncated_implies_source_failed": False,
        },
        "legacy_fallback_allowed": False,
    }
    if trigger_view is not None:
        result["trigger"] = trigger_view
    return result
