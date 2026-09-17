from __future__ import annotations

"""Tamper-evident report delivery proof and receipt validation.

R7 sits after R6 POST_RENDER QA. It records externally acknowledged
user-facing delivery evidence and is the only downstream contract in this
module that may transition a report slot to DELIVERED.
"""

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping

from .delivery_integrity import DeliveryIntegrityError, build_report_slot_id
from .temporal import canonical_timestamp, try_parse_timestamp


_ACKNOWLEDGED = "ACKNOWLEDGED"


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _post_render_ready(post_render_qa: Mapping[str, Any]) -> bool:
    return bool(
        post_render_qa.get("status") == "PASS"
        and post_render_qa.get("qa_stage") == "POST_RENDER"
        and post_render_qa.get("qa_passed") is True
        and post_render_qa.get("delivery_ready") is False
        and post_render_qa.get("report_state") == "BUILDING"
        and post_render_qa.get("next_action") == "BUILD_DELIVERY_PROOF"
        and post_render_qa.get("legacy_fallback_allowed") is False
        and _is_sha256(post_render_qa.get("compute_fingerprint"))
        and _is_sha256(post_render_qa.get("render_contract_token"))
    )


def is_post_render_delivery_ready(post_render_qa: Mapping[str, Any]) -> bool:
    """Public R6->R7 handoff predicate; no caller-supplied shortcut is accepted."""
    return _post_render_ready(post_render_qa)


def _parse_aware_timestamp(value: Any) -> datetime | None:
    return try_parse_timestamp(value)


def _logical_slot_time(report_slot_id: str) -> datetime | None:
    value = str(report_slot_id or "").strip()
    if "|" not in value:
        return None
    timestamp, report_type = value.rsplit("|", 1)
    if not report_type.strip():
        return None
    parsed = _parse_aware_timestamp(timestamp)
    if parsed is None or parsed.second != 0 or parsed.microsecond != 0:
        return None
    return parsed


def _canonical_report_slot_id(report_slot_id: str, logical_slot: datetime) -> str:
    _, report_type = report_slot_id.rsplit("|", 1)
    return build_report_slot_id(
        logical_slot=logical_slot.isoformat(),
        report_type=report_type,
    )


def _canonical_timestamp(value: datetime) -> str:
    return canonical_timestamp(value, timespec="seconds")


def _proof_digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _blocked_post_render() -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "delivery_state": "BLOCKED",
        "delivery_proof_valid": False,
        "report_delivered": False,
        "report_state": "QA_FAILED",
        "delivery_ready": False,
        "next_action": "POST_RENDER_QA",
        "legacy_fallback_allowed": False,
        "delivery_proof_id": None,
        "failures": ["POST_RENDER_QA_NOT_PASSED"],
    }


def _invalid_delivery(*, failures: list[str], report_slot_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "delivery_state": "FAILED",
        "delivery_proof_valid": False,
        "report_delivered": False,
        "report_state": "BUILDING",
        "delivery_ready": False,
        "next_action": "DELIVERY_PROOF_RECOVERY",
        "legacy_fallback_allowed": False,
        "delivery_proof_id": None,
        "delivered_report_slot_id": None,
        "report_slot_id": report_slot_id,
        "failures": failures,
    }


