from __future__ import annotations

import pytest

from src.runtime_v6.delivery_integrity import DeliveryIntegrityError, resolve_report_slot_decision
from src.runtime_v6.report_contract import resolve_report_scope_matrix
from src.runtime_v6.report_delivery import (
    build_delivery_proof,
    finalize_delivery_outcome,
    validate_delivery_proof,
)
from src.runtime_v6.report_recovery import plan_fail_safe_recovery


LOGICAL_SLOT = "2026-09-17T04:30:00+07:00"
REPORT_SLOT_ID = "2026-09-17T04:30+07:00|DEEP"


def _post_render_pass():
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
        "visible_body_validated": True,
    }


def _scope(**overrides):
    row = {
        "required": True,
        "auth_required": False,
        "volatile": True,
        "fresh_v6_available": True,
        "v6_scope_state": "CURRENT",
        "retrieval_state": "COMPLETE",
        "direct_fresh_available": False,
        "last_good_available": False,
    }
    row.update(overrides)
    return row


def _delivery_failure():
    return build_delivery_proof(
        post_render_qa=_post_render_pass(),
        report_slot_id=REPORT_SLOT_ID,
        delivery_status="ACKNOWLEDGED",
        delivery_channel="CHATGPT",
        delivery_target="USER_SESSION",
        provider_receipt_id="",
        delivered_at="2026-09-17T04:30:08+07:00",
    )


def _valid_delivery():
    post = _post_render_pass()
    proof = build_delivery_proof(
        post_render_qa=post,
        report_slot_id=REPORT_SLOT_ID,
        delivery_status="ACKNOWLEDGED",
        delivery_channel="CHATGPT",
        delivery_target="USER_SESSION",
        provider_receipt_id="receipt-r7-001",
        delivered_at="2026-09-17T04:30:08+07:00",
    )
    return validate_delivery_proof(
        proof=proof,
        post_render_qa=post,
        expected_report_slot_id=REPORT_SLOT_ID,
    )


def test_unacknowledged_delivery_becomes_explicit_delivery_failed_state():
    failed = _delivery_failure()

    assert failed["status"] == "FAIL"
    assert failed["report_delivered"] is False
    assert failed["report_state"] == "DELIVERY_FAILED"
    assert failed["delivery_state"] == "FAILED"
    assert failed["next_action"] == "DELIVERY_PROOF_RECOVERY"


def test_delivery_failed_slot_is_same_slot_recoverable_not_active_build():
    decision = resolve_report_slot_decision(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        report_state="DELIVERY_FAILED",
        v6_already_published=True,
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )

    assert decision["report_slot_id"] == REPORT_SLOT_ID
    assert decision["report_delivered"] is False
    assert decision["report_required"] is True
    assert decision["start_build"] is False
    assert decision["reason"] == "DELIVERY_PROOF_RECOVERY"


def test_fail_safe_planner_retries_same_r6_artifact_for_receipt_only_failure():
    post = _post_render_pass()
    failed = _delivery_failure()

    plan = plan_fail_safe_recovery(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        report_state=failed["report_state"],
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
        post_render_qa=post,
        delivery_result=failed,
        failed_healthy_scopes=[],
        attempt_count=0,
        max_attempts=2,
    )

    assert plan["report_slot_id"] == REPORT_SLOT_ID
    assert plan["retry_now"] is True
    assert plan["next_attempt_count"] == 1
    assert plan["same_artifact_retry"] is True
    assert plan["compute_fingerprint"] == post["compute_fingerprint"]
    assert plan["render_contract_token"] == post["render_contract_token"]
    assert plan["recovery_steps"] == [
        "DELIVERY_PROOF_RECOVERY",
        "DELIVER",
        "ACKNOWLEDGED_RECEIPT",
    ]
    assert plan["legacy_fallback_allowed"] is False


def test_invalid_post_render_requires_rerender_and_reqa_before_delivery_retry():
    post = _post_render_pass()
    post.update(
        {
            "status": "FAIL",
            "qa_passed": False,
            "report_state": "QA_FAILED",
            "next_action": "RENDER_RECOVERY",
        }
    )

    plan = plan_fail_safe_recovery(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        report_state="QA_FAILED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
        post_render_qa=post,
        delivery_result=None,
        failed_healthy_scopes=[],
        attempt_count=0,
        max_attempts=2,
    )

    assert plan["same_artifact_retry"] is False
    assert plan["recovery_steps"] == [
        "RENDER_RECOVERY",
        "POST_RENDER_QA",
        "BUILD_DELIVERY_PROOF",
        "DELIVER",
        "ACKNOWLEDGED_RECEIPT",
    ]


