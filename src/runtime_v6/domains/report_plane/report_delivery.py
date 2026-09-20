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
_EMIT_CONTRACT_FIELDS = (
    "mandatory_scope_gate_pass",
    "input_completeness_pass",
    "pre_render_qa_pass",
    "post_render_qa_pass",
    "report_contract_pass",
)


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _emit_contract_ready(post_render_qa: Mapping[str, Any]) -> bool:
    """Fail closed on any explicit canonical emit-contract failure.

    R6 POST_RENDER PASS is the canonical proof that compute, mandatory-scope,
    input-completeness and pre/post-render QA gates ran in sequence. IR2 adds
    explicit emit-contract evidence when present and forbids an inconsistent
    caller from overriding that chain with a visible delivery. Legacy R6
    fixtures without the newer evidence keys remain compatible until their
    producer is migrated; they are still subject to the exact R6 handoff gate.
    """
    return all(
        post_render_qa.get(field, True) is True
        for field in _EMIT_CONTRACT_FIELDS
    ) and post_render_qa.get("can_emit", True) is True


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
        and _emit_contract_ready(post_render_qa)
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
        "report_contract_pass": False,
        "can_emit": False,
        "visible_emitted": False,
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
        "report_contract_pass": True,
        "can_emit": True,
        "visible_emitted": False,
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
        "report_contract_pass": True,
        "can_emit": True,
        "visible_emitted": True,
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
        "report_contract_pass": True,
        "can_emit": True,
        "visible_emitted": True,
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
        "report_contract_pass": True,
        "can_emit": True,
        "visible_emitted": True,
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
        and validated_delivery.get("report_contract_pass") is True
        and validated_delivery.get("visible_emitted") is True
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
        "report_contract_pass": True,
        "can_emit": True,
        "visible_emitted": True,
        "report_quality": "DEGRADED" if degraded_scopes else "COMPLETE",
        "degraded_scopes": degraded_scopes,
        "blocking_scopes": [],
        "delivery_proof_id": str(validated_delivery.get("delivery_proof_id") or ""),
        "delivered_report_slot_id": expected_slot,
        "report_slot_id": expected_slot,
        "legacy_fallback_allowed": False,
    }


# P0.5 canonical delivery lifecycle. This extends the existing R7 owner instead of
# introducing a parallel proof subsystem.
_P05_RECEIPT_SCHEMA_VERSION = 1


def _delivery_failure(
    failures: list[str],
    *,
    report_slot_id: str | None = None,
    stage: str,
) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "lifecycle_stage": stage,
        "report_slot_id": report_slot_id,
        "visible_emitted": False,
        "delivery_acknowledged": False,
        "delivery_proof_valid": False,
        "report_slot_fulfilled": False,
        "failures": list(dict.fromkeys(failures)),
    }


def record_visible_emission(
    *,
    post_render_qa: Mapping[str, Any],
    report_slot_id: str,
    occurrence_identity: str,
    producer_identity: str,
    emitted_at: str | datetime,
    status_only: bool = False,
) -> dict[str, Any]:
    """Record the actual handoff to the visible delivery adapter.

    This transition proves only VISIBLE_EMITTED. It never synthesizes an ACK or a
    delivery proof from scheduler completion or report-body text.
    """
    slot_id = str(report_slot_id or "").strip()
    occurrence_id = str(occurrence_identity or "").strip()
    producer = str(producer_identity or "").strip()
    failures: list[str] = []
    if not _post_render_ready(post_render_qa):
        failures.append("POST_RENDER_QA_NOT_PASSED")
    if not slot_id or _logical_slot_time(slot_id) is None:
        failures.append("REPORT_SLOT_ID_INVALID")
    elif str(post_render_qa.get("report_slot_id") or "").strip() not in {"", slot_id}:
        failures.append("POST_RENDER_REPORT_SLOT_MISMATCH")
    if not occurrence_id:
        failures.append("OCCURRENCE_IDENTITY_MISSING")
    if not producer:
        failures.append("PRODUCER_IDENTITY_MISSING")
    emitted = _parse_aware_timestamp(emitted_at)
    post_evaluated = _parse_aware_timestamp(post_render_qa.get("evaluated_at"))
    render_completed = _parse_aware_timestamp(post_render_qa.get("render_completed_at"))
    if emitted is None:
        failures.append("EMITTED_AT_INVALID")
    if post_evaluated is None:
        failures.append("POST_RENDER_EVALUATED_AT_INVALID")
    if render_completed is None:
        failures.append("RENDER_COMPLETED_AT_INVALID")
    if (
        emitted is not None
        and post_evaluated is not None
        and emitted < post_evaluated
    ):
        failures.append("EMIT_BEFORE_POST_RENDER_QA")
    if (
        post_evaluated is not None
        and render_completed is not None
        and post_evaluated < render_completed
    ):
        failures.append("POST_RENDER_BEFORE_RENDER_COMPLETE")
    if post_render_qa.get("can_emit") is not True:
        failures.append("CAN_EMIT_NOT_TRUE")
    if post_render_qa.get("report_contract_pass") is not True:
        failures.append("REPORT_CONTRACT_NOT_PASSED")

    if failures:
        return _delivery_failure(
            failures,
            report_slot_id=slot_id or None,
            stage="VISIBLE_EMITTED",
        )

    return {
        "status": "PASS",
        "lifecycle_stage": "VISIBLE_EMITTED",
        "report_slot_id": slot_id,
        "occurrence_identity": occurrence_id,
        "producer_identity": producer,
        "emitted_at": _canonical_timestamp(emitted),
        "visible_body_sha256": post_render_qa.get("visible_body_sha256"),
        "compute_fingerprint": post_render_qa.get("compute_fingerprint"),
        "render_contract_token": post_render_qa.get("render_contract_token"),
        "p05_render_gate_token": (
            post_render_qa.get("provenance", {}).get("p05_render_gate_token")
            if isinstance(post_render_qa.get("provenance"), Mapping)
            else None
        ),
        "status_only": bool(status_only),
        "visible_emitted": True,
        "delivery_acknowledged": False,
        "delivery_proof_valid": False,
        "report_slot_fulfilled": False,
        "failures": [],
    }


