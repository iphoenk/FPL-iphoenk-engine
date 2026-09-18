from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.delivery_integrity import build_report_slot_id
from src.runtime_v6.domains.report_plane.report_contract import evaluate_rolling_natural_acceptance
from src.runtime_v6.domains.report_plane.report_delivery import (
    build_canonical_report_receipt,
    canonical_receipt_acceptance,
    record_delivery_acknowledgement,
    record_visible_emission,
    validate_delivery_acknowledgement,
)


LOGICAL = "2026-09-18T18:30:00+07:00"


def _slot(report_type="DEADLINE", logical=LOGICAL):
    return build_report_slot_id(logical_slot=logical, report_type=report_type)


def _pre(slot=None):
    slot = slot or _slot()
    return {
        "status": "PASS",
        "qa_stage": "PRE_RENDER",
        "qa_passed": True,
        "report_slot_id": slot,
        "evaluated_at": "2026-09-18T18:30:05+07:00",
        "decision_context": {
            "status": "PASS",
            "context_kind": "CURRENT_DECISION_CONTEXT",
            "context_fingerprint": "d" * 64,
        },
        "prefetch_identity": {
            "status": "PASS",
            "report_prefetch_run_id": "prefetch-1830",
        },
    }


def _post(slot=None):
    slot = slot or _slot()
    return {
        "status": "PASS",
        "qa_stage": "POST_RENDER",
        "qa_passed": True,
        "delivery_ready": False,
        "report_state": "BUILDING",
        "next_action": "BUILD_DELIVERY_PROOF",
        "legacy_fallback_allowed": False,
        "compute_fingerprint": "a" * 64,
        "render_contract_token": "b" * 64,
        "mandatory_scope_gate_pass": True,
        "input_completeness_pass": True,
        "pre_render_qa_pass": True,
        "post_render_qa_pass": True,
        "report_contract_pass": True,
        "can_emit": True,
        "report_slot_id": slot,
        "render_completed_at": "2026-09-18T18:30:10+07:00",
        "evaluated_at": "2026-09-18T18:30:15+07:00",
        "visible_body_sha256": "c" * 64,
        "provenance": {"p05_render_gate_token": "e" * 64},
    }


def _occurrence(
    *,
    slot=None,
    occurrence_identity="natural-1830",
    report_kind="DEADLINE",
    report_mode="DEADLINE",
    **overrides,
):
    slot = slot or _slot(report_mode)
    row = {
        "occurrence_identity": occurrence_identity,
        "report_slot_id": slot,
        "intended_report_slot": LOGICAL,
        "report_kind": report_kind,
        "report_mode": report_mode,
        "deadline_active": True,
        "occurrence_state": "ON_TIME",
        "observed_at": "2026-09-18T18:30:01+07:00",
        "data_logical_slot": "2026-09-18T18:00:00+07:00",
        "data_publication_sha": "f" * 40,
        "data_slot_fulfilled": True,
        "report_slot_due": True,
        "transport_failed": False,
        "recovery": False,
        "replacement_report_slot_used": False,
    }
    row.update(overrides)
    return row


def _visible(
    *,
    slot=None,
    occurrence_identity="natural-1830",
    producer="FPL_MASTER_REPORT_PLANE",
    status_only=False,
    emitted_at="2026-09-18T18:30:20+07:00",
    post=None,
):
    return record_visible_emission(
        post_render_qa=post or _post(slot),
        report_slot_id=slot or _slot(),
        occurrence_identity=occurrence_identity,
        producer_identity=producer,
        emitted_at=emitted_at,
        status_only=status_only,
    )


def _ack(
    visible=None,
    *,
    ack_id="ack-1830",
    acknowledged_at="2026-09-18T18:30:21+07:00",
    provenance=None,
    authoritative=True,
):
    return record_delivery_acknowledgement(
        visible_emission=visible or _visible(),
        delivery_ack_id=ack_id,
        acknowledged_at=acknowledged_at,
        ack_source="INTERNAL_PLATFORM_ACK",
        ack_provenance=provenance or {"platform_event_id": ack_id},
        authoritative=authoritative,
    )