def test_healthy_source_assertion_failure_forces_full_same_run_recovery_chain():
    plan = plan_fail_safe_recovery(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        report_state="QA_FAILED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
        post_render_qa={"status": "FAIL", "qa_stage": "POST_RENDER", "qa_passed": False},
        delivery_result=None,
        failed_healthy_scopes=["official_universe", "icon_mini_league"],
        attempt_count=0,
        max_attempts=2,
    )

    assert plan["report_slot_id"] == REPORT_SLOT_ID
    assert plan["failed_healthy_scopes"] == ["official_universe", "icon_mini_league"]
    assert plan["exact_scope_recovery_required"] is True
    assert plan["recovery_steps"] == [
        "SAME_V6_RETRIEVAL_RECOVERY",
        "RETRIEVE",
        "RECOMPUTE",
        "RERENDER",
        "POST_RENDER_QA",
        "BUILD_DELIVERY_PROOF",
        "DELIVER",
        "ACKNOWLEDGED_RECEIPT",
    ]
    assert plan["v6_data_plane_mutation_allowed"] is False


def test_retry_exhaustion_schedules_catch_up_without_claiming_delivery():
    failed = _delivery_failure()
    plan = plan_fail_safe_recovery(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        report_state=failed["report_state"],
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
        post_render_qa=_post_render_pass(),
        delivery_result=failed,
        failed_healthy_scopes=[],
        attempt_count=2,
        max_attempts=2,
    )

    assert plan["report_slot_id"] == REPORT_SLOT_ID
    assert plan["retry_now"] is False
    assert plan["retry_exhausted"] is True
    assert plan["catch_up_eligible"] is True
    assert plan["next_action"] == "SCHEDULE_CATCH_UP"
    assert plan["report_delivered"] is False


def test_acknowledged_delivery_can_be_complete_or_degraded_without_pass_degraded_state():
    delivery = _valid_delivery()
    complete_matrix = resolve_report_scope_matrix(
        {"official_universe": _scope(), "icon_mini_league": _scope()},
        auth_status="NOT REQUESTED",
    )
    degraded_matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(),
            "private_team_value": _scope(required=False, auth_required=True),
        },
        auth_status="EXPIRED",
    )

    complete = finalize_delivery_outcome(
        validated_delivery=delivery,
        expected_report_slot_id=REPORT_SLOT_ID,
        scope_matrix=complete_matrix,
    )
    degraded = finalize_delivery_outcome(
        validated_delivery=delivery,
        expected_report_slot_id=REPORT_SLOT_ID,
        scope_matrix=degraded_matrix,
    )

    assert complete["status"] == "PASS"
    assert complete["delivery_status"] == "DELIVERED"
    assert complete["report_quality"] == "COMPLETE"
    assert complete["degraded_scopes"] == []

    assert degraded["status"] == "PASS"
    assert degraded["delivery_status"] == "DELIVERED"
    assert degraded["report_quality"] == "DEGRADED"
    assert degraded["degraded_scopes"] == ["private_team_value"]
    assert degraded["status"] != "PASS_DEGRADED"


def test_finalization_rejects_blocked_scope_even_with_valid_receipt():
    blocked_matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(
                fresh_v6_available=False,
                v6_scope_state="V6_SCOPE_MISSING",
                direct_fresh_available=False,
                last_good_available=False,
            )
        },
        auth_status="NOT REQUESTED",
    )

    with pytest.raises(DeliveryIntegrityError, match="blocking scope"):
        finalize_delivery_outcome(
            validated_delivery=_valid_delivery(),
            expected_report_slot_id=REPORT_SLOT_ID,
            scope_matrix=blocked_matrix,
        )


def test_finalization_rejects_receipt_for_different_slot():
    delivery = dict(_valid_delivery())
    delivery["delivered_report_slot_id"] = "2026-09-17T05:30+07:00|PRICE"
    matrix = resolve_report_scope_matrix(
        {"official_universe": _scope()},
        auth_status="NOT REQUESTED",
    )

    with pytest.raises(DeliveryIntegrityError, match="same report slot"):
        finalize_delivery_outcome(
            validated_delivery=delivery,
            expected_report_slot_id=REPORT_SLOT_ID,
            scope_matrix=matrix,
        )
