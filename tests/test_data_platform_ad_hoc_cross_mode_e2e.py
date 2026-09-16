from __future__ import annotations

import pytest

from src.runtime_v6.delivery_integrity import MANDATORY_SECTIONS
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_delivery import build_delivery_proof, validate_delivery_proof
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa
from src.runtime_v6.report_trigger import build_ad_hoc_report_context
from test_support.report_provenance import r5_partitions, r5_section_payloads
from test_support.report_rank20 import rank20_rows


REPORT_MODES = (
    "DEEP",
    "PRICE",
    "MATCH",
    "DEADLINE",
    "FINAL",
    "FULL",
    "OVERLAP",
    "POST_MATCH",
)


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
    our15 = _our15()
    facts, models, inferences = r5_partitions()
    return build_report_compute_contract(
        scope_matrix_report_ready=True,
        our15_rows=our15,
        starting_xi_ids=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 7, 12, 15],
        watchlist_rows=_watchlist20(),
        rise_rows=rank20_rows(201, "RISE"),
        fall_rows=rank20_rows(301, "FALL"),
        section_payloads=r5_section_payloads(our15),
        facts=facts,
        models=models,
        inferences=inferences,
    )


def _weather_state(qa_report_mode: str) -> str:
    if qa_report_mode == "PRICE":
        return "PRICE_NOT_IN_SCOPE"
    if qa_report_mode == "MATCH":
        return "MATCH_CURRENT"
    return "DIRECT_CHATGPT"


@pytest.mark.parametrize("report_mode", REPORT_MODES)
def test_ad_hoc_canonical_mode_runs_through_qa_and_same_slot_receipt(report_mode: str):
    context = build_ad_hoc_report_context(
        request_id=f"req-e2e-{report_mode.lower()}",
        requested_at="2026-09-16T08:41:23+07:00",
        report_type=report_mode,
    )
    compute = _compute()
    manifest = [
        {"section_id": section_id, "status": "COMPLETE"}
        for section_id in MANDATORY_SECTIONS
    ]
    qa_report_mode = context["qa_report_mode"]
    weather_state = _weather_state(qa_report_mode)
    pre = validate_pre_render_qa(
        compute_contract=compute,
        section_manifest=manifest,
        mini_league_denominator_complete=True,
        report_mode=qa_report_mode,
        weather_contract_state=weather_state,
    )

    assert pre["status"] == "PASS", pre["failures"]
    if report_mode == "POST_MATCH":
        assert context["qa_report_mode"] == "FULL"

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

    assert post["status"] == "PASS", post["failures"]

    proof = build_delivery_proof(
        post_render_qa=post,
        report_slot_id=context["report_slot_id"],
        delivery_status="ACKNOWLEDGED",
        delivery_channel="chat",
        delivery_target="fpl-master-user",
        provider_receipt_id=f"receipt-{report_mode.lower()}",
        delivered_at="2026-09-16T08:42:00+07:00",
    )
    delivery = validate_delivery_proof(
        proof=proof,
        post_render_qa=post,
        expected_report_slot_id=context["report_slot_id"],
    )

    assert delivery["status"] == "PASS"
    assert delivery["report_delivered"] is True
    assert delivery["delivered_report_slot_id"] == context["report_slot_id"]