def _validated(
    ack=None,
    *,
    slot=None,
    occurrence_identity="natural-1830",
    producer="FPL_MASTER_REPORT_PLANE",
    receipt_generated_at="2026-09-18T18:30:22+07:00",
    consumed_ack_ids=(),
):
    return validate_delivery_acknowledgement(
        acknowledgement=ack or _ack(),
        expected_report_slot_id=slot or _slot(),
        expected_occurrence_identity=occurrence_identity,
        expected_producer_identity=producer,
        receipt_generated_at=receipt_generated_at,
        consumed_ack_ids=consumed_ack_ids,
    )


def _receipt(
    *,
    occurrence=None,
    pre=None,
    post=None,
    validated=None,
    receipt_generated_at="2026-09-18T18:30:22+07:00",
    existing_receipt=None,
):
    occurrence = occurrence or _occurrence()
    slot = occurrence["report_slot_id"]
    return build_canonical_report_receipt(
        occurrence=occurrence,
        pre_render_qa=pre or _pre(slot),
        post_render_qa=post or _post(slot),
        validated_acknowledgement=validated or _validated(
            slot=slot,
            occurrence_identity=occurrence["occurrence_identity"],
            receipt_generated_at=receipt_generated_at,
        ),
        receipt_generated_at=receipt_generated_at,
        existing_receipt=existing_receipt,
    )


def _acceptance_row(receipt=None, *, due=True, logical=LOGICAL, occurrence_identity="natural-1830"):
    return {
        "natural": True,
        "schedule_kind": "chatgpt_scheduler",
        "logical_slot": logical,
        "core_acceptance": "PASS",
        "mandatory_visible_report": due,
        "report_slot_id": _slot(logical=logical),
        "occurrence_identity": occurrence_identity,
        "canonical_report_receipt": receipt,
    }


def test_01_complete_natural_delivery_receipt_passes_and_is_consumed_by_acceptance():
    receipt = _receipt()
    assert receipt["status"] == "PASS"
    assert receipt["report_slot_fulfilled"] is True
    assert canonical_receipt_acceptance(
        receipt,
        expected_report_slot_id=_slot(),
        expected_occurrence_identity="natural-1830",
    ) is True
    rolling = evaluate_rolling_natural_acceptance([_acceptance_row(receipt)])
    assert rolling["latest_window"][0]["acceptance"] == "PASS"


def test_02_missing_pre_render_qa_fails_receipt():
    pre = _pre()
    pre["status"] = "FAIL"
    receipt = _receipt(pre=pre)
    assert receipt["status"] == "FAIL"
    assert "PRE_RENDER_QA_NOT_PASSED" in receipt["failures"]


def test_03_missing_post_render_qa_blocks_visible_emission_and_receipt():
    post = _post()
    post["status"] = "FAIL"
    visible = _visible(post=post)
    assert visible["status"] == "FAIL"
    assert visible["visible_emitted"] is False


def test_04_status_only_delivery_cannot_fulfill_report_slot():
    visible = _visible(status_only=True)
    ack = _ack(visible)
    validated = _validated(ack)
    assert validated["status"] == "FAIL"
    assert "STATUS_ONLY_ACK_NOT_CANONICAL" in validated["failures"]


def test_05_ack_wrong_report_slot_id_fails():
    ack = _ack()
    ack["report_slot_id"] = _slot(logical="2026-09-18T17:30:00+07:00")
    validated = _validated(ack)
    assert validated["status"] == "FAIL"
    assert "ACK_REPORT_SLOT_MISMATCH" in validated["failures"]


def test_06_previous_slot_receipt_cannot_satisfy_current_slot():
    previous = _receipt()
    assert canonical_receipt_acceptance(
        previous,
        expected_report_slot_id=_slot(logical="2026-09-18T19:30:00+07:00"),
    ) is False


def test_07_manual_substitute_cannot_satisfy_natural_occurrence():
    visible = _visible(occurrence_identity="manual-1830")
    ack = _ack(visible)
    validated = _validated(ack, occurrence_identity="manual-1830")
    natural = _occurrence(occurrence_identity="natural-1830")
    receipt = _receipt(occurrence=natural, validated=validated)
    assert receipt["status"] == "FAIL"
    assert "OCCURRENCE_IDENTITY_MISMATCH" in receipt["failures"]


