from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.delivery_integrity import build_report_slot_id
from src.runtime_v6.domains.report_plane.report_delivery import evaluate_same_slot_completion_ledger
from src.runtime_v6.domains.report_plane.section_contract import validate_p07_semantic_acceptance


SLOT = "2026-09-18T19:30:00+07:00"
REPORT_SLOT_ID = build_report_slot_id(logical_slot=SLOT, report_type="DEADLINE")


def _semantic_proof():
    return {
        "report_slot_id": REPORT_SLOT_ID,
        "logical_report_slot": SLOT,
        "watchlist20": {
            "status": "PASS",
            "full_universe_complete": True,
            "universe_count": 659,
            "evaluated_count": 659,
            "canonical_methodology_version": "FPL_MASTER_SPEC_V11:E/E0/E1/E2/F/G/H/T/T1/Z",
            "deterministic_ranking": True,
            "eligibility_checked": True,
            "owned_exclusion_checked": True,
            "provenance_valid": True,
            "observed_at": "2026-09-18T19:31:23+07:00",
        },
        "rise20": {
            "status": "PASS",
            "full_universe_complete": True,
            "universe_count": 659,
            "evaluated_count": 659,
            "deterministic_ranking": True,
            "transport_complete": True,
            "schema_complete": True,
            "provenance_valid": True,
            "observed_at": "2026-09-18T19:31:23+07:00",
        },
        "fall20": {
            "status": "PASS",
            "full_universe_complete": True,
            "universe_count": 659,
            "evaluated_count": 659,
            "deterministic_ranking": True,
            "transport_complete": True,
            "schema_complete": True,
            "provenance_valid": True,
            "observed_at": "2026-09-18T19:31:23+07:00",
        },
    }


def _section_checks():
    return {
        "WATCHLIST20": {"status": "PASS", "total": 20, "positions": {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}},
        "RISE20": {"status": "PASS", "total": 20, "row_schema_complete": True},
        "FALL20": {"status": "PASS", "total": 20, "row_schema_complete": True},
    }


def _ledger(**overrides):
    row = {
        "natural_occurrence_id": "natural-1930",
        "logical_data_slot": "2026-09-18T19:00:00+07:00",
        "logical_report_slot": SLOT,
        "governed_v6_run_id": "35344991540",
        "v6_terminal_state": "PUBLICATION_READY",
        "publication_readback_pass": True,
        "decision_context_hydrated": True,
        "decision_context_slot": SLOT,
        "report_prefetch_logical_slot": SLOT,
        "report_prefetch_identity_match": True,
        "report_prefetch_freshness": "CURRENT",
        "weather_attempted": True,
        "weather_status": "PASS",
        "pre_render_qa_pass": True,
        "canonical_render_completed": True,
        "canonical_render_hash": "a" * 64,
        "post_render_qa_pass": True,
        "report_contract_pass": True,
        "can_emit": True,
        "visible_emitted": True,
        "delivery_acknowledged": True,
        "delivery_proof_valid": True,
        "canonical_receipt_id": "b" * 64,
        "canonical_receipt_slot": SLOT,
        "report_slot_fulfilled": True,
    }
    row.update(overrides)
    return row


# T1-T10 same-slot completion behavior

def test_t1_terminal_v6_pass_continues_to_fulfilled_pass():
    result = evaluate_same_slot_completion_ledger(_ledger())
    assert result["status"] == "PASS"
    assert result["first_broken_or_unproven_edge"] is None


def test_t2_prefetch_amber_nonblocking_can_still_complete():
    result = evaluate_same_slot_completion_ledger(_ledger(report_prefetch_freshness="AMBER_NON_BLOCKING"))
    assert result["status"] == "PASS"


def test_t3_decision_context_slot_mismatch_fails():
    result = evaluate_same_slot_completion_ledger(_ledger(decision_context_slot="2026-09-18T18:30:00+07:00"))
    assert result["status"] == "FAIL"
    assert result["first_broken_or_unproven_edge"] == "ACTIVE_DECISION_CONTEXT_HYDRATION"


def test_t4_prefetch_exact_slot_mismatch_fails():
    result = evaluate_same_slot_completion_ledger(_ledger(report_prefetch_logical_slot="2026-09-18T18:30:00+07:00"))
    assert result["status"] == "FAIL"
    assert result["first_broken_or_unproven_edge"] == "EXACT_REPORT_PREFETCH_BINDING"


