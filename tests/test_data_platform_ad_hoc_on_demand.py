from __future__ import annotations

import pytest

from src.runtime_v6.delivery_integrity import DeliveryIntegrityError, MANDATORY_SECTIONS, plan_exact_scope_retrieval
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_delivery import build_delivery_proof, validate_delivery_proof
from src.runtime_v6.report_observability import build_report_observability
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa
from src.runtime_v6.report_recovery_closeout import CLOSEOUT_EVIDENCE_KEYS
from src.runtime_v6.report_trigger import (
    build_ad_hoc_report_context,
    plan_ad_hoc_recovery,
    resolve_ad_hoc_report_decision,
)
from src.runtime_v6.workflow_control import resolve_data_slot_decision


REQUESTED_AT = "2026-09-16T08:41:23+07:00"
RECOVERY_DEADLINE = "2026-09-16T08:56:23+07:00"


def _our15():
    return [
        *({"id": player_id, "position": "GK"} for player_id in range(1, 3)),
        *({"id": player_id, "position": "DEF"} for player_id in range(3, 8)),
        *({"id": player_id, "position": "MID"} for player_id in range(8, 13)),
        *({"id": player_id, "position": "FWD"} for player_id in range(13, 16)),
    ]


def _watchlist20():
    rows = []
    player_id = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for _ in range(5):
            rows.append({"id": player_id, "position": position})
            player_id += 1
    return rows


def _compute():
    return build_report_compute_contract(
        scope_matrix_report_ready=True,
        our15_rows=_our15(),
        starting_xi_ids=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 7, 12, 15],
        watchlist_rows=_watchlist20(),
        rise_rows=[{"id": 201 + index} for index in range(20)],
        fall_rows=[{"id": 301 + index} for index in range(20)],
        facts={"official": {"source": "official_fpl"}},
        models={"projection": {"model": "v6"}},
    )


def _qa(report_mode: str = "DEEP"):
    compute = _compute()
    manifest = [
        {"section_id": section_id, "status": "COMPLETE"}
        for section_id in MANDATORY_SECTIONS
    ]
    weather_state = "PRICE_NOT_IN_SCOPE" if report_mode == "PRICE" else "DIRECT_CHATGPT"
    pre = validate_pre_render_qa(
        compute_contract=compute,
        section_manifest=manifest,
        mini_league_denominator_complete=True,
        report_mode=report_mode,
        weather_contract_state=weather_state,
    )
    post = validate_post_render_qa(
        pre_render_qa=pre,
        rendered_section_ids=pre["expected_section_ids"],
        rendered_section_states={row["section_id"]: row["status"] for row in pre["section_manifest"]},
        rendered_compute_fingerprint=compute["compute_fingerprint"],
        render_contract_token=pre["render_contract_token"],
        rendered_counts=pre["expected_counts"],
        rendered_fact_keys=pre["expected_fact_keys"],
        rendered_model_keys=pre["expected_model_keys"],
        rendered_mini_league_denominator_complete=True,
        rendered_weather_contract_state=weather_state,
        truncated=False,
    )
    return compute, pre, post


def test_ad_hoc_identity_is_stable_across_equivalent_timezones_and_retry():
    first = build_ad_hoc_report_context(
        request_id="req-abc-001",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
    )
    equivalent = build_ad_hoc_report_context(
        request_id="req-abc-001",
        requested_at="2026-09-16T01:41:23Z",
        report_type="deep",
    )

    assert first == equivalent
    assert first["trigger_kind"] == "AD_HOC"
    assert first["requested_at"] == "2026-09-16T08:41:23+07:00"
    assert first["logical_slot"] == "2026-09-16T08:41:00+07:00"
    assert first["report_slot_id"] == "2026-09-16T08:41+07:00|ADHOC:REQ-ABC-001:DEEP"
    assert first["scheduler_proof_required"] is False
    assert first["scheduler_proof_status"] == "N/A"
    assert first["missed_cycle_status"] == "N/A"


def test_ad_hoc_identity_is_unique_per_request_even_in_same_minute():
    first = build_ad_hoc_report_context(
        request_id="req-abc-001",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
    )
    second = build_ad_hoc_report_context(
        request_id="req-abc-002",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
    )

    assert first["report_slot_id"] != second["report_slot_id"]


@pytest.mark.parametrize("report_type", ["DEEP", "PRICE", "MATCH", "DEADLINE", "FINAL", "FULL", "POST_MATCH"])
def test_ad_hoc_trigger_is_report_mode_agnostic(report_type: str):
    context = build_ad_hoc_report_context(
        request_id=f"req-{report_type.lower()}",
        requested_at=REQUESTED_AT,
        report_type=report_type,
    )

    assert context["report_type"] == report_type
    assert context["trigger_kind"] == "AD_HOC"
    assert context["report_slot_id"].endswith(f":{report_type}")