def record_delivery_acknowledgement(
    *,
    visible_emission: Mapping[str, Any],
    delivery_ack_id: str,
    acknowledged_at: str | datetime,
    ack_source: str,
    ack_provenance: Mapping[str, Any],
    authoritative: bool = True,
) -> dict[str, Any]:
    """Record provider/platform ACK without yet claiming proof validity."""
    slot_id = str(visible_emission.get("report_slot_id") or "").strip()
    failures: list[str] = []
    if not (
        visible_emission.get("status") == "PASS"
        and visible_emission.get("visible_emitted") is True
    ):
        failures.append("VISIBLE_EMISSION_NOT_VALID")
    ack_id = str(delivery_ack_id or "").strip()
    source = str(ack_source or "").strip()
    if not ack_id:
        failures.append("DELIVERY_ACK_ID_MISSING")
    if not source:
        failures.append("ACK_SOURCE_MISSING")
    if not isinstance(ack_provenance, Mapping) or not dict(ack_provenance):
        failures.append("ACK_PROVENANCE_MISSING")
    acknowledged = _parse_aware_timestamp(acknowledged_at)
    emitted = _parse_aware_timestamp(visible_emission.get("emitted_at"))
    if acknowledged is None:
        failures.append("ACKNOWLEDGED_AT_INVALID")
    if emitted is None:
        failures.append("EMITTED_AT_INVALID")
    if acknowledged is not None and emitted is not None and acknowledged < emitted:
        failures.append("ACK_BEFORE_VISIBLE_EMIT")

    if failures:
        return _delivery_failure(
            failures,
            report_slot_id=slot_id or None,
            stage="DELIVERY_ACKNOWLEDGED",
        )

    return {
        **dict(visible_emission),
        "status": "PASS",
        "lifecycle_stage": "DELIVERY_ACKNOWLEDGED",
        "delivery_ack_id": ack_id,
        "acknowledged_at": _canonical_timestamp(acknowledged),
        "delivered_at": _canonical_timestamp(acknowledged),
        "ack_source": source,
        "ack_provenance": dict(ack_provenance),
        "ack_authoritative": bool(authoritative),
        "delivery_acknowledged": True,
        "delivery_proof_valid": False,
        "report_slot_fulfilled": False,
        "failures": [],
    }


