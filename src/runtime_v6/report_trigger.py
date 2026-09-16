from __future__ import annotations

"""Trigger identity and bounded recovery for on-demand report requests.

AD_HOC is a trigger kind, not a second report pipeline. The generated identity
is deliberately encoded into the existing canonical report-slot format so
Waves 1-10 keep using the same retrieval, compute, QA, delivery-proof,
observability and duplicate-suppression contracts.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .delivery_integrity import (
    DeliveryIntegrityError,
    build_report_slot_id,
    resolve_report_slot_decision,
)


_REPORT_TIMEZONE = ZoneInfo("Asia/Jakarta")


def _parse_aware_timestamp(value: str | datetime, *, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise DeliveryIntegrityError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DeliveryIntegrityError(f"{label} must include timezone offset")
    return parsed


def _canonical_timestamp(value: datetime) -> str:
    return value.astimezone(_REPORT_TIMEZONE).isoformat(timespec="seconds")


def _validate_request_id(request_id: str) -> str:
    value = str(request_id or "").strip()
    if not value:
        raise DeliveryIntegrityError("request_id must be non-empty")
    if any(character in value for character in "|:") or any(character.isspace() for character in value):
        raise DeliveryIntegrityError("request_id must be slot-safe")
    return value


def _validate_report_type(report_type: str) -> str:
    value = str(report_type or "").strip().upper()
    if not value:
        raise DeliveryIntegrityError("report_type must be non-empty")
    if "|" in value or ":" in value:
        raise DeliveryIntegrityError("report_type must be slot-safe")
    return value


def _encoded_report_type(*, request_id: str, report_type: str) -> str:
    return f"ADHOC:{request_id}:{report_type}"


def build_ad_hoc_report_context(
    *,
    request_id: str,
    requested_at: str | datetime,
    report_type: str,
) -> dict[str, Any]:
    """Build deterministic identity for one on-demand request.

    The exact request timestamp is retained as evidence. The existing report
    slot format remains minute-aligned; uniqueness within a minute comes from
    request_id, so retries of one request reuse identity while new requests do
    not collide.
    """
    request = _validate_request_id(request_id)
    kind = _validate_report_type(report_type)
    requested = _parse_aware_timestamp(requested_at, label="requested_at").astimezone(
        _REPORT_TIMEZONE
    )
    logical = requested.replace(second=0, microsecond=0)
    encoded_type = _encoded_report_type(request_id=request, report_type=kind)
    report_slot_id = build_report_slot_id(
        logical_slot=logical,
        report_type=encoded_type,
    )
    return {
        "trigger_kind": "AD_HOC",
        "request_id": request,
        "requested_at": _canonical_timestamp(requested),
        "logical_slot": logical.isoformat(timespec="seconds"),
        "report_type": kind,
        "report_slot_id": report_slot_id,
        "scheduler_proof_required": False,
        "scheduler_proof_status": "N/A",
        "missed_cycle_status": "N/A",
        "legacy_fallback_allowed": False,
    }


def resolve_ad_hoc_report_decision(
    *,
    request_id: str,
    requested_at: str | datetime,
    report_type: str,
    report_state: str,
    delivered_report_slot_id: str | None,
    delivery_proof_valid: bool,
    v6_already_published: bool,
) -> dict[str, Any]:
    """Apply Wave 2 report-state semantics to an AD_HOC request identity."""
    context = build_ad_hoc_report_context(
        request_id=request_id,
        requested_at=requested_at,
        report_type=report_type,
    )
    encoded_type = _encoded_report_type(
        request_id=context["request_id"],
        report_type=context["report_type"],
    )
    decision = resolve_report_slot_decision(
        logical_slot=context["logical_slot"],
        report_type=encoded_type,
        report_state=report_state,
        v6_already_published=v6_already_published,
        delivered_report_slot_id=delivered_report_slot_id,
        delivery_proof_valid=delivery_proof_valid,
    )
    if decision["report_slot_id"] != context["report_slot_id"]:
        raise DeliveryIntegrityError("ad hoc report identity drift")
    return {
        **decision,
        **context,
    }


def plan_ad_hoc_recovery(
    *,
    request_id: str,
    requested_at: str | datetime,
    report_type: str,
    observed_at: str | datetime,
    recovery_deadline: str | datetime | None,
    report_state: str,
    delivered_report_slot_id: str | None,
    delivery_proof_valid: bool,
) -> dict[str, Any]:
    """Recover one on-demand request without minting a replacement identity."""
    requested = _parse_aware_timestamp(requested_at, label="requested_at")
    observed = _parse_aware_timestamp(observed_at, label="observed_at")
    if observed < requested:
        raise DeliveryIntegrityError("observed_at cannot precede requested_at")
    if recovery_deadline is None:
        raise DeliveryIntegrityError("ad hoc recovery requires explicit recovery_deadline")
    deadline = _parse_aware_timestamp(recovery_deadline, label="recovery_deadline")
    if deadline < requested:
        raise DeliveryIntegrityError("recovery_deadline cannot precede requested_at")

    decision = resolve_ad_hoc_report_decision(
        request_id=request_id,
        requested_at=requested_at,
        report_type=report_type,
        report_state=report_state,
        delivered_report_slot_id=delivered_report_slot_id,
        delivery_proof_valid=delivery_proof_valid,
        v6_already_published=False,
    )
    common = {
        **decision,
        "recovery_mode": "AD_HOC",
        "observed_at": _canonical_timestamp(observed),
        "recovery_deadline": _canonical_timestamp(deadline),
        "recovery_window_open": observed <= deadline,
        "v6_data_plane_mutation_allowed": False,
        "legacy_fallback_allowed": False,
        "underlying_reason": decision["reason"],
    }

    if decision["report_delivered"]:
        return {
            **common,
            "start_build": False,
            "next_action": "NONE",
        }
    if observed > deadline:
        return {
            **common,
            "start_build": False,
            "next_action": "AD_HOC_RECOVERY_EXPIRED",
        }
    if decision["reason"] == "SAME_SLOT_BUILD_IN_PROGRESS":
        return {
            **common,
            "start_build": False,
            "next_action": "WAIT_FOR_ACTIVE_BUILD",
        }

    next_action_by_reason = {
        "DUE_REPORT": "AD_HOC_BUILD",
        "SAME_SLOT_RECOVERY": "AD_HOC_SAME_REQUEST_RECOVERY",
        "DELIVERY_PROOF_RECOVERY": "AD_HOC_DELIVERY_PROOF_RECOVERY",
    }
    next_action = next_action_by_reason.get(decision["reason"])
    if next_action is None or not decision["report_required"] or not decision["start_build"]:
        raise DeliveryIntegrityError(
            f"ad hoc request is not eligible for recovery: {decision['reason']}"
        )
    return {
        **common,
        "start_build": True,
        "next_action": next_action,
    }