def test_t5_render_pass_without_delivery_ack_is_not_fulfilled():
    result = evaluate_same_slot_completion_ledger(_ledger(delivery_acknowledged=False, delivery_proof_valid=False, report_slot_fulfilled=False))
    assert result["status"] == "FAIL"
    assert result["first_broken_or_unproven_edge"] == "DELIVERY_ACKNOWLEDGED"


def test_t6_cross_slot_receipt_fails():
    result = evaluate_same_slot_completion_ledger(_ledger(canonical_receipt_slot="2026-09-18T18:30:00+07:00"))
    assert result["status"] == "FAIL"
    assert result["first_broken_or_unproven_edge"] == "IMMUTABLE_CANONICAL_RECEIPT"


def test_t7_visible_without_valid_delivery_proof_fails():
    result = evaluate_same_slot_completion_ledger(_ledger(delivery_proof_valid=False, canonical_receipt_id=None, report_slot_fulfilled=False))
    assert result["status"] == "FAIL"
    assert result["first_broken_or_unproven_edge"] == "DELIVERY_PROOF_VALID"


def test_t8_intermediate_status_cannot_be_terminal_success():
    result = evaluate_same_slot_completion_ledger(_ledger(v6_terminal_state="ACQUISITION_IN_PROGRESS", report_slot_fulfilled=False))
    assert result["status"] == "FAIL"
    assert result["terminal_status_only_allowed"] is False


def test_t9_complete_same_slot_chain_is_fulfilled():
    result = evaluate_same_slot_completion_ledger(_ledger())
    assert result["report_slot_fulfilled"] is True
    assert all(value == "EXECUTED_AND_PROVEN" for value in result["edge_classification"].values())


def test_t10_duplicate_continuation_reuses_same_occurrence_identity():
    result = evaluate_same_slot_completion_ledger(_ledger(), existing_ledger=evaluate_same_slot_completion_ledger(_ledger()))
    assert result["status"] == "PASS"
    assert result["idempotent_reuse"] is True


# T11-T13 immutable historical truth

def test_t11_historical_1730_cannot_be_rewritten():
    historical = _ledger(natural_occurrence_id="natural-1730", logical_report_slot="2026-09-18T17:30:00+07:00", historical_immutable=True, report_slot_fulfilled=False)
    result = evaluate_same_slot_completion_ledger(historical)
    assert result["status"] == "FAIL"
    assert result["historical_immutable"] is True


def test_t12_historical_1830_cannot_be_rewritten():
    historical = _ledger(natural_occurrence_id="natural-1830", logical_report_slot="2026-09-18T18:30:00+07:00", historical_immutable=True, report_slot_fulfilled=False)
    result = evaluate_same_slot_completion_ledger(historical)
    assert result["status"] == "FAIL"


def test_t13_historical_1930_semantic_escape_remains_failure():
    historical = _ledger(historical_immutable=True, report_slot_fulfilled=False, report_contract_pass=False)
    result = evaluate_same_slot_completion_ledger(historical)
    assert result["status"] == "FAIL"


# W1-W4 Watchlist semantic lineage

def test_w1_count20_without_full_universe_lineage_fails():
    proof = _semantic_proof()
    proof["watchlist20"]["full_universe_complete"] = False
    result = validate_p07_semantic_acceptance(section_checks=_section_checks(), semantic_proof=proof, expected_report_slot_id=REPORT_SLOT_ID)
    assert result["status"] == "FAIL"


def test_w2_partial_watchlist_candidate_set_fails():
    proof = _semantic_proof()
    proof["watchlist20"]["evaluated_count"] = 200
    result = validate_p07_semantic_acceptance(section_checks=_section_checks(), semantic_proof=proof, expected_report_slot_id=REPORT_SLOT_ID)
    assert result["checks"]["WATCHLIST20"]["status"] == "FAIL"


def test_w3_duplicate_or_owned_leakage_fails_through_structural_check():
    checks = _section_checks()
    checks["WATCHLIST20"] = {"status": "FAIL", "total": 20, "failures": ["OWNED_OVERLAP=1"]}
    result = validate_p07_semantic_acceptance(section_checks=checks, semantic_proof=_semantic_proof(), expected_report_slot_id=REPORT_SLOT_ID)
    assert result["status"] == "FAIL"


