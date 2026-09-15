from __future__ import annotations

from src.runtime_v6 import delivery_integrity


def _delivery_module():
    from src.runtime_v6 import report_delivery

    return report_delivery


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
    }


def _proof(**overrides):
    kwargs = {
        "post_render_qa": _post_render_pass(),
        "report_slot_id": "2026-09-16T04:30+07:00|DEEP",
        "delivery_status": "ACKNOWLEDGED",
        "delivery_channel": "CHATGPT",
        "delivery_target": "USER_SESSION",
        "provider_receipt_id": "receipt-0430-001",
        "delivered_at": "2026-09-16T04:30:08+07:00",
    }
    kwargs.update(overrides)
    return _delivery_module().build_delivery_proof(**kwargs)


def test_acknowledged_delivery_builds_tamper_evident_proof_but_not_a_second_send():
    result = _proof()

    assert result["status"] == "PASS"
    assert result["delivery_proof_valid"] is True
    assert result["report_delivered"] is True
    assert result["report_state"] == "DELIVERED"
    assert result["delivery_ready"] is False
    assert result["next_action"] == "NONE"
    assert result["report_slot_id"] == "2026-09-16T04:30+07:00|DEEP"
    assert result["compute_fingerprint"] == "a" * 64
    assert result["render_contract_token"] == "b" * 64
    assert result["delivery_status"] == "ACKNOWLEDGED"
    assert result["delivery_channel"] == "CHATGPT"
    assert result["delivery_target"] == "USER_SESSION"
    assert result["provider_receipt_id"] == "receipt-0430-001"
    assert len(result["delivery_proof_id"]) == 64


def test_delivery_proof_is_blocked_unless_wave6_post_render_contract_passed_exactly():
    post_render = _post_render_pass()
    post_render["next_action"] = "RENDER_RECOVERY"
    post_render["report_state"] = "QA_FAILED"
    post_render["status"] = "FAIL"
    post_render["qa_passed"] = False

    result = _proof(post_render_qa=post_render)

    assert result["status"] == "BLOCKED"
    assert result["delivery_proof_valid"] is False
    assert result["report_delivered"] is False
    assert result["report_state"] == "QA_FAILED"
    assert result["delivery_ready"] is False
    assert result["next_action"] == "POST_RENDER_QA"
    assert result["delivery_proof_id"] is None
    assert result["failures"] == ["POST_RENDER_QA_NOT_PASSED"]


def test_attempted_queued_or_sent_is_not_delivery_proof():
    for status in ("ATTEMPTED", "QUEUED", "SENT", "ACCEPTED"):
        result = _proof(delivery_status=status)

        assert result["status"] == "FAIL"
        assert result["delivery_proof_valid"] is False
        assert result["report_delivered"] is False
        assert result["report_state"] == "BUILDING"
        assert result["next_action"] == "DELIVERY_PROOF_RECOVERY"
        assert "DELIVERY_NOT_ACKNOWLEDGED" in result["failures"]


def test_delivery_proof_requires_channel_target_receipt_id_and_timezone_aware_timestamp():
    cases = (
        ({"delivery_channel": ""}, "DELIVERY_CHANNEL_MISSING"),
        ({"delivery_target": ""}, "DELIVERY_TARGET_MISSING"),
        ({"provider_receipt_id": ""}, "PROVIDER_RECEIPT_ID_MISSING"),
        ({"delivered_at": "2026-09-16T04:30:08"}, "DELIVERED_AT_INVALID"),
    )

    for overrides, expected_failure in cases:
        result = _proof(**overrides)
        assert result["status"] == "FAIL"
        assert result["delivery_proof_valid"] is False
        assert expected_failure in result["failures"]


def test_delivery_acknowledgement_cannot_predate_the_report_logical_slot():
    result = _proof(delivered_at="2026-09-16T04:29:59+07:00")

    assert result["status"] == "FAIL"
    assert result["delivery_proof_valid"] is False
    assert result["report_delivered"] is False
    assert "DELIVERY_BEFORE_LOGICAL_SLOT" in result["failures"]


def test_same_receipt_is_idempotent_and_evidence_changes_change_proof_id():
    first = _proof()
    second = _proof()
    changed_target = _proof(delivery_target="ANOTHER_TARGET")
    changed_receipt = _proof(provider_receipt_id="receipt-0430-002")

    assert first["delivery_proof_id"] == second["delivery_proof_id"]
    assert first["delivery_proof_id"] != changed_target["delivery_proof_id"]
    assert first["delivery_proof_id"] != changed_receipt["delivery_proof_id"]


def test_validate_delivery_proof_rejects_any_tampering_and_wrong_report_slot():
    report_delivery = _delivery_module()
    proof = _proof()

    valid = report_delivery.validate_delivery_proof(
        proof=proof,
        post_render_qa=_post_render_pass(),
        expected_report_slot_id="2026-09-16T04:30+07:00|DEEP",
    )
    assert valid["status"] == "PASS"
    assert valid["delivery_proof_valid"] is True
    assert valid["report_delivered"] is True
    assert valid["report_state"] == "DELIVERED"

    tampered = dict(proof)
    tampered["delivery_target"] = "ANOTHER_TARGET"
    invalid = report_delivery.validate_delivery_proof(
        proof=tampered,
        post_render_qa=_post_render_pass(),
        expected_report_slot_id="2026-09-16T04:30+07:00|DEEP",
    )
    assert invalid["status"] == "FAIL"
    assert invalid["delivery_proof_valid"] is False
    assert invalid["report_delivered"] is False
    assert invalid["report_state"] == "BUILDING"
    assert "DELIVERY_PROOF_DIGEST_MISMATCH" in invalid["failures"]

    wrong_slot = report_delivery.validate_delivery_proof(
        proof=proof,
        post_render_qa=_post_render_pass(),
        expected_report_slot_id="2026-09-16T05:30+07:00|PRICE",
    )
    assert wrong_slot["status"] == "FAIL"
    assert wrong_slot["delivery_proof_valid"] is False
    assert "REPORT_SLOT_MISMATCH" in wrong_slot["failures"]


def test_wave2_slot_resolver_marks_duplicate_only_after_structured_wave7_proof_validates():
    report_delivery = _delivery_module()
    proof = _proof()
    validation = report_delivery.validate_delivery_proof(
        proof=proof,
        post_render_qa=_post_render_pass(),
        expected_report_slot_id="2026-09-16T04:30+07:00|DEEP",
    )

    decision = delivery_integrity.resolve_report_slot_decision(
        logical_slot="2026-09-16T04:30:00+07:00",
        report_type="DEEP",
        report_state=validation["report_state"],
        v6_already_published=True,
        delivered_report_slot_id=validation["delivered_report_slot_id"],
        delivery_proof_valid=validation["delivery_proof_valid"],
    )

    assert decision["report_delivered"] is True
    assert decision["report_required"] is False
    assert decision["duplicate"] is True
    assert decision["reason"] == "SAME_SLOT_ALREADY_DELIVERED"


def test_wave7_never_enables_legacy_fallback():
    proof = _proof()

    assert proof["legacy_fallback_allowed"] is False
