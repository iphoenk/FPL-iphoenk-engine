from __future__ import annotations

import json
from datetime import datetime, timezone

from runtime_v6.domains.report_plane.report_delivery import build_delivery_proof
from runtime_v6.domains.report_plane.report_prefetch import PrefetchService


def _post_render_pass_but_contract_failed() -> dict[str, object]:
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
        # Golden incident: downstream delivery must never ignore this failure.
        "mandatory_scope_gate_pass": False,
        "input_completeness_pass": False,
        "pre_render_qa_pass": True,
        "post_render_qa_pass": True,
        "report_contract_pass": False,
        "trigger_kind": "AD_HOC",
        "mode": "DEEP",
        "rise20": "TRUNCATED",
        "fall20": "TRUNCATED",
        "icon_plus": "STALE_INCOMPLETE",
        "weather": "AVAILABLE",
        "personal": "STALE",
        "auth": "AUTH_EXPIRED",
    }


def test_e2e_r19_contract_false_can_never_reach_visible_delivery() -> None:
    proof = build_delivery_proof(
        post_render_qa=_post_render_pass_but_contract_failed(),
        report_slot_id="2026-09-18T04:30:00+07:00|ad_hoc_deep",
        delivery_status="ACKNOWLEDGED",
        delivery_channel="chatgpt",
        delivery_target="current_request",
        provider_receipt_id="e2e-r19-red-receipt",
        delivered_at="2026-09-18T04:31:00+07:00",
    )

    assert proof["status"] != "PASS"
    assert proof["report_delivered"] is False
    assert proof["report_state"] != "DELIVERED"


def test_e2e_r19_stored_fresh_flag_cannot_override_timestamp(tmp_path) -> None:
    service = PrefetchService(
        config={},
        output_root=tmp_path,
        now=datetime(2026, 9, 17, 21, 30, tzinfo=timezone.utc),  # 18 Sep 04:30 WIB
    )
    service._publish_health(
        {
            "generated_at": "2026-09-16T17:26:00+07:00",
            "logical_slot": "2026-09-16T17:26:00+07:00",
            "complete": True,
            "public_core_complete": True,
            "fresh_for_target_report": True,
            "personal_requested": True,
            "personal_status": "DEGRADED",
            "public_personal_status": "AVAILABLE",
            "auth_state": "AUTH_EXPIRED",
            "mini_league_status": "DEGRADED",
            "live_status": "NOT_REQUESTED",
            "source_failures": [],
            "telemetry": {},
            "idempotency": {"reused": False},
        }
    )

    health = json.loads((tmp_path / "health" / "report_prefetch.json").read_text())
    assert health["fresh_for_target_report"] is False
    assert health["prefetch_status"] == "STALE"
    assert health["public_core_status"] == "STALE"
