from __future__ import annotations

from pathlib import Path

import pytest

from src.engines.canonical_decision_methodology import (
    CANONICAL_AUTHORITY,
    CANONICAL_WEIGHTS,
    MethodologyContractError,
    build_decision_proof,
    build_horizon_analysis,
    build_probability_state,
    build_transfer_economics,
    compute_football_score,
    derive_dynamic_ft_shadow_value,
    validate_methodology_weights,
    validate_monte_carlo_provenance,
)
from src.engines.p1_decision_governance import (
    choose_close_call_lineup,
    state_conditional_slot_utility,
)
from src.models.package_optimizer_v2 import simulate_objective
from src.models.xmins_v3 import estimate_xmins
from src.runtime_v6.domains.report_plane.report_qa import (
    _expected_visible_counts,
    validate_v12_decision_semantics,
)
from src.engines.production_contract_validate import (
    _validate_xmins_probability_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _components() -> dict[str, float]:
    return {
        "PROVEN_HISTORICAL": 70.0,
        "TACTICAL_ROLE": 72.0,
        "CURRENT_UNDERLYING": 75.0,
        "FIXTURE_SECURITY": 68.0,
    }


def _probability_state() -> dict:
    return build_probability_state(
        p_available=0.90,
        p_start_given_available=0.70,
        p_bench_given_available_not_start=0.80,
        p_cameo_given_bench=0.75,
        p_late_cameo_given_cameo=0.40,
    )


def _xmins_distribution() -> dict:
    state = _probability_state()["unconditional"]
    regular_cameo = state["p_cameo"] - state["p_late_cameo"]
    return {
        "distribution": "FINITE_STATE_MINUTES_MIXTURE",
        "mean": 49.0,
        "std": 24.0,
        "states": [
            {"state": "START", "probability": state["p_start"], "minutes_mean": 72.0, "minutes_std": 10.0},
            {"state": "CAMEO", "probability": regular_cameo, "minutes_mean": 18.0, "minutes_std": 7.0},
            {"state": "LATE_CAMEO", "probability": state["p_late_cameo"], "minutes_mean": 8.0, "minutes_std": 4.0},
            {"state": "ZERO_MINUTES", "probability": state["p_dnp"], "minutes_mean": 0.0, "minutes_std": 0.0},
        ],
    }


def _horizons(*, rental: bool = False) -> dict:
    kwargs = {
        "one_gw": {"expected_points_delta": 1.3},
        "three_gw": {"expected_points_delta": 2.0},
        "five_gw": {"expected_points_delta": 3.1},
        "rental_or_exit": rental,
    }
    if rental:
        kwargs["two_gw"] = {"expected_points_delta": 1.7}
    return build_horizon_analysis(**kwargs)


def _dynamic_economics() -> dict:
    ft_shadow = derive_dynamic_ft_shadow_value(
        best_future_utility_with_ft=12.4,
        best_future_utility_with_ft_consumed=10.9,
        frontier_snapshot_id="frontier-synthetic-1",
    )
    return build_transfer_economics(
        ft_used=1,
        hit_points=0,
        ft_shadow=ft_shadow,
        buy_back_cost=0,
        sell_value_loss=0,
        price_movement_effect=0,
        affordability_after=True,
        itb_after=0.5,
        concentration_risk="LOW",
        correlation_risk="LOW",
        exit_route={},
        reacquisition_plan={"allowed": True},
        possible_future_ft=1,
        possible_future_hit=0,
        exit_security="PUNT EXIT SECURE",
    )


def _not_run_mc() -> dict:
    return {"execution_state": "NOT_RUN", "reason": "synthetic inputs intentionally do not support calibrated correlated event paths"}


def _valid_proof(**overrides) -> dict:
    payload = dict(
        authority_path=CANONICAL_AUTHORITY,
        authority_sha="a" * 64,
        authority_version="V12",
        official_universe_denominator=657,
        evaluated_denominator=657,
        gate0={"status": "PASS"},
        component_scores=_components(),
        weights=CANONICAL_WEIGHTS,
        bayesian_lineage={"prior": "historical", "posterior": "current", "shrinkage": True},
        probability_state=_probability_state(),
        xmins_distribution=_xmins_distribution(),
        horizons=_horizons(),
        transfer_economics=_dynamic_economics(),
        robustness={
            "expected_regret": 0.4,
            "conditional_floor": 2.0,
            "upper_tail": 9.0,
            "p_outperform": 0.53,
            "lineup_optionality": 1.2,
        },
        expected_regret=0.4,
        information_value_of_waiting=0.3,
        covariance={"material": False},
        icon_overlay={"applied_after_football_optimal_baseline": True},
        monte_carlo=_not_run_mc(),
        final_action="WAIT",
        search_authority="FULL",
        search_proof={
            "owned_expected": 15,
            "owned_evaluated": 15,
            "eligible_universe_expected": 657,
            "eligible_universe_evaluated": 657,
            "outgoing_candidate_count": 15,
            "outgoing_combination_count": 120,
            "legal_route_count": 1,
            "hold_included": True,
            "lossy_pruning": False,
            "search_authority": "FULL",
        },
        execution_provenance={
            "runtime": "CHATGPT_AUTOMATION",
            "repository_python_executed": False,
            "repository_contract_only": True,
        },
    )
    payload.update(overrides)
    return build_decision_proof(**payload)


def test_A_v12_rejects_active_library_v11_authority():
    assert validate_methodology_weights(CANONICAL_WEIGHTS, authority=CANONICAL_AUTHORITY) == CANONICAL_WEIGHTS
    for legacy in (
        "/FPL/FPL_MASTER_SPEC_V11.txt",
        "/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt",
        "/FPL/state/ACTIVE_DECISION_CONTEXT.json",
    ):
        with pytest.raises(MethodologyContractError):
            validate_methodology_weights(CANONICAL_WEIGHTS, authority=legacy)


def test_B_exact_20_25_30_25_methodology_ownership():
    score = compute_football_score(_components())
    assert score["weights"] == CANONICAL_WEIGHTS
    drifted = dict(CANONICAL_WEIGHTS, PROVEN_HISTORICAL=0.21, CURRENT_UNDERLYING=0.29)
    with pytest.raises(MethodologyContractError):
        validate_methodology_weights(drifted, authority=CANONICAL_AUTHORITY)


def test_C_probability_hierarchy_does_not_flatten_overlapping_bench_state():
    state = _probability_state()
    u = state["unconditional"]
    assert abs(u["p_start"] + u["p_cameo"] + u["p_dnp"] - 1.0) < 1e-8
    assert state["bench_is_overlapping_state"] is True
    assert u["p_bench"] >= u["p_cameo"]
    assert u["p_start"] + u["p_bench"] + u["p_cameo"] + u["p_dnp"] > 1.0


def test_D_xmins_is_derived_from_state_mixture_and_publishes_distribution():
    player = {
        "status": "a",
        "starts": 3,
        "minutes": 230,
        "chance_of_playing_next_round": 100,
    }
    out = estimate_xmins(
        player,
        {
            "team_matches_played": 4,
            "prior_start_probability": 0.75,
            "starter_minutes_prior": 76,
            "prior_evidence_minutes": 900,
        },
    )
    dist = out["xmins_distribution"]
    assert dist["distribution"] == "FINITE_STATE_MINUTES_MIXTURE"
    assert {"START", "CAMEO", "LATE_CAMEO", "ZERO_MINUTES"} <= {row["state"] for row in dist["states"]}
    derived = sum(row["probability"] * row["minutes_mean"] for row in dist["states"])
    assert abs(derived - out["expected_minutes"]) < 0.3
    assert out["governance"]["xmins_derived_from_start_cameo_zero_mixture"] is True


def test_E_cameo_is_not_dnp_and_blocks_auto_sub():
    starter = {
        "xpts_mean": 5.0,
        "expected_minutes": 50.0,
        "start_probability": 0.60,
        "cameo_probability": 0.25,
        "late_cameo_probability": 0.10,
        "dnp_probability": 0.15,
        "xmins_distribution": _xmins_distribution(),
    }
    utility = state_conditional_slot_utility(starter, legal_auto_sub_value=4.0)
    assert utility["cameo_auto_sub_blocking_cost"] == 1.0
    assert utility["dnp_auto_sub_utility"] == 0.6
    assert utility["governance"]["cameo_is_not_dnp"] is True


def test_F_late_cameo_is_captured_as_subset_of_cameo():
    state = _probability_state()["unconditional"]
    assert 0 < state["p_late_cameo"] < state["p_cameo"]


def test_G_auto_sub_preservation_and_cameo_blocking_are_both_exposed():
    starter = {
        "xpts_mean": 4.0,
        "expected_minutes": 45.0,
        "start_probability": 0.50,
        "cameo_probability": 0.30,
        "late_cameo_probability": 0.10,
        "dnp_probability": 0.20,
        "xmins_distribution": _xmins_distribution(),
    }
    utility = state_conditional_slot_utility(starter, legal_auto_sub_value=5.0)
    assert utility["auto_sub_preservation_value"] == 1.0
    assert utility["cameo_auto_sub_blocking_cost"] == 1.5


def test_H_uncertain_starter_tiny_mean_edge_can_lose_to_robust_generic_B():
    policy = {"selection": {"close_call_rerank_gap": 0.75}}
    a = {
        "id": "A",
        "base_score": 6.10,
        "decision_score": 6.10,
        "xpts_mean": 6.10,
        "xpts_std": 3.0,
        "v12_expected_utility": 5.20,
        "conditional_floor": 1.0,
        "expected_regret": 1.4,
    }
    b = {
        "id": "B",
        "base_score": 6.00,
        "decision_score": 6.00,
        "xpts_mean": 6.00,
        "xpts_std": 1.2,
        "v12_expected_utility": 5.75,
        "conditional_floor": 3.0,
        "expected_regret": 0.5,
    }
    ranked = choose_close_call_lineup([a, b], policy)
    assert ranked[0]["id"] == "B"
    assert ranked[0]["legacy_close_gap_is_decision_authority"] is False


def test_I_v12_horizons_are_gw1_3_5_and_2_when_required():
    normal = _horizons()
    rental = _horizons(rental=True)
    assert list(normal["horizons"]) == ["GW+1", "3GW", "5GW"]
    assert list(rental["horizons"]) == ["GW+1", "2GW", "3GW", "5GW"]
    with pytest.raises(MethodologyContractError):
        build_horizon_analysis(
            one_gw={"expected_points_delta": 1},
            three_gw={"expected_points_delta": 2},
            five_gw={"expected_points_delta": 3},
            rental_or_exit=True,
        )


def test_J_one_gw_rental_exit_is_provisional_and_reoptimized():
    proof = _valid_proof(
        route_type="ONE_GW_PUNT",
        horizons=_horizons(rental=True),
        owned_out_scan={
            "evaluated_owned_element_ids": list(range(1, 16)),
            "selected_outgoing_element_ids": [],
            "user_named_outgoing_element_ids": [],
            "selection_is_result_not_precondition": True,
            "user_named_out_is_hypothesis_only": True,
        },
    )
    assert proof["route_type"] == "ONE_GW_PUNT"
    assert "2GW" in proof["horizons"]["horizons"]
    assert proof["transfer_economics"]["exit_route_is_provisional"] is True


def test_K_ft_shadow_is_dynamic_future_opportunity_not_020_heuristic():
    shadow = derive_dynamic_ft_shadow_value(
        best_future_utility_with_ft=14.0,
        best_future_utility_with_ft_consumed=11.25,
        frontier_snapshot_id="future-frontier",
    )
    assert shadow["ft_shadow_value"] == 2.75
    assert shadow["fixed_universal_ft_value"] is False
    legacy = build_transfer_economics(
        ft_used=1,
        hit_points=0,
        future_ft_shadow_value=0.20,
        buy_back_cost=0,
        sell_value_loss=0,
        price_movement_effect=0,
        affordability_after=True,
        itb_after=0,
        concentration_risk="LOW",
        correlation_risk="LOW",
        exit_route={},
        reacquisition_plan={},
    )
    assert legacy["ft_shadow_semantics"] == "LEGACY_HEURISTIC_NOT_CANONICAL"


def test_L_300_path_independent_mc_can_never_claim_v12_canonical_pass():
    legacy = simulate_objective(10.0, 2.0, 300, 7)
    assert legacy["actual_paths"] == 300
    assert legacy["correlated"] is False
    assert legacy["canonical_v12_pass"] is False
    guard = validate_monte_carlo_provenance(
        {
            "execution_state": "EXECUTED",
            "actual_paths": 300,
            "correlated": False,
            "method": "independent_normal_aggregate_baseline",
        }
    )
    assert guard["status"] == "FAIL"
    assert guard["canonical_pass"] is False


def test_M_correlated_mc_execution_requires_actual_n_at_least_500k_and_metadata():
    bad = validate_monte_carlo_provenance(
        {
            "execution_state": "EXECUTED",
            "actual_paths": 499999,
            "correlated": True,
            "method": "correlated_path_simulation",
            "correlation_model": "shared_match_factor",
            "seed_policy": "deterministic",
            "input_snapshot_ids": ["snap"],
            "input_freshness": "fresh",
            "convergence_evidence": {"stable": True},
            "output_fingerprint": "b" * 64,
        }
    )
    assert bad["status"] == "FAIL"
    good = validate_monte_carlo_provenance(
        {
            "execution_state": "EXECUTED",
            "actual_paths": 500000,
            "correlated": True,
            "method": "correlated_state_event_paths",
            "correlation_model": "shared_team_match_factors",
            "seed_policy": "paired_common_random_numbers",
            "common_random_numbers": True,
            "input_snapshot_ids": ["snap-a", "snap-b"],
            "input_freshness": "fresh",
            "convergence_evidence": {"batch_mean_delta_stable": True},
            "output_fingerprint": "c" * 64,
            "paired_outputs": {"p_route_beats_hold": 0.53},
        }
    )
    assert good["status"] == "PASS"
    assert good["actual_paths"] == 500000


def test_N_mc_not_run_or_partial_is_truthful_and_report_can_continue():
    not_run = validate_monte_carlo_provenance(_not_run_mc())
    partial = validate_monte_carlo_provenance(
        {"execution_state": "PARTIAL", "degradation_reason": "one input distribution lacks calibrated event tails"}
    )
    assert not_run["report_can_continue"] is True
    assert partial["report_can_continue"] is True


def test_O_partial_search_cannot_claim_full_universe_optimized():
    with pytest.raises(MethodologyContractError):
        _valid_proof(
            search_authority="PARTIAL",
            optimization_claim="FULL_UNIVERSE_OPTIMIZED",
        )


def test_P_semantic_report_qa_catches_missing_probability_horizon_and_robustness():
    proof = _valid_proof()
    proof.pop("probability_state")
    proof.pop("horizons")
    proof.pop("robustness")
    qa = validate_v12_decision_semantics(proof, serious_decision_required=True)
    assert qa["status"] == "PARTIAL"
    assert qa["canonical_v12_compliant"] is False
    assert qa["report_can_continue"] is True
    assert any("PROBABILITY" in failure for failure in qa["failures"])
    assert any("HORIZON" in failure for failure in qa["failures"])
    assert any("ROBUSTNESS" in failure for failure in qa["failures"])


def test_Q_structural_exact_watchlist_rise_fall_targets_remain_green():
    counts = _expected_visible_counts("DEEP")
    assert counts["WATCHLIST20"] == 20
    assert counts["RISE20"] == 20
    assert counts["FALL20"] == 20
    assert counts["OUR15"] == 15
    assert counts["XI"] == 11
    assert counts["BENCH"] == 4


def test_R_degraded_optional_decision_scope_does_not_suppress_due_report():
    qa = validate_v12_decision_semantics(None, serious_decision_required=True)
    assert qa["status"] == "PARTIAL"
    assert qa["report_can_continue"] is True
    assert "V12_DECISION_PROOF_MISSING" in qa["failures"]


def test_S_no_v3_v4_v5_factual_fallback_in_active_v12_authority():
    canonical = (ROOT / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt").read_text(encoding="utf-8")
    assert "V6 ONLY" in canonical
    assert "NEVER V3/V4/V5" in canonical
    assert "V3/V4/V5 factual fallback" not in canonical


def test_T_runtime_truth_preserves_one_scheduler_no_duplicate_acquisition_and_same_slot_contract():
    canonical = (ROOT / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt").read_text(encoding="utf-8")
    assert "Exactly one recurring FPL Master scheduler may be active." in canonical
    assert "never duplicate acquisition" in canonical
    assert "Preserve original scheduler-supplied Asia/Jakarta HH:30 slot" in canonical


def test_decision_proof_full_semantics_pass_without_fake_execution_claims():
    proof = _valid_proof()
    qa = validate_v12_decision_semantics(proof, serious_decision_required=True)
    assert proof["canonical_v12_compliant"] is True
    assert qa["status"] == "PASS"
    assert qa["canonical_v12_compliant"] is True


def test_repository_python_execution_claim_requires_actual_evidence():
    proof = _valid_proof()
    proof["execution_provenance"] = {
        "runtime": "CHATGPT_AUTOMATION",
        "repository_python_executed": True,
    }
    qa = validate_v12_decision_semantics(proof, serious_decision_required=True)
    assert "V12_PYTHON_EXECUTION_CLAIM_UNPROVEN" in qa["failures"]


def test_production_contract_accepts_v12_hierarchical_probability_partition():
    xm = {
        "probability_semantics": "V12_HIERARCHICAL",
        "start_probability": 0.60,
        "bench_probability": 0.28,
        "cameo_probability": 0.20,
        "late_cameo_probability": 0.08,
        "dnp_probability": 0.20,
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "states": [
                {"state": "START"},
                {"state": "CAMEO"},
                {"state": "LATE_CAMEO"},
                {"state": "ZERO_MINUTES"},
            ],
        },
    }
    result = _validate_xmins_probability_contract(xm)
    assert result["semantics"] == "V12_HIERARCHICAL"
    assert result["appearance_partition"] == "START+CAMEO+DNP"
    assert result["bench_overlapping"] is True