def test_retry_and_valid_receipt_reuse_same_ad_hoc_identity():
    context = build_ad_hoc_report_context(
        request_id="req-retry-001",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
    )
    retry = resolve_ad_hoc_report_decision(
        request_id="req-retry-001",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
        report_state="QA_FAILED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
        v6_already_published=True,
    )
    delivered = resolve_ad_hoc_report_decision(
        request_id="req-retry-001",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
        report_state="DELIVERED",
        delivered_report_slot_id=context["report_slot_id"],
        delivery_proof_valid=True,
        v6_already_published=True,
    )

    assert retry["report_slot_id"] == context["report_slot_id"]
    assert retry["start_build"] is True
    assert retry["reason"] == "SAME_SLOT_RECOVERY"
    assert delivered["report_slot_id"] == context["report_slot_id"]
    assert delivered["report_delivered"] is True
    assert delivered["duplicate"] is True
    assert delivered["start_build"] is False


def test_ad_hoc_recovery_requires_explicit_window_and_expires_without_rekeying():
    context = build_ad_hoc_report_context(
        request_id="req-recovery-001",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
    )

    with pytest.raises(DeliveryIntegrityError):
        plan_ad_hoc_recovery(
            request_id="req-recovery-001",
            requested_at=REQUESTED_AT,
            report_type="DEEP",
            observed_at="2026-09-16T08:50:00+07:00",
            recovery_deadline=None,
            report_state="QA_FAILED",
            delivered_report_slot_id=None,
            delivery_proof_valid=False,
        )

    active = plan_ad_hoc_recovery(
        request_id="req-recovery-001",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
        observed_at="2026-09-16T08:50:00+07:00",
        recovery_deadline=RECOVERY_DEADLINE,
        report_state="QA_FAILED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )
    expired = plan_ad_hoc_recovery(
        request_id="req-recovery-001",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
        observed_at="2026-09-16T08:56:24+07:00",
        recovery_deadline=RECOVERY_DEADLINE,
        report_state="QA_FAILED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )

    assert active["report_slot_id"] == context["report_slot_id"]
    assert active["recovery_mode"] == "AD_HOC"
    assert active["start_build"] is True
    assert active["next_action"] == "AD_HOC_SAME_REQUEST_RECOVERY"
    assert expired["report_slot_id"] == context["report_slot_id"]
    assert expired["start_build"] is False
    assert expired["next_action"] == "AD_HOC_RECOVERY_EXPIRED"
    assert expired["v6_data_plane_mutation_allowed"] is False


def test_ad_hoc_e2e_reuses_v6_and_requires_receipt_without_scheduler_proof():
    context = build_ad_hoc_report_context(
        request_id="req-e2e-001",
        requested_at=REQUESTED_AT,
        report_type="DEEP",
    )
    data_slot = resolve_data_slot_decision(already_published=True)
    retrieval = plan_exact_scope_retrieval(
        v6_scope_id="bootstrap",
        v6_scope_state="CURRENT",
        retrieval_state="COMPLETE",
    )
    compute, pre, post = _qa("DEEP")
    proof = build_delivery_proof(
        post_render_qa=post,
        report_slot_id=context["report_slot_id"],
        delivery_status="ACKNOWLEDGED",
        delivery_channel="chat",
        delivery_target="fpl-master-user",
        provider_receipt_id="receipt-ad-hoc-e2e",
        delivered_at="2026-09-16T08:42:00+07:00",
    )
    delivery = validate_delivery_proof(
        proof=proof,
        post_render_qa=post,
        expected_report_slot_id=context["report_slot_id"],
    )
    observability = build_report_observability(
        report_slot_id=context["report_slot_id"],
        data_plane={"status": "GREEN"},
        retrieval=retrieval,
        compute=compute,
        pre_render_qa=pre,
        post_render_qa=post,
        delivery=delivery,
        recovery=None,
        trigger_context=context,
        stage_timestamps={
            "data_plane": "2026-09-16T08:41:24+07:00",
            "retrieval": "2026-09-16T08:41:25+07:00",
            "compute": "2026-09-16T08:41:30+07:00",
            "pre_render_qa": "2026-09-16T08:41:35+07:00",
            "post_render_qa": "2026-09-16T08:41:40+07:00",
            "delivery": "2026-09-16T08:42:00+07:00",
        },
    )

    assert data_slot["skip_new_acquisition"] is True
    assert data_slot["continue_report_pipeline"] is True
    assert retrieval["action"] == "READ_V6_ONLY"
    assert pre["status"] == "PASS"
    assert post["status"] == "PASS"
    assert delivery["status"] == "PASS"
    assert delivery["delivered_report_slot_id"] == context["report_slot_id"]
    assert observability["trigger"]["trigger_kind"] == "AD_HOC"
    assert observability["trigger"]["scheduler_proof_status"] == "N/A"
    assert observability["trigger"]["missed_cycle_status"] == "N/A"
    assert observability["report_plane"]["status"] == "DELIVERED"
    assert observability["legacy_fallback_allowed"] is False


def test_wave10_closeout_requires_ad_hoc_on_demand_e2e_evidence():
    assert "ad_hoc_on_demand_e2e_pass" in CLOSEOUT_EVIDENCE_KEYS
