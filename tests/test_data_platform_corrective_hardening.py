from __future__ import annotations

from copy import deepcopy

import pytest

from src.runtime_v6.delivery_integrity import (
    DeliveryIntegrityError,
    MANDATORY_SECTIONS,
    build_report_slot_id,
)
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa
from src.runtime_v6.report_recovery import plan_report_catch_up
from src.runtime_v6.report_recovery_closeout import (
    CLOSEOUT_EVIDENCE_KEYS,
    REGRESSION_SCENARIO_IDS,
    evaluate_production_closeout,
    evaluate_regression_acceptance,
)
from test_support.report_provenance import r5_partitions, r5_section_payloads
from test_support.report_rank20 import rank20_rows


def _our15():
    rows = []
    for player_id in range(1, 3):
        rows.append({"id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"id": player_id, "position": "FWD"})
    return rows


def _watchlist20():
    rows = []
    next_id = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for _ in range(5):
            rows.append({"id": next_id, "position": position})
            next_id += 1
    return rows


def _valid_compute():
    our15 = _our15()
    facts, models, inferences = r5_partitions(
        fact_key="price_fact",
        model_key="price_model",
        fact_source="OFFICIAL_FPL",
        model_name="V6_PRICE_MODEL",
    )
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


def _manifest():
    return [{"section_id": section_id, "status": "COMPLETE"} for section_id in MANDATORY_SECTIONS]


def _scenario_results():
    return {
        scenario_id: {"status": "PASS", "detail": scenario_id}
        for scenario_id in REGRESSION_SCENARIO_IDS
    }


def _e2e_evidence():
    return {key: True for key in CLOSEOUT_EVIDENCE_KEYS}


def test_report_slot_identity_normalizes_same_instant_to_asia_jakarta():
    wib = build_report_slot_id(
        logical_slot="2026-09-16T04:30:00+07:00",
        report_type="deep",
    )
    utc = build_report_slot_id(
        logical_slot="2026-09-15T21:30:00+00:00",
        report_type="DEEP",
    )

    assert wib == "2026-09-16T04:30+07:00|DEEP"
    assert utc == wib


def test_late_catch_up_without_explicit_deadline_fails_closed():
    with pytest.raises(DeliveryIntegrityError, match="explicit catch_up_deadline"):
        plan_report_catch_up(
            logical_slot="2026-09-16T04:30:00+07:00",
            report_type="DEEP",
            observed_at="2026-09-16T04:45:00+07:00",
            report_state="NOT_STARTED",
            delivered_report_slot_id=None,
            delivery_proof_valid=False,
            catch_up_deadline=None,
        )


def test_pre_render_fails_closed_when_mandatory_direct_weather_is_missing():
    outcome = validate_pre_render_qa(
        compute_contract=_valid_compute(),
        section_manifest=_manifest(),
        mini_league_denominator_complete=True,
        weather_required=True,
        weather_direct_chat_present=False,
    )

    assert outcome["status"] == "FAIL"
    assert outcome["render_allowed"] is False
    assert "MANDATORY_WEATHER_MISSING" in outcome["failures"]


def test_post_render_fails_closed_when_approved_weather_is_omitted():
    compute = _valid_compute()
    pre = validate_pre_render_qa(
        compute_contract=compute,
        section_manifest=_manifest(),
        mini_league_denominator_complete=True,
        weather_required=True,
        weather_direct_chat_present=True,
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
        rendered_weather_direct_chat_present=False,
        truncated=False,
    )

    assert pre["status"] == "PASS"
    assert post["status"] == "FAIL"
    assert "MANDATORY_WEATHER_MISSING" in post["failures"]


def test_weather_state_is_bound_into_pre_render_contract_token():
    compute = _valid_compute()
    pre = validate_pre_render_qa(
        compute_contract=compute,
        section_manifest=_manifest(),
        mini_league_denominator_complete=True,
        weather_required=True,
        weather_direct_chat_present=True,
    )
    tampered = deepcopy(pre)
    tampered["weather_direct_chat_present"] = False

    post = validate_post_render_qa(
        pre_render_qa=tampered,
        rendered_section_ids=pre["expected_section_ids"],
        rendered_section_states={row["section_id"]: row["status"] for row in pre["section_manifest"]},
        rendered_compute_fingerprint=compute["compute_fingerprint"],
        render_contract_token=pre["render_contract_token"],
        rendered_counts=pre["expected_counts"],
        rendered_fact_keys=pre["expected_fact_keys"],
        rendered_model_keys=pre["expected_model_keys"],
        rendered_mini_league_denominator_complete=True,
        rendered_weather_direct_chat_present=True,
        truncated=False,
    )

    assert post["status"] == "FAIL"
    assert "PRE_RENDER_CONTRACT_TOKEN_INVALID" in post["failures"]


def test_production_closeout_requires_bound_verification_provenance():
    regression = evaluate_regression_acceptance(_scenario_results())
    valid_provenance = {
        "commit_sha": "a" * 40,
        "acceptance_fingerprint": regression["acceptance_fingerprint"],
        "verified_at": "2026-09-16T08:00:00+07:00",
    }
    passed = evaluate_production_closeout(
        regression_acceptance=regression,
        e2e_evidence=_e2e_evidence(),
        provenance=valid_provenance,
    )
    missing = evaluate_production_closeout(
        regression_acceptance=regression,
        e2e_evidence=_e2e_evidence(),
        provenance={},
    )
    wrong_fingerprint = evaluate_production_closeout(
        regression_acceptance=regression,
        e2e_evidence=_e2e_evidence(),
        provenance={**valid_provenance, "acceptance_fingerprint": "b" * 64},
    )

    assert passed["status"] == "PASS"
    assert passed["provenance"] == valid_provenance
    assert missing["status"] == "FAIL"
    assert "PROVENANCE_COMMIT_SHA_INVALID" in missing["failures"]
    assert "PROVENANCE_ACCEPTANCE_FINGERPRINT_INVALID" in missing["failures"]
    assert "PROVENANCE_VERIFIED_AT_INVALID" in missing["failures"]
    assert wrong_fingerprint["status"] == "FAIL"
    assert "PROVENANCE_ACCEPTANCE_FINGERPRINT_MISMATCH" in wrong_fingerprint["failures"]