def validate_delivery_acknowledgement(
    *,
    acknowledgement: Mapping[str, Any],
    expected_report_slot_id: str,
    expected_occurrence_identity: str,
    expected_producer_identity: str,
    receipt_generated_at: str | datetime,
    consumed_ack_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Validate same-slot authoritative ACK and chronology without synthesizing truth."""
    expected_slot = str(expected_report_slot_id or "").strip()
    expected_occurrence = str(expected_occurrence_identity or "").strip()
    expected_producer = str(expected_producer_identity or "").strip()
    failures: list[str] = []
    if not (
        acknowledgement.get("status") == "PASS"
        and acknowledgement.get("visible_emitted") is True
        and acknowledgement.get("delivery_acknowledged") is True
    ):
        failures.append("DELIVERY_ACK_NOT_RECORDED")
    if acknowledgement.get("report_slot_id") != expected_slot:
        failures.append("ACK_REPORT_SLOT_MISMATCH")
    if acknowledgement.get("occurrence_identity") != expected_occurrence:
        failures.append("ACK_OCCURRENCE_IDENTITY_MISMATCH")
    if acknowledgement.get("producer_identity") != expected_producer:
        failures.append("ACK_PRODUCER_IDENTITY_MISMATCH")
    if acknowledgement.get("ack_authoritative") is not True:
        failures.append("ACK_NOT_AUTHORITATIVE")
    ack_id = str(acknowledgement.get("delivery_ack_id") or "").strip()
    if not ack_id:
        failures.append("DELIVERY_ACK_ID_MISSING")
    if ack_id in set(consumed_ack_ids):
        failures.append("DELIVERY_ACK_REUSED")
    if acknowledgement.get("status_only") is True:
        failures.append("STATUS_ONLY_ACK_NOT_CANONICAL")
    if not isinstance(acknowledgement.get("ack_provenance"), Mapping) or not dict(
        acknowledgement.get("ack_provenance") or {}
    ):
        failures.append("ACK_PROVENANCE_MISSING")

    emitted = _parse_aware_timestamp(acknowledgement.get("emitted_at"))
    acknowledged = _parse_aware_timestamp(acknowledgement.get("acknowledged_at"))
    receipt_time = _parse_aware_timestamp(receipt_generated_at)
    logical_slot = _logical_slot_time(expected_slot)
    if emitted is None or acknowledged is None or receipt_time is None:
        failures.append("DELIVERY_CHRONOLOGY_TIMESTAMP_INVALID")
    else:
        if logical_slot is not None and emitted < logical_slot:
            failures.append("EMIT_BEFORE_REPORT_SLOT")
        if acknowledged < emitted:
            failures.append("ACK_BEFORE_VISIBLE_EMIT")
        if receipt_time < acknowledged:
            failures.append("RECEIPT_BEFORE_ACK")

    if failures:
        return {
            **dict(acknowledgement),
            "status": "FAIL",
            "lifecycle_stage": "DELIVERY_PROOF_VALID",
            "delivery_proof_valid": False,
            "report_slot_fulfilled": False,
            "receipt_generated_at": (
                _canonical_timestamp(receipt_time) if receipt_time is not None else None
            ),
            "failures": list(dict.fromkeys(failures)),
        }

    proof_payload = {
        "report_slot_id": expected_slot,
        "occurrence_identity": expected_occurrence,
        "producer_identity": expected_producer,
        "delivery_ack_id": ack_id,
        "emitted_at": acknowledgement.get("emitted_at"),
        "acknowledged_at": acknowledgement.get("acknowledged_at"),
        "ack_source": acknowledgement.get("ack_source"),
        "ack_provenance": acknowledgement.get("ack_provenance"),
    }
    return {
        **dict(acknowledgement),
        "status": "PASS",
        "lifecycle_stage": "DELIVERY_PROOF_VALID",
        "delivery_proof_valid": True,
        "delivery_proof_id": _proof_digest(proof_payload),
        "receipt_generated_at": _canonical_timestamp(receipt_time),
        "report_slot_fulfilled": False,
        "failures": [],
    }


def canonical_receipt_acceptance(
    receipt: Mapping[str, Any] | None,
    *,
    expected_report_slot_id: str | None = None,
    expected_occurrence_identity: str | None = None,
) -> bool:
    """Single receipt predicate consumed by Runtime rolling-natural acceptance."""
    if not isinstance(receipt, Mapping):
        return False
    if not (
        receipt.get("schema_version") == _P05_RECEIPT_SCHEMA_VERSION
        and receipt.get("immutable") is True
        and receipt.get("report_slot_due") is True
        and receipt.get("context_hydration_pass") is True
        and receipt.get("prefetch_identity_pass") is True
        and receipt.get("pre_render_qa_pass") is True
        and receipt.get("report_contract_pass") is True
        and receipt.get("post_render_qa_pass") is True
        and receipt.get("can_emit") is True
        and receipt.get("visible_emitted") is True
        and receipt.get("delivery_acknowledged") is True
        and receipt.get("delivery_proof_valid") is True
        and receipt.get("same_slot_binding") is True
        and receipt.get("status_only") is False
        and receipt.get("report_slot_fulfilled") is True
    ):
        return False
    if expected_report_slot_id is not None and receipt.get("report_slot_id") != expected_report_slot_id:
        return False
    if expected_occurrence_identity is not None and receipt.get("occurrence_identity") != expected_occurrence_identity:
        return False
    return True


def build_canonical_report_receipt(
    *,
    occurrence: Mapping[str, Any],
    pre_render_qa: Mapping[str, Any],
    post_render_qa: Mapping[str, Any],
    validated_acknowledgement: Mapping[str, Any],
    receipt_generated_at: str | datetime,
    existing_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mint at most one immutable same-slot fulfillment receipt for an occurrence."""
    report_slot_id = str(post_render_qa.get("report_slot_id") or "").strip()
    occurrence_identity = str(occurrence.get("occurrence_identity") or "").strip()
    producer_identity = str(
        validated_acknowledgement.get("producer_identity") or ""
    ).strip()

    if existing_receipt is not None:
        if canonical_receipt_acceptance(
            existing_receipt,
            expected_report_slot_id=report_slot_id,
            expected_occurrence_identity=occurrence_identity,
        ):
            preserved = dict(existing_receipt)
            preserved["idempotent_reuse"] = True
            preserved["duplicate_ack_observed"] = (
                str(validated_acknowledgement.get("delivery_ack_id") or "")
                != str(existing_receipt.get("delivery_ack_id") or "")
            )
            return preserved
        return {
            "status": "FAIL",
            "report_slot_id": report_slot_id or None,
            "report_slot_fulfilled": False,
            "failures": ["EXISTING_RECEIPT_INVALID_OR_CONFLICTING"],
        }

    failures: list[str] = []
    if not report_slot_id or _logical_slot_time(report_slot_id) is None:
        failures.append("REPORT_SLOT_ID_INVALID")
    if not occurrence_identity:
        failures.append("OCCURRENCE_IDENTITY_MISSING")
    if occurrence.get("report_slot_due") is not True:
        failures.append("REPORT_SLOT_NOT_DUE")
    if occurrence.get("historical_immutable") is True and occurrence.get(
        "canonical_receipt_existed_at_occurrence"
    ) is not True:
        failures.append("HISTORICAL_RECEIPT_BACKFILL_FORBIDDEN")
    if occurrence.get("replacement_report_slot_used") is True:
        failures.append("REPLACEMENT_REPORT_SLOT_FORBIDDEN")
    if occurrence.get("recovery") is True:
        if occurrence.get("recovery_allowed") is not True:
            failures.append("RECOVERY_NOT_ALLOWED")
        if occurrence.get("original_report_slot_id") != report_slot_id:
            failures.append("RECOVERY_ORIGINAL_SLOT_MISMATCH")
    expected_occurrence_id = str(
        validated_acknowledgement.get("occurrence_identity") or ""
    ).strip()
    if expected_occurrence_id != occurrence_identity:
        failures.append("OCCURRENCE_IDENTITY_MISMATCH")
    if pre_render_qa.get("report_slot_id") != report_slot_id:
        failures.append("PRE_RENDER_REPORT_SLOT_MISMATCH")
    if validated_acknowledgement.get("report_slot_id") != report_slot_id:
        failures.append("ACK_REPORT_SLOT_MISMATCH")
    if not producer_identity:
        failures.append("PRODUCER_IDENTITY_MISSING")

    context_hydration_pass = bool(
        isinstance(pre_render_qa.get("decision_context"), Mapping)
        and pre_render_qa.get("decision_context", {}).get("status") == "PASS"
    )
    prefetch_identity_pass = bool(
        isinstance(pre_render_qa.get("prefetch_identity"), Mapping)
        and pre_render_qa.get("prefetch_identity", {}).get("status") == "PASS"
    )
    pre_render_pass = bool(
        pre_render_qa.get("status") == "PASS"
        and pre_render_qa.get("qa_stage") == "PRE_RENDER"
        and pre_render_qa.get("qa_passed") is True
    )
    post_render_pass = bool(
        post_render_qa.get("status") == "PASS"
        and post_render_qa.get("qa_stage") == "POST_RENDER"
        and post_render_qa.get("post_render_qa_pass") is True
    )
    report_contract_pass = post_render_qa.get("report_contract_pass") is True
    can_emit = post_render_qa.get("can_emit") is True
    if not context_hydration_pass:
        failures.append("CONTEXT_HYDRATION_NOT_PASSED")
    if not prefetch_identity_pass:
        failures.append("PREFETCH_IDENTITY_NOT_PASSED")
    if not pre_render_pass:
        failures.append("PRE_RENDER_QA_NOT_PASSED")
    if not post_render_pass:
        failures.append("POST_RENDER_QA_NOT_PASSED")
    if not report_contract_pass:
        failures.append("REPORT_CONTRACT_NOT_PASSED")
    if not can_emit:
        failures.append("CAN_EMIT_NOT_TRUE")
    if validated_acknowledgement.get("visible_emitted") is not True:
        failures.append("VISIBLE_EMITTED_NOT_TRUE")
    if validated_acknowledgement.get("delivery_acknowledged") is not True:
        failures.append("DELIVERY_ACKNOWLEDGED_NOT_TRUE")
    if validated_acknowledgement.get("delivery_proof_valid") is not True:
        failures.append("DELIVERY_PROOF_NOT_VALID")
    if validated_acknowledgement.get("status_only") is True:
        failures.append("STATUS_ONLY_NOT_CANONICAL")

    pre_time = _parse_aware_timestamp(pre_render_qa.get("evaluated_at"))
    render_time = _parse_aware_timestamp(post_render_qa.get("render_completed_at"))
    post_time = _parse_aware_timestamp(post_render_qa.get("evaluated_at"))
    emitted_time = _parse_aware_timestamp(validated_acknowledgement.get("emitted_at"))
    ack_time = _parse_aware_timestamp(validated_acknowledgement.get("acknowledged_at"))
    receipt_time = _parse_aware_timestamp(receipt_generated_at)
    if None in {pre_time, render_time, post_time, emitted_time, ack_time, receipt_time}:
        failures.append("RECEIPT_CHRONOLOGY_TIMESTAMP_INVALID")
    elif not (
        pre_time < render_time < post_time <= emitted_time <= ack_time <= receipt_time
    ):
        failures.append("RECEIPT_CHRONOLOGY_INVALID")

    provenance = {
        "compute_fingerprint": post_render_qa.get("compute_fingerprint"),
        "render_contract_token": post_render_qa.get("render_contract_token"),
        "p05_render_gate_token": (
            post_render_qa.get("provenance", {}).get("p05_render_gate_token")
            if isinstance(post_render_qa.get("provenance"), Mapping)
            else None
        ),
        "visible_body_sha256": validated_acknowledgement.get("visible_body_sha256"),
        "delivery_proof_id": validated_acknowledgement.get("delivery_proof_id"),
        "ack_source": validated_acknowledgement.get("ack_source"),
        "ack_provenance": validated_acknowledgement.get("ack_provenance"),
    }
    if any(value in (None, "", {}, []) for value in provenance.values()):
        failures.append("RECEIPT_PROVENANCE_INCOMPLETE")

    failures = list(dict.fromkeys(failures))
    if failures:
        return {
            "status": "FAIL",
            "schema_version": _P05_RECEIPT_SCHEMA_VERSION,
            "report_slot_id": report_slot_id or None,
            "occurrence_identity": occurrence_identity or None,
            "report_slot_fulfilled": False,
            "delivery_proof_valid": False,
            "failures": failures,
        }

    intended_report_slot = occurrence.get("intended_report_slot")
    report_kind = occurrence.get("report_kind")
    report_mode = occurrence.get("report_mode")
    receipt = {
        "schema_version": _P05_RECEIPT_SCHEMA_VERSION,
        "immutable": True,
        "report_slot_id": report_slot_id,
        "occurrence_identity": occurrence_identity,
        "intended_report_slot": intended_report_slot,
        "report_kind": report_kind,
        "report_mode": report_mode,
        "deadline_active": bool(occurrence.get("deadline_active")),
        "occurrence_state": occurrence.get("occurrence_state"),
        "observed_at": occurrence.get("observed_at"),
        "data_logical_slot": occurrence.get("data_logical_slot"),
        "data_publication_sha": occurrence.get("data_publication_sha"),
        "data_slot_fulfilled": bool(occurrence.get("data_slot_fulfilled")),
        "report_slot_due": True,
        "context_hydration_pass": context_hydration_pass,
        "prefetch_identity_pass": prefetch_identity_pass,
        "pre_render_qa_pass": pre_render_pass,
        "report_contract_pass": report_contract_pass,
        "post_render_qa_pass": post_render_pass,
        "can_emit": can_emit,
        "visible_emitted": True,
        "delivery_acknowledged": True,
        "delivery_proof_valid": True,
        "delivery_ack_id": validated_acknowledgement.get("delivery_ack_id"),
        "delivered_at": validated_acknowledgement.get("acknowledged_at"),
        "status_only": False,
        "same_slot_binding": True,
        "provenance": provenance,
        "producer_identity": producer_identity,
        "receipt_generated_at": _canonical_timestamp(receipt_time),
        "report_slot_fulfilled": True,
        "transport_failed": bool(occurrence.get("transport_failed")),
        "recovery": bool(occurrence.get("recovery")),
        "failures": [],
    }
    receipt["receipt_id"] = _proof_digest(receipt)
    receipt["status"] = "PASS"
    return receipt


_P07_TERMINAL_V6_STATES = frozenset({
    "PASS",
    "SUCCESS",
    "PUBLISHED",
    "ALREADY_PUBLISHED",
    "PUBLICATION_READY",
    "PUBLIC_COMPLETE",
    "PUBLIC_COMPLETE_AUTH_DEFERRED",
})


def evaluate_same_slot_completion_ledger(
    evidence: Mapping[str, Any],
    *,
    existing_ledger: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify the P0.7 report-completion chain without inventing missing proof.

    The ledger is an observability projection over the existing report lifecycle.
    It does not mint delivery acknowledgements or receipts and it cannot rewrite
    historical occurrences. Every report-plane identity is checked against the
    original logical_report_slot.
    """
    row = dict(evidence or {})
    report_slot = str(row.get("logical_report_slot") or "").strip()
    occurrence_id = str(row.get("natural_occurrence_id") or "").strip()

    if existing_ledger is not None:
        prior = dict(existing_ledger)
        if (
            prior.get("status") == "PASS"
            and prior.get("logical_report_slot") == report_slot
            and prior.get("natural_occurrence_id") == occurrence_id
            and prior.get("report_slot_fulfilled") is True
        ):
            prior["idempotent_reuse"] = True
            return prior
        return {
            "status": "FAIL",
            "logical_report_slot": report_slot or None,
            "natural_occurrence_id": occurrence_id or None,
            "report_slot_fulfilled": False,
            "idempotent_reuse": False,
            "terminal_status_only_allowed": False,
            "first_broken_or_unproven_edge": "EXISTING_LEDGER_CONFLICT",
            "edge_classification": {},
            "failures": ["EXISTING_LEDGER_INVALID_OR_CONFLICTING"],
        }

    classifications: dict[str, str] = {}
    failures: list[str] = []

    def mark(edge: str, proven: bool, failure: str | None = None) -> None:
        classifications[edge] = "EXECUTED_AND_PROVEN" if proven else "UNVERIFIED"
        if not proven and failure:
            failures.append(failure)

    slot_valid = bool(report_slot and _parse_aware_timestamp(report_slot) is not None)
    terminal_state = str(row.get("v6_terminal_state") or "").strip().upper()
    terminal_valid = bool(
        str(row.get("governed_v6_run_id") or "").strip()
        and terminal_state in _P07_TERMINAL_V6_STATES
    )
    mark("V6_TERMINAL", terminal_valid, "V6_TERMINAL_NOT_PROVEN")
    mark(
        "TERMINAL_REREAD",
        terminal_valid and row.get("publication_readback_pass") is True,
        "PUBLICATION_READBACK_NOT_PROVEN",
    )

    context_slot = str(row.get("decision_context_slot") or "").strip()
    context_ok = bool(
        slot_valid
        and row.get("decision_context_hydrated") is True
        and context_slot == report_slot
    )
    mark(
        "ACTIVE_DECISION_CONTEXT_HYDRATION",
        context_ok,
        "DECISION_CONTEXT_EXACT_SLOT_NOT_PROVEN",
    )

    prefetch_slot = str(row.get("report_prefetch_logical_slot") or "").strip()
    freshness = str(row.get("report_prefetch_freshness") or "").strip().upper()
    prefetch_ok = bool(
        slot_valid
        and row.get("report_prefetch_identity_match") is True
        and prefetch_slot == report_slot
        and freshness in {
            "CURRENT",
            "FRESH",
            "PASS",
            "AMBER",
            "AMBER_NON_BLOCKING",
            "DEGRADED_NON_BLOCKING",
        }
    )
    mark(
        "EXACT_REPORT_PREFETCH_BINDING",
        prefetch_ok,
        "REPORT_PREFETCH_EXACT_SLOT_NOT_PROVEN",
    )

    weather_ok = bool(
        row.get("weather_attempted") is True
        and str(row.get("weather_status") or "").strip().upper()
        in {"PASS", "DEGRADED", "SOURCE_DEGRADED", "LOW_CONFIDENCE"}
    )
    mark("WEATHER_ATTEMPT", weather_ok, "WEATHER_ATTEMPT_NOT_PROVEN")
    mark(
        "PRE_RENDER_QA",
        row.get("pre_render_qa_pass") is True,
        "PRE_RENDER_QA_NOT_PASSED",
    )

    render_hash = str(row.get("canonical_render_hash") or "")
    render_ok = bool(
        row.get("canonical_render_completed") is True and _is_sha256(render_hash)
    )
    mark("CANONICAL_RENDER", render_ok, "CANONICAL_RENDER_NOT_PROVEN")
    mark(
        "POST_RENDER_QA",
        row.get("post_render_qa_pass") is True,
        "POST_RENDER_QA_NOT_PASSED",
    )
    mark(
        "REPORT_CONTRACT_PASS",
        row.get("report_contract_pass") is True,
        "REPORT_CONTRACT_NOT_PASSED",
    )
    mark("CAN_EMIT", row.get("can_emit") is True, "CAN_EMIT_NOT_TRUE")
    mark(
        "VISIBLE_EMITTED",
        row.get("visible_emitted") is True,
        "VISIBLE_EMITTED_NOT_TRUE",
    )
    mark(
        "DELIVERY_ACKNOWLEDGED",
        row.get("delivery_acknowledged") is True,
        "DELIVERY_ACKNOWLEDGED_NOT_TRUE",
    )
    mark(
        "DELIVERY_PROOF_VALID",
        row.get("delivery_proof_valid") is True,
        "DELIVERY_PROOF_NOT_VALID",
    )

    receipt_slot = str(row.get("canonical_receipt_slot") or "").strip()
    receipt_ok = bool(
        slot_valid
        and _is_sha256(row.get("canonical_receipt_id"))
        and receipt_slot == report_slot
    )
    mark(
        "IMMUTABLE_CANONICAL_RECEIPT",
        receipt_ok,
        "CANONICAL_RECEIPT_EXACT_SLOT_NOT_PROVEN",
    )

    fulfilled = bool(
        row.get("report_slot_fulfilled") is True
        and not failures
        and all(state == "EXECUTED_AND_PROVEN" for state in classifications.values())
    )
    mark(
        "REPORT_SLOT_FULFILLED",
        fulfilled,
        "REPORT_SLOT_FULFILLED_NOT_PROVEN",
    )

    first_unproven = next(
        (edge for edge, state in classifications.items() if state != "EXECUTED_AND_PROVEN"),
        None,
    )
    historical = row.get("historical_immutable") is True
    if historical and row.get("report_slot_fulfilled") is not True:
        fulfilled = False
        if "HISTORICAL_TRUTH_IMMUTABLE" not in failures:
            failures.append("HISTORICAL_TRUTH_IMMUTABLE")

    return {
        **row,
        "status": "PASS" if fulfilled else "FAIL",
        "historical_immutable": historical,
        "logical_report_slot": report_slot or None,
        "natural_occurrence_id": occurrence_id or None,
        "report_slot_fulfilled": fulfilled,
        "edge_classification": classifications,
        "first_broken_or_unproven_edge": first_unproven,
        "terminal_status_only_allowed": False,
        "idempotent_reuse": False,
        "failures": list(dict.fromkeys(failures)),
    }



_P07_LEDGER_SCHEMA_VERSION = "P0_7_SAME_SLOT_COMPLETION_V1"


def _p07_ledger_digest(payload: Mapping[str, Any]) -> str:
    canonical = {
        key: value
        for key, value in dict(payload).items()
        if key not in {"ledger_hash", "readback_valid", "idempotent_reuse"}
    }
    return _proof_digest(canonical)


def seal_same_slot_completion_ledger(
    evidence: Mapping[str, Any],
    *,
    existing_ledger: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal a same-slot completion ledger for persistence beside existing receipt evidence.

    This deliberately reuses the report-delivery owner. It is not a second receipt
    authority: canonical receipt truth remains owned by build_canonical_report_receipt.
    """
    evaluated = evaluate_same_slot_completion_ledger(
        evidence,
        existing_ledger=existing_ledger,
    )
    if evaluated.get("status") != "PASS":
        return {
            **evaluated,
            "schema_version": _P07_LEDGER_SCHEMA_VERSION,
            "immutable": False,
            "ledger_hash": None,
            "readback_valid": False,
        }

    sealed = {
        **evaluated,
        "schema_version": _P07_LEDGER_SCHEMA_VERSION,
        "immutable": True,
        "readback_valid": False,
    }
    sealed["ledger_hash"] = _p07_ledger_digest(sealed)
    return sealed


def validate_same_slot_completion_ledger_readback(
    ledger: Mapping[str, Any] | None,
    *,
    expected_logical_report_slot: str,
    expected_occurrence_identity: str,
) -> dict[str, Any]:
    """Fail closed unless persisted/read-back ledger bytes preserve exact-slot proof."""
    if not isinstance(ledger, Mapping):
        return {
            "status": "FAIL",
            "readback_valid": False,
            "report_slot_fulfilled": False,
            "failures": ["COMPLETION_LEDGER_MISSING"],
        }

    row = dict(ledger)
    failures: list[str] = []
    if row.get("schema_version") != _P07_LEDGER_SCHEMA_VERSION:
        failures.append("COMPLETION_LEDGER_SCHEMA_MISMATCH")
    if row.get("immutable") is not True:
        failures.append("COMPLETION_LEDGER_NOT_IMMUTABLE")
    if row.get("logical_report_slot") != expected_logical_report_slot:
        failures.append("COMPLETION_LEDGER_REPORT_SLOT_MISMATCH")
    if row.get("natural_occurrence_id") != expected_occurrence_identity:
        failures.append("COMPLETION_LEDGER_OCCURRENCE_MISMATCH")
    stored_hash = str(row.get("ledger_hash") or "")
    if not _is_sha256(stored_hash) or stored_hash != _p07_ledger_digest(row):
        failures.append("COMPLETION_LEDGER_HASH_MISMATCH")
    if row.get("status") != "PASS" or row.get("report_slot_fulfilled") is not True:
        failures.append("COMPLETION_LEDGER_NOT_FULFILLED")
    if any(
        state != "EXECUTED_AND_PROVEN"
        for state in dict(row.get("edge_classification") or {}).values()
    ):
        failures.append("COMPLETION_LEDGER_EDGE_UNPROVEN")

    return {
        **row,
        "status": "PASS" if not failures else "FAIL",
        "readback_valid": not failures,
        "report_slot_fulfilled": bool(
            not failures and row.get("report_slot_fulfilled") is True
        ),
        "failures": list(dict.fromkeys(failures)),
    }

# V12 natural-report acceptance observability.
#
# This deliberately extends the existing report-delivery / same-slot evidence owner.
# It is acceptance evidence only. It does not change Canonical routing, V6 factual
# acquisition/publication, scheduler cadence, delivery acknowledgement semantics,
# or the immutable canonical-receipt predicate above.
_V12_NATURAL_ACCEPTANCE_SCHEMA_VERSION = "V12_NATURAL_REPORT_ACCEPTANCE_V1"
_V12_UI_ACK_STATES = frozenset({"PROVEN", "UNAVAILABLE", "NOT_SUPPORTED"})
_V12_ACCEPTANCE_STATES = frozenset({"PASS", "FAIL", "NOT_APPLICABLE", "UNRESOLVED"})


def _v12_nonempty(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _v12_dynamic_trigger(value: Any) -> bool | str:
    if value is True or value is False:
        return bool(value)
    text = str(value or "").strip().upper()
    if text in {"TRUE", "PASS", "TRIGGERED"}:
        return True
    if text in {"FALSE", "NO", "NOT_TRIGGERED"}:
        return False
    return "UNRESOLVED"


def _v12_mode_tokens(value: Any) -> tuple[str, ...]:
    text = str(value or "").strip().upper()
    if not text:
        return ()
    return tuple(
        token
        for token in re.split(r"[+\s,/|]+", text)
        if token
    )


def _v12_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _v12_fixture_rows(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return out
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        out.append(
            {
                "fixture_id": raw.get("fixture_id"),
                "event": raw.get("event", raw.get("gw")),
                "kickoff_time": raw.get("kickoff_time"),
                "started": _v12_optional_bool(raw.get("started")),
                "finished": _v12_optional_bool(raw.get("finished")),
                "finished_provisional": _v12_optional_bool(
                    raw.get("finished_provisional")
                ),
                "minutes": raw.get("minutes"),
                "status": raw.get("status"),
                "evidence_source": raw.get("evidence_source", raw.get("source")),
                "evidence_generated_at": raw.get(
                    "evidence_generated_at", raw.get("generated_at")
                ),
                "checked_at": raw.get("checked_at"),
                "freshness_classification": raw.get(
                    "freshness_classification", raw.get("freshness")
                ),
            }
        )
    return out


def _v12_icon_coverage(
    manager_count_expected: Any,
    manager_picks_covered: Any,
) -> tuple[str, str]:
    try:
        expected = int(manager_count_expected)
        covered = int(manager_picks_covered)
    except (TypeError, ValueError):
        return "UNAVAILABLE", "UNAVAILABLE"
    if expected <= 0 or covered < 0:
        return "UNAVAILABLE", "UNAVAILABLE"
    ratio = f"{covered}/{expected}"
    if covered == expected:
        return ratio, "COMPLETE"
    if covered < expected:
        return ratio, "PARTIAL"
    return ratio, "INVALID"


def _v12_acceptance_digest(payload: Mapping[str, Any]) -> str:
    canonical = {
        key: value
        for key, value in dict(payload).items()
        if key not in {"proof_hash", "readback_valid", "idempotent_reuse"}
    }
    return _proof_digest(canonical)


def build_natural_report_acceptance_proof(
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Build occurrence-bound V12 routing/render acceptance evidence.

    The result is intentionally orthogonal to UI delivery acknowledgement.
    RENDER_PROVEN never implies DELIVERY_UI_ACK=PROVEN. This builder records
    factual execution evidence supplied by the natural occurrence; it does not
    re-route reports, reinterpret fixture lifecycle, acquire data, or mint a
    provider/client acknowledgement.
    """
    row = dict(evidence or {})
    failures: list[str] = []

    occurrence_id = _v12_nonempty(
        row.get("scheduler_occurrence", row.get("natural_occurrence_id"))
    )
    timezone_name = _v12_nonempty(row.get("timezone"))
    observed_at = row.get("observed_at")
    core_slot = row.get("core_logical_slot", row.get("logical_core_slot"))
    scheduler_identity = _v12_nonempty(row.get("scheduler_identity"))

    if not occurrence_id:
        failures.append("SCHEDULER_OCCURRENCE_MISSING")
    if not timezone_name:
        failures.append("TIMEZONE_MISSING")
    if _parse_aware_timestamp(observed_at) is None:
        failures.append("OBSERVED_AT_INVALID")
    if _parse_aware_timestamp(core_slot) is None:
        failures.append("CORE_LOGICAL_SLOT_INVALID")
    if not scheduler_identity:
        failures.append("SCHEDULER_IDENTITY_MISSING")

    core_gate_executed = row.get("core_gate_executed") is True
    core_gate_resolution = _v12_nonempty(row.get("core_gate_resolution"))
    if not core_gate_executed:
        failures.append("CORE_GATE_EXECUTION_NOT_PROVEN")
    if not core_gate_resolution:
        failures.append("CORE_GATE_RESOLUTION_MISSING")

    preliminary_due = row.get("preliminary_report_due")
    final_due = row.get("final_report_due")
    dynamic_checked = row.get("dynamic_evidence_checked") is True
    dynamic_trigger = _v12_dynamic_trigger(row.get("dynamic_trigger"))
    final_mode = _v12_nonempty(row.get("final_mode"))
    if preliminary_due not in {True, False}:
        failures.append("PRELIMINARY_REPORT_DUE_MISSING")
    if final_due not in {True, False}:
        failures.append("FINAL_REPORT_DUE_MISSING")
    if not dynamic_checked:
        failures.append("DYNAMIC_EVIDENCE_NOT_CHECKED")
    if final_due is True and not final_mode:
        failures.append("FINAL_MODE_MISSING")

    fixture_rows = _v12_fixture_rows(row.get("dynamic_fixture_evidence"))
    mode_tokens = _v12_mode_tokens(final_mode)
    match_in_final_mode = "MATCH" in mode_tokens

    if dynamic_trigger is True:
        routing_acceptance = (
            "PASS" if final_due is True and match_in_final_mode else "FAIL"
        )
    elif dynamic_trigger == "UNRESOLVED":
        routing_acceptance = "UNRESOLVED"
    else:
        routing_acceptance = "NOT_APPLICABLE"

    render_attempted = row.get("render_attempted") is True
    render_completed = row.get("render_completed") is True
    rendered_mode = _v12_nonempty(row.get("rendered_mode"))
    section_ids = [
        str(value)
        for value in (row.get("rendered_section_ids") or [])
        if str(value or "").strip()
    ]
    section_names = [
        str(value)
        for value in (row.get("rendered_section_names") or [])
        if str(value or "").strip()
    ]
    section_count = row.get("section_count")
    try:
        section_count_value = int(section_count)
    except (TypeError, ValueError):
        section_count_value = len(section_ids or section_names)
    critical_sections_present = row.get("critical_sections_present") is True
    render_digest = _v12_nonempty(
        row.get("render_content_digest", row.get("visible_body_sha256"))
    )
    render_completed_at = row.get("render_completed_at")
    report_instance_count = row.get("report_instance_count", 1 if final_due else 0)
    try:
        report_instance_count = int(report_instance_count)
    except (TypeError, ValueError):
        report_instance_count = -1

    render_shape_consistent = (
        section_count_value >= 0
        and (
            not section_ids
            or section_count_value == len(section_ids)
        )
        and (
            not section_names
            or section_count_value == len(section_names)
        )
    )
    render_proven = bool(
        render_attempted
        and render_completed
        and rendered_mode
        and critical_sections_present
        and render_shape_consistent
        and _is_sha256(render_digest)
        and _parse_aware_timestamp(render_completed_at) is not None
        and report_instance_count == 1
    )

    if final_due is True and not render_attempted:
        failures.append("RENDER_NOT_ATTEMPTED")
    if render_completed and not render_attempted:
        failures.append("RENDER_COMPLETED_WITHOUT_ATTEMPT")
    if render_completed and not render_shape_consistent:
        failures.append("RENDER_SECTION_COUNT_MISMATCH")
    if final_due is True and report_instance_count != 1:
        failures.append("REPORT_INSTANCE_COUNT_INVALID")

    if routing_acceptance == "PASS":
        render_acceptance = "PASS" if render_proven else "FAIL"
    elif routing_acceptance == "FAIL":
        render_acceptance = "FAIL"
    elif routing_acceptance == "UNRESOLVED":
        render_acceptance = "UNRESOLVED"
    else:
        render_acceptance = (
            "PASS" if final_due is True and render_proven else "NOT_APPLICABLE"
        )

    delivery_ui_ack = str(row.get("delivery_ui_ack") or "UNAVAILABLE").strip().upper()
    if delivery_ui_ack not in _V12_UI_ACK_STATES:
        failures.append("DELIVERY_UI_ACK_STATE_INVALID")
        delivery_ui_ack = "UNAVAILABLE"
    ui_ack_evidence = dict(row.get("ui_ack_evidence") or {})
    if delivery_ui_ack == "PROVEN":
        ack_id = _v12_nonempty(
            ui_ack_evidence.get(
                "provider_receipt_id", ui_ack_evidence.get("delivery_ack_id")
            )
        )
        ack_time = ui_ack_evidence.get(
            "acknowledged_at", ui_ack_evidence.get("delivered_at")
        )
        if not ack_id or _parse_aware_timestamp(ack_time) is None:
            failures.append("DELIVERY_UI_ACK_PROOF_INCOMPLETE")
            delivery_ui_ack = "UNAVAILABLE"
            ui_ack_evidence = {}
    elif ui_ack_evidence:
        # Do not retain pseudo-ACK payloads when the channel is unavailable.
        ui_ack_evidence = {}

    locked = {
        "locked_team_source": row.get("locked_team_source"),
        "locked_team_status": row.get("locked_team_status"),
        "submitted_15_available": _v12_optional_bool(
            row.get("submitted_15_available")
        ),
        "xi_available": _v12_optional_bool(row.get("xi_available")),
        "bench_available": _v12_optional_bool(row.get("bench_available")),
        "captain_available": _v12_optional_bool(row.get("captain_available")),
        "vice_available": _v12_optional_bool(row.get("vice_available")),
    }

    picks_coverage, coverage_status = _v12_icon_coverage(
        row.get("manager_count_expected"), row.get("manager_picks_covered")
    )
    icon_plus = {
        "league_id": row.get("league_id"),
        "league_name": row.get("league_name"),
        "icon_live_requested": _v12_optional_bool(row.get("icon_live_requested")),
        "icon_live_status": row.get("icon_live_status"),
        "manager_count_expected": row.get("manager_count_expected"),
        "manager_picks_covered": row.get("manager_picks_covered"),
        "picks_coverage": picks_coverage,
        "picks_coverage_status": coverage_status,
        "ownership_available": _v12_optional_bool(row.get("ownership_available")),
        "starter_available": _v12_optional_bool(row.get("starter_available")),
        "captain_available": _v12_optional_bool(
            row.get("icon_captain_available", row.get("captain_coverage_available"))
        ),
        "vice_available": _v12_optional_bool(
            row.get("icon_vice_available", row.get("vice_coverage_available"))
        ),
        "eo_status": row.get("eo_status"),
        "live_points_status": row.get("live_points_status"),
    }

    proof = {
        "schema_version": _V12_NATURAL_ACCEPTANCE_SCHEMA_VERSION,
        "proof_kind": "V12_NATURAL_REPORT_ACCEPTANCE_PROOF",
        "authoritative": False,
        "factual_authority": False,
        "report_authority": False,
        "methodology_authority": False,
        "decision_authority": False,
        "scheduler_authority": False,
        "durable_acceptance_evidence": True,
        "persistence_owner": (
            "src/runtime_v6/domains/report_plane/report_delivery.py"
            "::same_slot_completion_evidence"
        ),
        "occurrence": {
            "scheduler_occurrence": occurrence_id,
            "timezone": timezone_name,
            "observed_at": observed_at,
            "core_logical_slot": core_slot,
            "scheduler_identity": scheduler_identity,
        },
        "core": {
            "core_gate_executed": core_gate_executed,
            "core_gate_resolution": core_gate_resolution,
            "same_slot_fulfilled": _v12_optional_bool(
                row.get("same_slot_fulfilled")
            ),
            "bound_v6_run_id": row.get("bound_v6_run_id"),
            "v6_publication_sha": row.get(
                "v6_publication_sha", row.get("data_publication_sha")
            ),
            "v6_generation": row.get("v6_generation"),
            "publish_integrity": row.get("publish_integrity"),
            "authoritative_runtime_snapshot": _v12_optional_bool(
                row.get("authoritative_runtime_snapshot")
            ),
            "duplicate_acquisition": _v12_optional_bool(
                row.get("duplicate_acquisition")
            ),
        },
        "report_due": {
            "preliminary_report_due": preliminary_due,
            "preliminary_reason": row.get("preliminary_reason"),
            "dynamic_evidence_checked": dynamic_checked,
            "dynamic_trigger": dynamic_trigger,
            "dynamic_trigger_reason": row.get("dynamic_trigger_reason"),
            "final_report_due": final_due,
            "final_mode": final_mode,
        },
        "dynamic_fixture_evidence": fixture_rows,
        "render": {
            "render_attempted": render_attempted,
            "render_completed": render_completed,
            "render_proven": render_proven,
            "rendered_mode": rendered_mode,
            "rendered_section_ids": section_ids,
            "rendered_section_names": section_names,
            "section_count": section_count_value,
            "critical_sections_present": critical_sections_present,
            "render_content_digest": render_digest,
            "render_completed_at": render_completed_at,
            "report_instance_count": report_instance_count,
        },
        "locked_team": locked,
        "icon_plus": icon_plus,
        "delivery": {
            "delivery_ui_ack": delivery_ui_ack,
            "ui_ack_evidence": ui_ack_evidence or None,
            "rendering_implies_ui_delivery": False,
        },
        "acceptance": {
            "routing_acceptance": routing_acceptance,
            "render_acceptance": render_acceptance,
            "ui_delivery_ack": delivery_ui_ack,
        },
        "historical_immutable": row.get("historical_immutable") is True,
        "proof_existed_at_occurrence": row.get("proof_existed_at_occurrence") is True,
        "evidence_integrity": "PASS" if not failures else "FAIL",
        "failures": list(dict.fromkeys(failures)),
        "immutable": False,
        "readback_valid": False,
        "proof_hash": None,
        "idempotent_reuse": False,
    }
    return proof


def seal_natural_report_acceptance_proof(
    evidence: Mapping[str, Any],
    *,
    existing_proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal prospective acceptance evidence without fabricating historical receipts."""
    built = build_natural_report_acceptance_proof(evidence)
    occurrence_id = built["occurrence"]["scheduler_occurrence"]

    if existing_proof is not None:
        prior = dict(existing_proof)
        prior_occurrence = (
            prior.get("occurrence", {}).get("scheduler_occurrence")
            if isinstance(prior.get("occurrence"), Mapping)
            else None
        )
        if (
            prior.get("schema_version") == _V12_NATURAL_ACCEPTANCE_SCHEMA_VERSION
            and prior.get("immutable") is True
            and prior_occurrence == occurrence_id
            and _is_sha256(prior.get("proof_hash"))
            and prior.get("proof_hash") == _v12_acceptance_digest(prior)
        ):
            prior["idempotent_reuse"] = True
            return prior
        return {
            **built,
            "evidence_integrity": "FAIL",
            "failures": list(
                dict.fromkeys(
                    [*built.get("failures", []), "EXISTING_ACCEPTANCE_PROOF_CONFLICT"]
                )
            ),
        }

    if (
        built.get("historical_immutable") is True
        and built.get("proof_existed_at_occurrence") is not True
    ):
        return {
            **built,
            "evidence_integrity": "FAIL",
            "failures": list(
                dict.fromkeys(
                    [
                        *built.get("failures", []),
                        "HISTORICAL_ACCEPTANCE_PROOF_BACKFILL_FORBIDDEN",
                    ]
                )
            ),
        }

    sealed = {
        **built,
        "immutable": True,
        "readback_valid": False,
    }
    sealed["proof_hash"] = _v12_acceptance_digest(sealed)
    return sealed


def validate_natural_report_acceptance_proof_readback(
    proof: Mapping[str, Any] | None,
    *,
    expected_scheduler_occurrence: str,
) -> dict[str, Any]:
    """Verify persisted bytes/identity; acceptance PASS/FAIL remains orthogonal."""
    if not isinstance(proof, Mapping):
        return {
            "status": "FAIL",
            "readback_valid": False,
            "failures": ["NATURAL_ACCEPTANCE_PROOF_MISSING"],
        }
    row = dict(proof)
    failures: list[str] = []
    occurrence = (
        dict(row.get("occurrence") or {})
        if isinstance(row.get("occurrence"), Mapping)
        else {}
    )
    if row.get("schema_version") != _V12_NATURAL_ACCEPTANCE_SCHEMA_VERSION:
        failures.append("NATURAL_ACCEPTANCE_PROOF_SCHEMA_MISMATCH")
    if row.get("immutable") is not True:
        failures.append("NATURAL_ACCEPTANCE_PROOF_NOT_IMMUTABLE")
    if occurrence.get("scheduler_occurrence") != expected_scheduler_occurrence:
        failures.append("NATURAL_ACCEPTANCE_PROOF_OCCURRENCE_MISMATCH")
    stored_hash = str(row.get("proof_hash") or "")
    if not _is_sha256(stored_hash) or stored_hash != _v12_acceptance_digest(row):
        failures.append("NATURAL_ACCEPTANCE_PROOF_HASH_MISMATCH")
    acceptance = dict(row.get("acceptance") or {})
    for key in ("routing_acceptance", "render_acceptance"):
        if acceptance.get(key) not in _V12_ACCEPTANCE_STATES:
            failures.append(f"NATURAL_ACCEPTANCE_{key.upper()}_INVALID")
    if acceptance.get("ui_delivery_ack") not in _V12_UI_ACK_STATES:
        failures.append("NATURAL_ACCEPTANCE_UI_ACK_INVALID")

    return {
        **row,
        "status": "PASS" if not failures else "FAIL",
        "readback_valid": not failures,
        "failures": list(dict.fromkeys([*row.get("failures", []), *failures])),
    }

