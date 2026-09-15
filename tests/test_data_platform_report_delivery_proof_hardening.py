from __future__ import annotations

from src.runtime_v6 import report_delivery


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


def test_delivery_proof_rejects_noncanonical_report_slot_identity():
    result = report_delivery.build_delivery_proof(
        post_render_qa=_post_render_pass(),
        report_slot_id="2026-09-16T04:30:00+07:00|deep",
        delivery_status="ACKNOWLEDGED",
        delivery_channel="CHATGPT",
        delivery_target="USER_SESSION",
        provider_receipt_id="receipt-0430-001",
        delivered_at="2026-09-16T04:30:08+07:00",
    )

    assert result["status"] == "FAIL"
    assert result["delivery_proof_valid"] is False
    assert result["report_delivered"] is False
    assert result["report_state"] == "BUILDING"
    assert "REPORT_SLOT_ID_NONCANONICAL" in result["failures"]
