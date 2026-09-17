from __future__ import annotations

from src.runtime_v6.report_delivery import build_delivery_proof, is_post_render_delivery_ready
from src.runtime_v6.report_qa import validate_post_render_qa


def _post_render_contract(*, trigger_kind: str = "SCHEDULED", contract_pass: bool = True):
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
        "mandatory_scope_gate_pass": contract_pass,
        "input_completeness_pass": contract_pass,
        "pre_render_qa_pass": True,
        "post_render_qa_pass": True,
        "report_contract_pass": contract_pass,
        "can_emit": contract_pass,
        "visible_emitted": False,
        "trigger_kind": trigger_kind,
        "mode": "DEEP",
    }


def _delivery(post_render_qa):
    return build_delivery_proof(
        post_render_qa=post_render_qa,
        report_slot_id="2026-09-18T04:30+07:00|DEEP",
        delivery_status="ACKNOWLEDGED",
        delivery_channel="CHATGPT",
        delivery_target="USER_SESSION",
        provider_receipt_id="ir2-receipt",
        delivered_at="2026-09-18T04:30:08+07:00",
    )


def test_contract_false_can_never_emit():
    failed = _post_render_contract(contract_pass=False)
    assert is_post_render_delivery_ready(failed) is False
    proof = _delivery(failed)
    assert proof["status"] == "BLOCKED"
    assert proof["report_delivered"] is False
    assert proof.get("visible_emitted") is False


def test_ad_hoc_uses_same_contract_gate_as_scheduled():
    for trigger_kind in ("SCHEDULED", "AD_HOC"):
        assert is_post_render_delivery_ready(
            _post_render_contract(trigger_kind=trigger_kind, contract_pass=True)
        ) is True
        assert is_post_render_delivery_ready(
            _post_render_contract(trigger_kind=trigger_kind, contract_pass=False)
        ) is False


def test_ad_hoc_cannot_emit_failed_deep_report():
    failed = _post_render_contract(trigger_kind="AD_HOC", contract_pass=False)
    proof = _delivery(failed)
    assert proof["status"] == "BLOCKED"
    assert proof["report_state"] == "QA_FAILED"
    assert proof["report_delivered"] is False
    assert proof.get("visible_emitted") is False


def test_post_render_failure_discards_body():
    blocked = validate_post_render_qa(
        pre_render_qa={
            "status": "FAIL",
            "qa_stage": "PRE_RENDER",
            "qa_passed": False,
            "render_allowed": False,
            "delivery_ready": False,
        },
        rendered_body="THIS BODY MUST NEVER ESCAPE",
        rendered_section_ids=[],
        rendered_section_states={},
        rendered_compute_fingerprint=None,
        render_contract_token=None,
        rendered_counts={},
        rendered_fact_keys=[],
        rendered_model_keys=[],
        rendered_mini_league_denominator_complete=False,
        truncated=False,
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["qa_passed"] is False
    assert blocked["visible_body_validated"] is False
    assert "rendered_body" not in blocked


def test_visible_emit_requires_contract_pass():
    proof = _delivery(_post_render_contract(contract_pass=True))
    assert proof["status"] == "PASS"
    assert proof["report_contract_pass"] is True
    assert proof["can_emit"] is True
    assert proof["visible_emitted"] is True
