from __future__ import annotations

from src.runtime_v6.delivery_integrity import (
    MANDATORY_SECTIONS,
    build_report_slot_id,
    plan_exact_scope_retrieval,
    resolve_report_slot_decision,
    validate_retrieval_reassembly,
)
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_contract import resolve_report_scope_matrix
from src.runtime_v6.report_delivery import build_delivery_proof, validate_delivery_proof
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa
from src.runtime_v6.workflow_control import resolve_data_slot_decision
from test_support.report_rank20 import rank20_rows


LOGICAL_SLOT = "2026-09-16T04:30:00+07:00"
REPORT_SLOT_ID = "2026-09-16T04:30+07:00|DEEP"


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


def _our15():
    rows = []
    for player_id in (1, 2):
        rows.append({"element_id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"element_id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"element_id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"element_id": player_id, "position": "FWD"})
    return rows


def _watchlist20():
    rows = []
    start = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for offset in range(5):
            rows.append({"element_id": start + offset, "position": position})
        start += 10
    return rows


def test_0430_already_published_v6_still_delivers_deep_report_exactly_once():
    data_slot = resolve_data_slot_decision(already_published=True)
    assert data_slot == {
        "data_slot_status": "ALREADY_PUBLISHED",
        "skip_new_acquisition": True,
        "reuse_last_valid_publication": True,
        "continue_report_pipeline": True,
    }

    assert build_report_slot_id(logical_slot=LOGICAL_SLOT, report_type="DEEP") == REPORT_SLOT_ID
    initial_report = resolve_report_slot_decision(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        report_state="NOT_STARTED",
        v6_already_published=True,
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )
    assert initial_report["report_required"] is True
    assert initial_report["report_delivered"] is False
    assert initial_report["duplicate"] is False
    assert initial_report["reason"] == "DUE_REPORT"

    retrieval = plan_exact_scope_retrieval(
        v6_scope_id="official_universe",
        v6_scope_state="CURRENT",
        retrieval_state="CONNECTOR_TRUNCATED",
    )
    assert retrieval["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert retrieval["scope_lock_required"] is True
    assert retrieval["direct_fresh_allowed"] is False
    assert retrieval["legacy_fallback_allowed"] is False
    assert retrieval["final_unavailable_allowed"] is False

    reassembled = validate_retrieval_reassembly(
        v6_scope_id="official_universe",
        expected_ids=[1, 2, 3, 4, 5, 6],
        retrieved_chunks=[[1, 2], [3, 4], [5, 6]],
    )
    assert reassembled["complete"] is True
    assert reassembled["action"] == "READ_REASSEMBLED_V6_SCOPE"
    assert reassembled["direct_fresh_allowed"] is False
    assert reassembled["legacy_fallback_allowed"] is False

    scope_matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(),
            "fixtures": _scope(),
            "price_predictor": _scope(),
            "icon_mini_league": _scope(),
            "private_ft_itb_sell_value": _scope(required=False, auth_required=True),
        },
        auth_status="EXPIRED",
    )
    assert scope_matrix["report_ready"] is True
    assert scope_matrix["blocking_scopes"] == []
    assert scope_matrix["degraded_scopes"] == ["private_ft_itb_sell_value"]
    assert scope_matrix["legacy_fallback_allowed"] is False

    compute = build_report_compute_contract(
        scope_matrix_report_ready=scope_matrix["report_ready"],
        our15_rows=_our15(),
        starting_xi_ids=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 7, 12, 15],
        watchlist_rows=_watchlist20(),
        rise_rows=rank20_rows(201, "RISE"),
        fall_rows=rank20_rows(301, "FALL"),
        facts={
            "official_price": {"source": "OFFICIAL_FPL", "value": 75},
            "ownership": {"source": "OFFICIAL_FPL", "value": 42.1},
        },
        models={
            "price_rise_probability": {"model": "PRICE_PREDICTOR", "value": 0.71},
            "expected_points": {"model": "BAYESIAN", "value": 6.8},
        },
    )
    assert compute["status"] == "PASS"
    assert compute["compute_ready"] is True
    assert compute["next_action"] == "PRE_RENDER_QA"
    assert compute["delivery_ready"] is False
    assert compute["legacy_fallback_allowed"] is False

    manifest = [
        {"section_id": section_id, "status": "COMPLETE"}
        for section_id in MANDATORY_SECTIONS
    ]
    pre = validate_pre_render_qa(
        compute_contract=compute,
        section_manifest=manifest,
        mini_league_denominator_complete=True,
        weather_required=True,
        weather_direct_chat_present=True,
    )
    assert pre["status"] == "PASS"
    assert pre["next_action"] == "RENDER_REPORT"
    assert pre["delivery_ready"] is False
    assert pre["weather_direct_chat_present"] is True

    post = validate_post_render_qa(
        pre_render_qa=pre,
        rendered_section_ids=list(pre["expected_section_ids"]),
        rendered_section_states={
            row["section_id"]: row["status"] for row in pre["section_manifest"]
        },
        rendered_compute_fingerprint=pre["compute_fingerprint"],
        render_contract_token=pre["render_contract_token"],
        rendered_counts=dict(pre["expected_counts"]),
        rendered_fact_keys=list(pre["expected_fact_keys"]),
        rendered_model_keys=list(pre["expected_model_keys"]),
        rendered_mini_league_denominator_complete=True,
        rendered_weather_direct_chat_present=True,
        truncated=False,
    )
    assert post["status"] == "PASS"
    assert post["next_action"] == "BUILD_DELIVERY_PROOF"
    assert post["delivery_ready"] is False
    assert post["weather_direct_chat_present"] is True
    assert post["legacy_fallback_allowed"] is False

    proof = build_delivery_proof(
        post_render_qa=post,
        report_slot_id=REPORT_SLOT_ID,
        delivery_status="ACKNOWLEDGED",
        delivery_channel="CHATGPT",
        delivery_target="USER_SESSION",
        provider_receipt_id="e2e-repro-0430-001",
        delivered_at="2026-09-16T04:30:08+07:00",
    )
    assert proof["status"] == "PASS"
    assert proof["delivery_proof_valid"] is True
    assert proof["report_delivered"] is True
    assert proof["report_state"] == "DELIVERED"
    assert proof["legacy_fallback_allowed"] is False

    validated = validate_delivery_proof(
        proof=proof,
        post_render_qa=post,
        expected_report_slot_id=REPORT_SLOT_ID,
    )
    assert validated["status"] == "PASS"
    assert validated["delivery_proof_valid"] is True
    assert validated["delivered_report_slot_id"] == REPORT_SLOT_ID

    rerun = resolve_report_slot_decision(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        report_state=validated["report_state"],
        v6_already_published=True,
        delivered_report_slot_id=validated["delivered_report_slot_id"],
        delivery_proof_valid=validated["delivery_proof_valid"],
    )
    assert rerun["report_required"] is False
    assert rerun["report_delivered"] is True
    assert rerun["duplicate"] is True
    assert rerun["reason"] == "SAME_SLOT_ALREADY_DELIVERED"