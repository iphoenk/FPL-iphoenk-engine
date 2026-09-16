from __future__ import annotations

from src.runtime_v6.report_observability import build_report_observability
from src.runtime_v6.report_trigger import build_ad_hoc_report_context, plan_ad_hoc_recovery


def test_ad_hoc_identity_includes_original_request_second():
    first = build_ad_hoc_report_context(
        request_id="req-same",
        requested_at="2026-09-16T08:41:23+07:00",
        report_type="DEEP",
    )
    second = build_ad_hoc_report_context(
        request_id="req-same",
        requested_at="2026-09-16T08:41:24+07:00",
        report_type="DEEP",
    )

    assert first["requested_at"] != second["requested_at"]
    assert first["report_slot_id"] != second["report_slot_id"]


def test_ad_hoc_request_id_is_canonical_case_insensitive_identity():
    lower = build_ad_hoc_report_context(
        request_id="req-case-001",
        requested_at="2026-09-16T08:41:23+07:00",
        report_type="DEEP",
    )
    upper = build_ad_hoc_report_context(
        request_id="REQ-CASE-001",
        requested_at="2026-09-16T08:41:23+07:00",
        report_type="deep",
    )

    assert lower == upper
    assert lower["request_id"] == "REQ-CASE-001"


def test_ad_hoc_expired_recovery_is_explicit_in_observability():
    context = build_ad_hoc_report_context(
        request_id="req-expired-001",
        requested_at="2026-09-16T08:41:23+07:00",
        report_type="DEEP",
    )
    recovery = plan_ad_hoc_recovery(
        request_id="req-expired-001",
        requested_at="2026-09-16T08:41:23+07:00",
        report_type="DEEP",
        observed_at="2026-09-16T08:56:24+07:00",
        recovery_deadline="2026-09-16T08:56:23+07:00",
        report_state="QA_FAILED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )
    view = build_report_observability(
        report_slot_id=context["report_slot_id"],
        data_plane={"status": "GREEN"},
        retrieval=None,
        compute=None,
        pre_render_qa=None,
        post_render_qa=None,
        delivery=None,
        recovery=recovery,
        trigger_context=context,
        stage_timestamps={"recovery": "2026-09-16T08:56:24+07:00"},
    )

    assert recovery["next_action"] == "AD_HOC_RECOVERY_EXPIRED"
    assert view["report_plane"]["stages"]["recovery"]["status"] == "EXPIRED"
    assert view["report_plane"]["status"] == "RECOVERY_EXPIRED"
