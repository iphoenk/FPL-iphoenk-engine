from __future__ import annotations

"""Tamper-evident report delivery proof and receipt validation.

Wave 7 sits after Wave 6 POST_RENDER QA. It records externally acknowledged
user-facing delivery evidence and is the only downstream contract in this
module that may transition a report slot to DELIVERED.
"""

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping

from .delivery_integrity import build_report_slot_id


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


def _parse_aware_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


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
    return value.isoformat(timespec="seconds")


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
