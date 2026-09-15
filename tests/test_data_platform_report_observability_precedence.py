from __future__ import annotations

from src.runtime_v6.report_observability import build_report_observability


SLOT = "2026-09-16T04:30+07:00|DEEP"


def test_delivery_blocked_by_post_render_qa_keeps_qa_as_root_status():
    result = build_report_observability(
        report_slot_id=SLOT,
        data_plane={"status": "GREEN"},
        retrieval={
            "v6_scope_id": "bootstrap",
            "v6_scope_state": "CURRENT",
            "retrieval_state": "COMPLETE",
            "action": "READ_V6_ONLY",
            "legacy_fallback_allowed": False,
        },
        compute={
            "status": "PASS",
            "compute_ready": True,
            "next_action": "PRE_RENDER_QA",
            "legacy_fallback_allowed": False,
        },
        pre_render_qa={
            "status": "PASS",
            "qa_stage": "PRE_RENDER",
            "qa_passed": True,
            "report_state": "BUILDING",
            "next_action": "RENDER_REPORT",
            "legacy_fallback_allowed": False,
        },
        post_render_qa={
            "status": "FAIL",
            "qa_stage": "POST_RENDER",
            "qa_passed": False,
            "report_state": "QA_FAILED",
            "next_action": "RENDER_RECOVERY",
            "legacy_fallback_allowed": False,
        },
        delivery={
            "status": "BLOCKED",
            "delivery_proof_valid": False,
            "report_delivered": False,
            "report_state": "QA_FAILED",
            "next_action": "POST_RENDER_QA",
            "legacy_fallback_allowed": False,
            "failures": ["POST_RENDER_QA_NOT_PASSED"],
        },
        recovery=None,
        stage_timestamps={},
    )

    assert result["report_plane"]["stages"]["delivery"]["status"] == "BLOCKED"
    assert result["report_plane"]["status"] == "QA_FAILED"
    assert result["report_plane"]["delivered"] is False