def test_08_allowed_recovery_preserves_original_slot_and_passes():
    occurrence = _occurrence(
        recovery=True,
        recovery_allowed=True,
        original_report_slot_id=_slot(),
    )
    receipt = _receipt(occurrence=occurrence)
    assert receipt["status"] == "PASS"
    assert receipt["recovery"] is True


def test_09_replacement_slot_recovery_fails():
    occurrence = _occurrence(
        recovery=True,
        recovery_allowed=True,
        original_report_slot_id=_slot(),
        replacement_report_slot_used=True,
    )
    receipt = _receipt(occurrence=occurrence)
    assert receipt["status"] == "FAIL"
    assert "REPLACEMENT_REPORT_SLOT_FORBIDDEN" in receipt["failures"]


def test_10_v6_degraded_but_valid_report_can_fulfill():
    occurrence = _occurrence(data_slot_fulfilled=False, v6_degraded=True)
    receipt = _receipt(occurrence=occurrence)
    assert receipt["status"] == "PASS"
    assert receipt["data_slot_fulfilled"] is False
    assert receipt["report_slot_fulfilled"] is True


def test_11_transport_degraded_is_independent_of_valid_report_delivery():
    occurrence = _occurrence(transport_failed=True)
    receipt = _receipt(occurrence=occurrence)
    assert receipt["status"] == "PASS"
    assert receipt["transport_failed"] is True
    assert receipt["report_slot_fulfilled"] is True


def test_12_duplicate_ack_is_idempotent_and_does_not_create_second_receipt():
    first = _receipt()
    second = _receipt(existing_receipt=first)
    assert second["receipt_id"] == first["receipt_id"]
    assert second["idempotent_reuse"] is True
    assert second["duplicate_ack_observed"] is False


def test_13_due_report_without_delivery_fails():
    invalid = {
        "status": "FAIL",
        "report_slot_id": _slot(),
        "visible_emitted": False,
        "delivery_acknowledged": False,
        "delivery_proof_valid": False,
    }
    receipt = _receipt(validated=invalid)
    assert receipt["status"] == "FAIL"
    assert "VISIBLE_EMITTED_NOT_TRUE" in receipt["failures"]


def test_14_not_due_occurrence_requires_no_receipt():
    row = _acceptance_row(receipt=None, due=False)
    rolling = evaluate_rolling_natural_acceptance([row])
    assert rolling["latest_window"][0]["acceptance"] == "PASS"


def test_15_deadline_match_overlap_has_one_canonical_receipt():
    slot = _slot("DEADLINE+MATCH")
    occurrence = _occurrence(slot=slot, report_mode="DEADLINE+MATCH")
    receipt = _receipt(
        occurrence=occurrence,
        pre=_pre(slot),
        post=_post(slot),
        validated=_validated(
            ack=_ack(_visible(slot=slot, post=_post(slot))),
            slot=slot,
            occurrence_identity=occurrence["occurrence_identity"],
        ),
    )
    assert receipt["status"] == "PASS"
    assert receipt["report_slot_id"] == slot


def test_16_final_match_overlap_has_one_canonical_receipt():
    slot = _slot("FINAL+MATCH")
    occurrence = _occurrence(slot=slot, report_mode="FINAL+MATCH")
    visible = _visible(slot=slot, post=_post(slot))
    receipt = _receipt(
        occurrence=occurrence,
        pre=_pre(slot),
        post=_post(slot),
        validated=_validated(
            ack=_ack(visible),
            slot=slot,
            occurrence_identity=occurrence["occurrence_identity"],
        ),
    )
    assert receipt["status"] == "PASS"


def test_17_price_overlap_has_one_canonical_receipt():
    slot = _slot("PRICE")
    occurrence = _occurrence(slot=slot, report_kind="PRICE", report_mode="PRICE")
    visible = _visible(slot=slot, post=_post(slot))
    receipt = _receipt(
        occurrence=occurrence,
        pre=_pre(slot),
        post=_post(slot),
        validated=_validated(
            ack=_ack(visible),
            slot=slot,
            occurrence_identity=occurrence["occurrence_identity"],
        ),
    )
    assert receipt["status"] == "PASS"


def test_18_ack_before_render_completion_fails_chronology():
    visible = _visible()
    ack = _ack(
        visible,
        acknowledged_at="2026-09-18T18:30:09+07:00",
    )
    assert ack["status"] == "FAIL"
    assert "ACK_BEFORE_VISIBLE_EMIT" in ack["failures"]