def build_delivery_proof(
    *,
    post_render_qa: Mapping[str, Any],
    report_slot_id: str,
    delivery_status: str,
    delivery_channel: str,
    delivery_target: str,
    provider_receipt_id: str,
    delivered_at: str | datetime,
) -> dict[str, Any]:
    """Mint proof only from externally acknowledged delivery evidence."""
    if not _post_render_ready(post_render_qa):
        return _blocked_post_render()

    slot_id = str(report_slot_id or "").strip()
    status = str(delivery_status or "").strip().upper()
    channel = str(delivery_channel or "").strip()
    target = str(delivery_target or "").strip()
    receipt_id = str(provider_receipt_id or "").strip()
    delivered = _parse_aware_timestamp(delivered_at)
    logical_slot = _logical_slot_time(slot_id)

    failures: list[str] = []
    if status != _ACKNOWLEDGED:
        failures.append("DELIVERY_NOT_ACKNOWLEDGED")
    if not channel:
        failures.append("DELIVERY_CHANNEL_MISSING")
    if not target:
        failures.append("DELIVERY_TARGET_MISSING")
    if not receipt_id:
        failures.append("PROVIDER_RECEIPT_ID_MISSING")
    if delivered is None:
        failures.append("DELIVERED_AT_INVALID")
    if logical_slot is None:
        failures.append("REPORT_SLOT_ID_INVALID")
    elif slot_id != _canonical_report_slot_id(slot_id, logical_slot):
        failures.append("REPORT_SLOT_ID_NONCANONICAL")
    if delivered is not None and logical_slot is not None and delivered < logical_slot:
        failures.append("DELIVERY_BEFORE_LOGICAL_SLOT")

    if failures:
        return _invalid_delivery(failures=failures, report_slot_id=slot_id)

    delivered_at_canonical = _canonical_timestamp(delivered)
    compute_fingerprint = str(post_render_qa["compute_fingerprint"])
    render_contract_token = str(post_render_qa["render_contract_token"])
    payload = {
        "schema_version": 1,
        "report_slot_id": slot_id,
        "compute_fingerprint": compute_fingerprint,
        "render_contract_token": render_contract_token,
        "delivery_status": _ACKNOWLEDGED,
        "delivery_channel": channel,
        "delivery_target": target,
        "provider_receipt_id": receipt_id,
        "delivered_at": delivered_at_canonical,
    }
    proof_id = _proof_digest(payload)

    return {
        "status": "PASS",
        "delivery_state": "ACKNOWLEDGED",
        "delivery_proof_valid": True,
        "report_delivered": True,
        "report_state": "DELIVERED",
        "delivery_ready": False,
        "next_action": "NONE",
        "legacy_fallback_allowed": False,
        "delivery_proof_id": proof_id,
        "delivered_report_slot_id": slot_id,
        **payload,
        "failures": [],
    }


def validate_delivery_proof(
    *,
    proof: Mapping[str, Any],
    post_render_qa: Mapping[str, Any],
    expected_report_slot_id: str,
) -> dict[str, Any]:
    """Recompute proof from receipt evidence and reject any mutation or slot drift."""
    if not _post_render_ready(post_render_qa):
        return _blocked_post_render()

    expected_slot = str(expected_report_slot_id or "").strip()
    failures: list[str] = []
    if str(proof.get("report_slot_id") or "").strip() != expected_slot:
        failures.append("REPORT_SLOT_MISMATCH")
    if proof.get("compute_fingerprint") != post_render_qa.get("compute_fingerprint"):
        failures.append("COMPUTE_FINGERPRINT_MISMATCH")
    if proof.get("render_contract_token") != post_render_qa.get("render_contract_token"):
        failures.append("RENDER_CONTRACT_TOKEN_MISMATCH")

    rebuilt = build_delivery_proof(
        post_render_qa=post_render_qa,
        report_slot_id=str(proof.get("report_slot_id") or ""),
        delivery_status=str(proof.get("delivery_status") or ""),
        delivery_channel=str(proof.get("delivery_channel") or ""),
        delivery_target=str(proof.get("delivery_target") or ""),
        provider_receipt_id=str(proof.get("provider_receipt_id") or ""),
        delivered_at=str(proof.get("delivered_at") or ""),
    )
    if rebuilt.get("status") != "PASS":
        failures.extend(
            failure
            for failure in rebuilt.get("failures", [])
            if failure not in failures
        )
    elif proof.get("delivery_proof_id") != rebuilt.get("delivery_proof_id"):
        failures.append("DELIVERY_PROOF_DIGEST_MISMATCH")

    expected_control = {
        "status": "PASS",
        "delivery_proof_valid": True,
        "report_delivered": True,
        "report_state": "DELIVERED",
        "delivery_ready": False,
        "next_action": "NONE",
        "legacy_fallback_allowed": False,
    }
    if any(proof.get(key) != value for key, value in expected_control.items()):
        failures.append("DELIVERY_PROOF_STATE_INVALID")

    if failures:
        return _invalid_delivery(failures=failures, report_slot_id=expected_slot)

    return {
        "status": "PASS",
        "delivery_state": "ACKNOWLEDGED",
        "delivery_proof_valid": True,
        "report_delivered": True,
        "report_state": "DELIVERED",
        "delivery_ready": False,
        "next_action": "NONE",
        "legacy_fallback_allowed": False,
        "delivery_proof_id": str(proof["delivery_proof_id"]),
        "delivered_report_slot_id": expected_slot,
        "report_slot_id": expected_slot,
        "compute_fingerprint": str(post_render_qa["compute_fingerprint"]),
        "render_contract_token": str(post_render_qa["render_contract_token"]),
        "delivery_status": str(proof["delivery_status"]),
        "delivery_channel": str(proof["delivery_channel"]),
        "delivery_target": str(proof["delivery_target"]),
        "provider_receipt_id": str(proof["provider_receipt_id"]),
        "delivered_at": str(proof["delivered_at"]),
        "failures": [],
    }