def test_w4_wrong_authority_position_composition_fails():
    checks = _section_checks()
    checks["WATCHLIST20"] = {"status": "FAIL", "total": 20, "positions": {"GK": 4, "DEF": 6, "MID": 5, "FWD": 5}}
    result = validate_p07_semantic_acceptance(section_checks=checks, semantic_proof=_semantic_proof(), expected_report_slot_id=REPORT_SLOT_ID)
    assert result["status"] == "FAIL"


# P1-P5 RISE/FALL semantic acceptance

def test_p1_rise_count_below20_fails():
    checks = _section_checks(); checks["RISE20"] = {"status": "FAIL", "total": 19}
    assert validate_p07_semantic_acceptance(section_checks=checks, semantic_proof=_semantic_proof(), expected_report_slot_id=REPORT_SLOT_ID)["status"] == "FAIL"


def test_p2_fall_count_below20_fails():
    checks = _section_checks(); checks["FALL20"] = {"status": "FAIL", "total": 19}
    assert validate_p07_semantic_acceptance(section_checks=checks, semantic_proof=_semantic_proof(), expected_report_slot_id=REPORT_SLOT_ID)["status"] == "FAIL"


def test_p3_narrative_cannot_substitute_structured_rows():
    checks = _section_checks()
    checks["RISE20"] = {"status": "FAIL", "total": 0, "failures": ["NARRATIVE_SUBSTITUTION"]}
    checks["FALL20"] = {"status": "FAIL", "total": 0, "failures": ["NARRATIVE_SUBSTITUTION"]}
    result = validate_p07_semantic_acceptance(section_checks=checks, semantic_proof=_semantic_proof(), expected_report_slot_id=REPORT_SLOT_ID)
    assert result["status"] == "FAIL"


def test_p4_schema_incomplete_rows_fail():
    checks = _section_checks(); checks["RISE20"] = {"status": "FAIL", "total": 20, "row_schema_complete": False}
    assert validate_p07_semantic_acceptance(section_checks=checks, semantic_proof=_semantic_proof(), expected_report_slot_id=REPORT_SLOT_ID)["status"] == "FAIL"


def test_p5_truncated_universe_without_completeness_proof_fails():
    proof = _semantic_proof(); proof["rise20"]["transport_complete"] = False
    result = validate_p07_semantic_acceptance(section_checks=_section_checks(), semantic_proof=proof, expected_report_slot_id=REPORT_SLOT_ID)
    assert result["checks"]["RISE20"]["status"] == "FAIL"


# A1 global invariant

def test_a1_any_mandatory_semantic_failure_blocks_contract_and_emit():
    proof = _semantic_proof(); proof["watchlist20"]["canonical_methodology_version"] = ""
    result = validate_p07_semantic_acceptance(section_checks=_section_checks(), semantic_proof=proof, expected_report_slot_id=REPORT_SLOT_ID)
    assert result["status"] == "FAIL"
    assert result["report_contract_pass"] is False
    assert result["can_emit"] is False


def test_exact_observed_1930_semantic_escape_is_golden_fail():
    checks = _section_checks()
    proof = _semantic_proof()
    proof["watchlist20"]["full_universe_complete"] = False
    proof["watchlist20"]["canonical_methodology_version"] = ""
    checks["RISE20"] = {"status": "FAIL", "total": 0, "failures": ["NARRATIVE_SUBSTITUTION"]}
    checks["FALL20"] = {"status": "FAIL", "total": 0, "failures": ["NARRATIVE_SUBSTITUTION"]}
    evidence = {
        "observed_visible_watchlist_count": 20,
        "observed_visible_watchlist_positions": {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5},
        "observed_price_risk_exact_excerpt": "saya tidak akan menyalin Rise20/Fall20",
        "historical_occurrence": "2026-09-18T19:30:00+07:00",
    }
    result = validate_p07_semantic_acceptance(section_checks=checks, semantic_proof=proof, expected_report_slot_id=REPORT_SLOT_ID)
    assert evidence["observed_price_risk_exact_excerpt"] in "saya tidak akan menyalin Rise20/Fall20 karena artifact tidak tersedia"
    assert result["status"] == "FAIL"
    assert result["report_contract_pass"] is False
    assert result["can_emit"] is False