def test_19_missing_ack_provenance_fails():
    visible = _visible()
    ack = record_delivery_acknowledgement(
        visible_emission=visible,
        delivery_ack_id="ack-no-provenance",
        acknowledged_at="2026-09-18T18:30:21+07:00",
        ack_source="INTERNAL_PLATFORM_ACK",
        ack_provenance={},
        authoritative=True,
    )
    assert ack["status"] == "FAIL"
    assert "ACK_PROVENANCE_MISSING" in ack["failures"]


def test_20_exact_same_slot_canonical_receipt_passes():
    receipt = _receipt()
    assert receipt["same_slot_binding"] is True
    assert receipt["delivery_proof_valid"] is True
    assert receipt["delivery_acknowledged"] is True


def test_21_stale_ack_before_visible_emit_fails():
    ack = _ack(acknowledged_at="2026-09-18T18:29:59+07:00")
    assert ack["status"] == "FAIL"
    assert "ACK_BEFORE_VISIBLE_EMIT" in ack["failures"]


def test_22_reused_ack_id_fails_proof_validation():
    ack = _ack(ack_id="ack-reused")
    validated = _validated(ack, consumed_ack_ids=("ack-reused",))
    assert validated["status"] == "FAIL"
    assert "DELIVERY_ACK_REUSED" in validated["failures"]


def test_23_duplicate_delivery_attempt_keeps_singular_fulfillment():
    first = _receipt()
    second_visible = _visible(emitted_at="2026-09-18T18:30:23+07:00")
    second_ack = _ack(
        second_visible,
        ack_id="ack-1830-duplicate",
        acknowledged_at="2026-09-18T18:30:24+07:00",
    )
    second_validated = _validated(
        second_ack,
        receipt_generated_at="2026-09-18T18:30:25+07:00",
    )
    second = _receipt(
        validated=second_validated,
        receipt_generated_at="2026-09-18T18:30:25+07:00",
        existing_receipt=first,
    )
    assert second["receipt_id"] == first["receipt_id"]
    assert second["duplicate_ack_observed"] is True


def test_24_status_notification_then_canonical_report_counts_only_canonical():
    status_visible = _visible(status_only=True)
    status_ack = _ack(status_visible, ack_id="status-ack")
    status_validated = _validated(status_ack)
    assert status_validated["delivery_proof_valid"] is False

    canonical = _receipt()
    assert canonical_receipt_acceptance(canonical) is True


def test_25_historical_1730_remains_immutable_and_cannot_be_backfilled():
    historical_slot = _slot(
        "DEADLINE",
        logical="2026-09-18T17:30:00+07:00",
    )
    historical_truth = {
        "core_pass": True,
        "v6_pass": True,
        "visible_delivery_observed": True,
        "report_quality": "FAIL",
        "canonical_receipt_proven": False,
    }
    before = deepcopy(historical_truth)
    occurrence = _occurrence(
        slot=historical_slot,
        occurrence_identity="natural-1730-historical",
        historical_immutable=True,
        canonical_receipt_existed_at_occurrence=False,
        intended_report_slot="2026-09-18T17:30:00+07:00",
    )
    pre = _pre(historical_slot)
    post = _post(historical_slot)
    visible = _visible(
        slot=historical_slot,
        occurrence_identity="natural-1730-historical",
        emitted_at="2026-09-18T17:30:20+07:00",
        post=post,
    )
    ack = _ack(
        visible,
        ack_id="hypothetical-1730",
        acknowledged_at="2026-09-18T17:30:21+07:00",
    )
    validated = _validated(
        ack,
        slot=historical_slot,
        occurrence_identity="natural-1730-historical",
        receipt_generated_at="2026-09-18T17:30:22+07:00",
    )
    receipt = build_canonical_report_receipt(
        occurrence=occurrence,
        pre_render_qa=pre,
        post_render_qa=post,
        validated_acknowledgement=validated,
        receipt_generated_at="2026-09-18T17:30:22+07:00",
    )
    assert receipt["status"] == "FAIL"
    assert "HISTORICAL_RECEIPT_BACKFILL_FORBIDDEN" in receipt["failures"]
    assert historical_truth == before
    assert historical_truth["canonical_receipt_proven"] is False