def finalize_delivery_outcome(
    *,
    validated_delivery: Mapping[str, Any],
    expected_report_slot_id: str,
    scope_matrix: Mapping[str, Any],
) -> dict[str, Any]:
    """Project acknowledged delivery truth separately from report quality.

    `status=PASS` means the exact report slot has a valid acknowledged receipt.
    `report_quality=DEGRADED` only describes truthful non-blocking scope degradation;
    it never weakens the receipt requirement and never creates `PASS_DEGRADED`.
    """
    expected_slot = str(expected_report_slot_id or "").strip()
    if not expected_slot:
        raise DeliveryIntegrityError("expected_report_slot_id is required")

    blocking_scopes = list(scope_matrix.get("blocking_scopes") or [])
    if scope_matrix.get("report_ready") is not True or blocking_scopes:
        raise DeliveryIntegrityError("cannot finalize delivery with blocking scope")

    scopes = scope_matrix.get("scopes")
    if not isinstance(scopes, Mapping):
        raise DeliveryIntegrityError("scope matrix is missing canonical scopes")

    degraded_scopes = list(scope_matrix.get("degraded_scopes") or [])
    for scope_id in degraded_scopes:
        row = scopes.get(scope_id)
        if not isinstance(row, Mapping) or row.get("degraded") is not True:
            raise DeliveryIntegrityError("degraded scope matrix is inconsistent")

    if not (
        validated_delivery.get("status") == "PASS"
        and validated_delivery.get("delivery_proof_valid") is True
        and validated_delivery.get("report_delivered") is True
        and validated_delivery.get("report_state") == "DELIVERED"
    ):
        raise DeliveryIntegrityError("validated acknowledged delivery proof is required")

    delivered_slot = str(validated_delivery.get("delivered_report_slot_id") or "").strip()
    if delivered_slot != expected_slot:
        raise DeliveryIntegrityError("delivery proof must acknowledge the same report slot")

    return {
        "status": "PASS",
        "delivery_status": "DELIVERED",
        "delivery_state": "ACKNOWLEDGED",
        "report_delivered": True,
        "report_state": "DELIVERED",
        "report_quality": "DEGRADED" if degraded_scopes else "COMPLETE",
        "degraded_scopes": degraded_scopes,
        "blocking_scopes": [],
        "delivery_proof_id": str(validated_delivery.get("delivery_proof_id") or ""),
        "delivered_report_slot_id": expected_slot,
        "report_slot_id": expected_slot,
        "legacy_fallback_allowed": False,
    }
