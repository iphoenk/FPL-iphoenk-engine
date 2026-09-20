from __future__ import annotations

import json
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
    validate_owned_out_scan,
    validate_pairwise_battles,
    validate_search_proof,
)
from src.engines.v12_package_search import search_packages
from src.engines.v12_tactical_role import (
    CANONICAL_WEIGHT,
    TACTICAL_EVIDENCE_CLASSES,
    TacticalRoleContractError,
    classify_tactical_evidence,
)
from src.platform.legacy_execution_isolation_validate import validate as validate_legacy_isolation


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"
STATE = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_STATE_V12.json"
WORKFLOW = ROOT / ".github" / "workflows" / "repository-governance.yml"


def _full_search_proof(**overrides):
    proof = {
        "owned_expected": 15,
        "owned_evaluated": 15,
        "eligible_universe_expected": 647,
        "eligible_universe_evaluated": 647,
        "outgoing_candidate_count": 15,
        "outgoing_combination_count": 120,
        "legal_route_count": 1,
        "hold_included": True,
        "lossy_pruning": False,
        "search_authority": "FULL",
    }
    proof.update(overrides)
    return proof


def _owned_out_scan(**overrides):
    scan = {
        "evaluated_owned_element_ids": list(range(1, 16)),
        "selected_outgoing_element_ids": [],
        "user_named_outgoing_element_ids": [],
        "selection_is_result_not_precondition": True,
        "user_named_out_is_hypothesis_only": True,
    }
    scan.update(overrides)
    return scan


def _pairwise_battle(**overrides):
    battle = {
        "owned_element_id": 1,
        "challenger_element_id": 101,
        "football_score_delta": 3.2,
        "component_comparison": {
            "PROVEN_HISTORICAL": {"owned": 65.0, "challenger": 68.0},
            "TACTICAL_ROLE": {"owned": 70.0, "challenger": 74.0},
            "CURRENT_UNDERLYING": {"owned": 66.0, "challenger": 75.0},
            "FIXTURE_SECURITY": {"owned": 72.0, "challenger": 73.0},
        },
        "p_available_comparison": {"owned": 0.98, "challenger": 0.99},
        "p_start_comparison": {"owned": 0.82, "challenger": 0.91},
        "xmins_comparison": {"owned_mean": 71.0, "challenger_mean": 79.0},
        "p_return_comparison": {"owned": 0.31, "challenger": 0.39},
        "p_blank_comparison": {"owned": 0.44, "challenger": 0.37},
        "material_tail_comparison": {"p_10_plus_owned": 0.12, "p_10_plus_challenger": 0.18},
        "expected_points_comparison": {"owned": 4.9, "challenger": 5.8},
        "tactical_role_comparison": {"owned": "wide-8", "challenger": "advanced-8"},
        "tactical_evidence_class": {
            "owned": "OBSERVED_ROLE",
            "challenger": "INFERRED_ROLE",
        },
        "set_piece_penalty_comparison": {"owned": "secondary", "challenger": "primary-corners"},
        "gw_plus_1": {"delta": 0.9},
        "three_gw": {"delta": 1.8},
        "five_gw": {"delta": 2.4},
        "price_economic_delta": {"net_budget_delta": -0.2},
        "robustness_delta": {"expected_regret_delta": -0.3},
        "expected_regret": {"owned": 0.8, "challenger": 0.5},
        "information_value_of_waiting": 0.2,
        "mini_league_leverage": {"applied_after_football_baseline": True, "delta": 0.03},
        "operational_action": "WAIT",
        "reversal_trigger": "confirmed lineup materially changes P(start)",
        "diagnostic_evidence_only": True,
        "decision_authority": False,
        "ranking_authority": False,
        "material_deltas": {"football_score": 3.2, "gw_plus_1_xpts": 0.9},
        "decision_delta_or_fingerprint": "pairwise-synthetic-v1",
        "unavailable_reasons": {},
    }
    battle.update(overrides)
    return battle


def _decision_kwargs(**overrides):
    probability = build_probability_state(
        p_available=0.95,
        p_start_given_available=0.80,
        p_bench_given_available_not_start=0.75,
        p_cameo_given_bench=0.70,
        p_late_cameo_given_cameo=0.30,
    )
    ft_shadow = derive_dynamic_ft_shadow_value(
        best_future_utility_with_ft=12.0,
        best_future_utility_with_ft_consumed=10.8,
        frontier_snapshot_id="scope-test-frontier",
    )
    payload = {
        "authority_path": CANONICAL_AUTHORITY,
        "authority_sha": "a" * 64,
        "authority_version": "V12",
        "official_universe_denominator": 657,
        "evaluated_denominator": 657,
        "gate0": {"status": "PASS"},
        "component_scores": {
            "PROVEN_HISTORICAL": 70.0,
            "TACTICAL_ROLE": 72.0,
            "CURRENT_UNDERLYING": 75.0,
            "FIXTURE_SECURITY": 68.0,
        },
        "weights": CANONICAL_WEIGHTS,
        "bayesian_lineage": {"prior": "historical", "posterior": "current", "shrinkage": True},
        "probability_state": probability,
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "mean": 67.0,
            "std": 18.0,
        },
        "horizons": build_horizon_analysis(
            one_gw={"expected_points_delta": 0.4},
            three_gw={"expected_points_delta": 1.1},
            five_gw={"expected_points_delta": 1.8},
        ),
        "transfer_economics": build_transfer_economics(
            ft_used=0,
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
            reacquisition_plan={},
        ),
        "robustness": {"expected_regret": 0.4, "conditional_floor": 2.0, "upper_tail": 9.0},
        "expected_regret": 0.4,
        "information_value_of_waiting": 0.2,
        "covariance": {"material": False},
        "icon_overlay": {"applied_after_football_optimal_baseline": True},
        "monte_carlo": {"execution_state": "NOT_RUN", "reason": "not required for this synthetic contract test"},
        "final_action": "WAIT",
        "search_authority": "FULL",
        "execution_provenance": {
            "runtime": "CHATGPT_AUTOMATION",
            "repository_python_executed": False,
            "repository_contract_only": True,
        },
        "decision_scope": "FIXED_SQUAD",
    }
    payload.update(overrides)
    return payload


def _legal_squad():
    rows = []
    element = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(count):
            rows.append(
                {
                    "element": element,
                    "position": position,
                    "team_id": element,
                    "now_cost": 50,
                    "sell_value": 50,
                    "status": "a",
                    "eligible": True,
                }
            )
            element += 1
    return rows


def _candidate_universe():
    return [
        {"element": 101, "position": "GK", "team_id": 16, "now_cost": 50, "status": "a", "eligible": True},
        {"element": 102, "position": "DEF", "team_id": 17, "now_cost": 50, "status": "a", "eligible": True},
        {"element": 103, "position": "MID", "team_id": 18, "now_cost": 50, "status": "a", "eligible": True},
        {"element": 104, "position": "FWD", "team_id": 19, "now_cost": 50, "status": "a", "eligible": True},
    ]


def test_01_canonical_has_zero_legacy_oracle_execution_permission():
    text = CANONICAL.read_text(encoding="utf-8")
    assert "may execute as MIGRATION_ORACLE" not in text
    assert "remains CI REGRESSION_ORACLE" not in text
    assert "MIGRATION_ORACLE execution is forbidden" in text
    assert "CI REGRESSION_ORACLE execution is forbidden" in text


def test_02_static_legacy_guard_proves_v3_v4_v5_execution_forbidden():
    assert validate_legacy_isolation(ROOT) == []


def test_03_full_serious_search_requires_exact_owned15_and_denominator_proof():
    validated = validate_search_proof(_full_search_proof(), search_authority="FULL")
    assert validated["owned_expected"] == 15
    assert validated["owned_evaluated"] == 15
    assert validated["denominator_complete"] is True
    with pytest.raises(MethodologyContractError):
        validate_search_proof(
            _full_search_proof(owned_evaluated=14),
            search_authority="FULL",
        )


def test_04_user_named_out_is_hypothesis_not_mandatory_outgoing():
    scan = validate_owned_out_scan(
        {
            "evaluated_owned_element_ids": list(range(1, 16)),
            "selected_outgoing_element_ids": [2],
            "user_named_outgoing_element_ids": [1],
            "selection_is_result_not_precondition": True,
            "user_named_out_is_hypothesis_only": True,
        },
        require_complete=True,
    )
    assert scan["selected_outgoing_element_ids"] == [2]
    assert scan["user_named_outgoing_element_ids"] == [1]
    assert scan["second_outgoing_score_created"] is False


def test_05_weak_link_must_be_result_not_input_precondition():
    with pytest.raises(MethodologyContractError):
        validate_owned_out_scan(
            {
                "evaluated_owned_element_ids": list(range(1, 16)),
                "selected_outgoing_element_ids": [1],
                "selection_is_result_not_precondition": False,
                "user_named_out_is_hypothesis_only": True,
            },
            require_complete=True,
        )


def test_06_hold_is_mandatory_for_full_search_authority():
    with pytest.raises(MethodologyContractError):
        validate_search_proof(
            _full_search_proof(hold_included=False),
            search_authority="FULL",
        )


def test_07_full_requires_exact_universe_denominator_agreement():
    with pytest.raises(MethodologyContractError):
        validate_search_proof(
            _full_search_proof(eligible_universe_evaluated=646),
            search_authority="FULL",
        )


def test_08_partial_is_the_only_truthful_authority_when_denominator_is_incomplete():
    partial = _full_search_proof(
        eligible_universe_evaluated=646,
        search_authority="PARTIAL",
    )
    validated = validate_search_proof(partial, search_authority="PARTIAL")
    assert validated["search_authority"] == "PARTIAL"
    assert validated["denominator_complete"] is False


def test_09_full_forbids_lossy_pruning():
    with pytest.raises(MethodologyContractError):
        validate_search_proof(
            _full_search_proof(lossy_pruning=True),
            search_authority="FULL",
        )


def test_10_pairwise_battle_retains_owned_challenger_and_material_deltas():
    battle = validate_pairwise_battles([_pairwise_battle()])[0]
    assert battle["owned_element_id"] == 1
    assert battle["challenger_element_id"] == 101
    assert battle["material_deltas"]["football_score"] == 3.2
    assert battle["diagnostic_evidence_only"] is True


def test_11_pairwise_evidence_cannot_create_second_decision_authority():
    with pytest.raises(MethodologyContractError):
        validate_pairwise_battles([_pairwise_battle(decision_authority=True)])
    with pytest.raises(MethodologyContractError):
        validate_pairwise_battles([_pairwise_battle(ranking_authority=True)])


def test_12_tactical_evidence_enum_is_exact():
    assert TACTICAL_EVIDENCE_CLASSES == frozenset(
        {"OBSERVED_ROLE", "INFERRED_ROLE", "FPL_POSITION_ONLY", "UNKNOWN"}
    )


def test_13_fpl_position_only_is_not_observed_tactical_role():
    row = classify_tactical_evidence(
        element_id=10,
        evidence_class="FPL_POSITION_ONLY",
    )
    assert row["fpl_position_is_tactical_role_proof"] is False
    assert row["tactical_numeric_evidence"] is None
    with pytest.raises(TacticalRoleContractError):
        classify_tactical_evidence(
            element_id=10,
            evidence_class="FPL_POSITION_ONLY",
            tactical_numeric_evidence=0.6,
        )


def test_14_unknown_cannot_silently_become_numeric_tactical_evidence():
    with pytest.raises(TacticalRoleContractError):
        classify_tactical_evidence(
            element_id=10,
            evidence_class="UNKNOWN",
            tactical_numeric_evidence=0.5,
        )


def test_15_state_remains_non_authoritative():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    assert state["authority"] is False
    assert state["non_authoritative_state_file"] is True
    assert state["latest_explicit_user_state_wins"] is True


def test_16_state_does_not_duplicate_raw_v6_payload():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    assert state["model_evidence"]["raw_v6_payload_persisted"] is False
    serialized = json.dumps(state, sort_keys=True)
    assert '"raw_v6_payload":' not in serialized
    assert '"raw_v6_payloads":' not in serialized


def test_17_package_search_emits_exact_owned15_first_search_proof():
    result = search_packages(
        current_squad=_legal_squad(),
        candidate_universe=_candidate_universe(),
        bank=0,
        max_transfers=2,
        universe_complete=True,
        expected_eligible_universe_count=4,
        lossy_pruning=False,
    )
    proof = result["search_proof"]
    assert proof == {
        "owned_expected": 15,
        "owned_evaluated": 15,
        "eligible_universe_expected": 4,
        "eligible_universe_evaluated": 4,
        "outgoing_candidate_count": 15,
        "outgoing_combination_count": 120,
        "legal_route_count": len(result["routes"]),
        "hold_included": True,
        "lossy_pruning": False,
        "search_authority": "FULL",
    }
    assert result["owned_out_scan"]["evaluated_owned_element_ids"] == list(range(1, 16))
    assert result["owned_out_scan"]["selection_is_result_not_precondition"] is True
    assert result["governance"]["user_named_out_is_never_search_precondition"] is True


def test_18_static_v12_test_workflow_contains_no_legacy_runtime_execution():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m src.runtime_v3" not in text
    assert "python -m src.runtime_v4" not in text
    assert "python -m src.runtime_v5" not in text
    assert "package_optimizer_shards" not in text
    assert "package_optimizer_exhaustive_accelerated" not in text


def test_19_canonical_search_proof_surface_is_explicit_and_no_fake_full_claim():
    text = CANONICAL.read_text(encoding="utf-8")
    for token in (
        "OUR15_EXPECTED",
        "OUR15_EVALUATED",
        "ELIGIBLE_UNIVERSE_EXPECTED",
        "ELIGIBLE_UNIVERSE_EVALUATED",
        "OUTGOING_CANDIDATES_EVALUATED",
        "OUTGOING_COMBINATIONS_EVALUATED",
        "LEGAL_ROUTES_EVALUATED",
        "HOLD_INCLUDED",
        "LOSSY_PRUNING",
        "SEARCH_AUTHORITY",
    ):
        assert token in text
    assert "Never render FULL-UNIVERSE OPTIMIZED unless FULL authority is proven" in text


def test_20_canonical_20_25_30_25_is_unchanged():
    assert CANONICAL_WEIGHTS == {
        "PROVEN_HISTORICAL": 0.20,
        "TACTICAL_ROLE": 0.25,
        "CURRENT_UNDERLYING": 0.30,
        "FIXTURE_SECURITY": 0.25,
    }
    score = compute_football_score(
        {
            "PROVEN_HISTORICAL": 50,
            "TACTICAL_ROLE": 50,
            "CURRENT_UNDERLYING": 50,
            "FIXTURE_SECURITY": 50,
        }
    )
    assert score["football_score"] == 50.0


def test_21_tactical_taxonomy_does_not_change_p1_6_math():
    observed = classify_tactical_evidence(
        element_id=10,
        evidence_class="OBSERVED_ROLE",
        tactical_numeric_evidence=0.6,
        provenance="fixture-role-observation",
        fingerprint="abc123",
    )
    assert CANONICAL_WEIGHT == 0.25
    assert observed["changes_canonical_score"] is False
    assert observed["changes_p1_6_math"] is False


def test_22_static_guard_text_preserves_zero_legacy_fallback_and_v6_data_only():
    text = CANONICAL.read_text(encoding="utf-8")
    assert "Production factual data plane = V6 ONLY. NEVER V3/V4/V5." in text
    assert "No legacy fallback is permitted." in text
    assert "V3/V4/V5 runtime execution is forbidden." in text



def test_23_fixed_squad_xi_does_not_require_transfer_search_proof():
    proof = build_decision_proof(**_decision_kwargs())
    assert proof["decision_scope"] == "FIXED_SQUAD"
    assert proof["search_proof"] is None
    assert proof["search_authority_applies"] is False
    assert proof["optimization_claim"] == "FIXED_SQUAD_NO_TRANSFER_UNIVERSE_CLAIM"


def test_24_fixed_squad_captain_vice_does_not_require_transfer_search_proof():
    proof = build_decision_proof(**_decision_kwargs(final_action="PREPARE"))
    assert proof["decision_scope"] == "FIXED_SQUAD"
    assert proof["search_proof"] is None
    assert proof["search_authority_applies"] is False


def test_25_fixed_squad_bench_order_does_not_require_transfer_search_proof():
    proof = build_decision_proof(**_decision_kwargs(final_action="WAIT"))
    assert proof["decision_scope"] == "FIXED_SQUAD"
    assert proof["search_proof"] is None


def test_26_serious_transfer_still_requires_search_proof():
    with pytest.raises(MethodologyContractError, match="SEARCH_PROOF"):
        build_decision_proof(
            **_decision_kwargs(
                decision_scope="TRANSFER",
                serious_transfer_decision=True,
                owned_out_scan=_owned_out_scan(),
                pairwise_empty_reason="NO_MATERIAL_CHALLENGER",
            )
        )


def test_27_explicit_full_universe_claim_requires_search_proof_even_if_scope_fixed():
    with pytest.raises(MethodologyContractError, match="SEARCH_PROOF"):
        build_decision_proof(
            **_decision_kwargs(
                optimization_claim="FULL_UNIVERSE_OPTIMIZED",
            )
        )


def test_28_serious_transfer_full_keeps_strict_search_requirements():
    proof = build_decision_proof(
        **_decision_kwargs(
            decision_scope="TRANSFER",
            serious_transfer_decision=True,
            search_proof=_full_search_proof(eligible_universe_expected=657, eligible_universe_evaluated=657),
            owned_out_scan=_owned_out_scan(),
            pairwise_empty_reason="HOLD_DOMINATES_ALL_MATERIAL_ROUTES",
        )
    )
    assert proof["search_authority_applies"] is True
    assert proof["search_proof"]["owned_evaluated"] == 15
    with pytest.raises(MethodologyContractError):
        build_decision_proof(
            **_decision_kwargs(
                decision_scope="TRANSFER",
                serious_transfer_decision=True,
                search_proof=_full_search_proof(
                    eligible_universe_expected=657,
                    eligible_universe_evaluated=656,
                ),
                owned_out_scan=_owned_out_scan(),
                pairwise_empty_reason="NO_MATERIAL_CHALLENGER",
            )
        )


def test_29_partial_transfer_cannot_claim_full_universe_optimized():
    partial = _full_search_proof(
        eligible_universe_expected=657,
        eligible_universe_evaluated=656,
        search_authority="PARTIAL",
    )
    with pytest.raises(MethodologyContractError):
        build_decision_proof(
            **_decision_kwargs(
                decision_scope="TRANSFER",
                search_authority="PARTIAL",
                optimization_claim="FULL_UNIVERSE_OPTIMIZED",
                search_proof=partial,
                owned_out_scan=_owned_out_scan(),
            )
        )


def test_30_valid_observed_role_binding_passes_without_changing_tactical_math():
    proof = build_decision_proof(
        **_decision_kwargs(
            tactical_evidence_classes=[
                {
                    "element_id": 1,
                    "evidence_class": "OBSERVED_ROLE",
                    "tactical_numeric_evidence": 0.65,
                    "provenance": "observed-role-source",
                    "fingerprint": "obs-fingerprint",
                }
            ]
        )
    )
    row = proof["tactical_evidence_classes"][0]
    assert row["evidence_class"] == "OBSERVED_ROLE"
    assert row["changes_canonical_score"] is False
    assert row["changes_p1_6_math"] is False
    assert CANONICAL_WEIGHT == 0.25


def test_31_valid_inferred_role_requires_and_retains_provenance():
    proof = build_decision_proof(
        **_decision_kwargs(
            tactical_evidence_classes=[
                {
                    "element_id": 1,
                    "evidence_class": "INFERRED_ROLE",
                    "tactical_numeric_evidence": 0.55,
                    "provenance": "bounded-factual-inference",
                }
            ]
        )
    )
    assert proof["tactical_evidence_classes"][0]["provenance"] == "bounded-factual-inference"


def test_32_fpl_position_only_numeric_fails_inside_decision_proof():
    with pytest.raises(MethodologyContractError):
        build_decision_proof(
            **_decision_kwargs(
                tactical_evidence_classes=[
                    {
                        "element_id": 1,
                        "evidence_class": "FPL_POSITION_ONLY",
                        "tactical_numeric_evidence": 0.5,
                    }
                ]
            )
        )


def test_33_unknown_numeric_fails_inside_decision_proof():
    with pytest.raises(MethodologyContractError):
        build_decision_proof(
            **_decision_kwargs(
                tactical_evidence_classes=[
                    {
                        "element_id": 1,
                        "evidence_class": "UNKNOWN",
                        "tactical_numeric_evidence": 0.5,
                    }
                ]
            )
        )


def test_34_invalid_tactical_enum_fails_inside_decision_proof():
    with pytest.raises(MethodologyContractError):
        build_decision_proof(
            **_decision_kwargs(
                tactical_evidence_classes=[
                    {
                        "element_id": 1,
                        "evidence_class": "OBSERVED_POSITION_ROLE",
                        "provenance": "invalid-enum-test",
                    }
                ]
            )
        )


def test_35_material_pairwise_requires_complete_canonical_surface():
    battle = validate_pairwise_battles([_pairwise_battle()])[0]
    for key in (
        "football_score_delta",
        "component_comparison",
        "p_available_comparison",
        "p_start_comparison",
        "xmins_comparison",
        "p_return_comparison",
        "p_blank_comparison",
        "material_tail_comparison",
        "expected_points_comparison",
        "tactical_role_comparison",
        "tactical_evidence_class",
        "set_piece_penalty_comparison",
        "gw_plus_1",
        "three_gw",
        "five_gw",
        "price_economic_delta",
        "robustness_delta",
        "expected_regret",
        "information_value_of_waiting",
        "mini_league_leverage",
    ):
        assert key in battle


def test_36_missing_pairwise_semantic_field_fails():
    battle = _pairwise_battle()
    battle.pop("p_blank_comparison")
    with pytest.raises(MethodologyContractError, match="p_blank_comparison"):
        validate_pairwise_battles([battle])


def test_37_explicit_unavailable_pairwise_value_requires_reason_and_passes_with_reason():
    bad = _pairwise_battle(material_tail_comparison=None)
    with pytest.raises(MethodologyContractError, match="material_tail_comparison"):
        validate_pairwise_battles([bad])

    good = _pairwise_battle(
        material_tail_comparison=None,
        unavailable_reasons={
            "material_tail_comparison": "calibrated tail distribution unavailable"
        },
    )
    row = validate_pairwise_battles([good])[0]
    assert row["material_tail_comparison"] is None
    assert row["unavailable_reasons"]["material_tail_comparison"]


def test_38_pairwise_action_is_exact_wait_prepare_act():
    with pytest.raises(MethodologyContractError):
        validate_pairwise_battles([_pairwise_battle(operational_action="TRANSFER")])


def test_39_material_change_route_cannot_omit_pairwise_battle():
    with pytest.raises(MethodologyContractError, match="pairwise"):
        build_decision_proof(
            **_decision_kwargs(
                decision_scope="TRANSFER",
                search_proof=_full_search_proof(eligible_universe_expected=657, eligible_universe_evaluated=657),
                owned_out_scan=_owned_out_scan(selected_outgoing_element_ids=[1]),
                material_challenger_present=True,
                selected_change_route=True,
            )
        )


def test_40_serious_transfer_hold_dominant_may_have_empty_pairwise_with_exact_reason():
    proof = build_decision_proof(
        **_decision_kwargs(
            decision_scope="TRANSFER",
            serious_transfer_decision=True,
            search_proof=_full_search_proof(eligible_universe_expected=657, eligible_universe_evaluated=657),
            owned_out_scan=_owned_out_scan(),
            pairwise_battles=[],
            pairwise_empty_reason="HOLD_DOMINATES_ALL_MATERIAL_ROUTES",
        )
    )
    assert proof["pairwise_battles"] == []
    assert proof["pairwise_empty_reason"] == "HOLD_DOMINATES_ALL_MATERIAL_ROUTES"


def test_41_serious_transfer_empty_pairwise_without_reason_fails():
    with pytest.raises(MethodologyContractError, match="empty pairwise"):
        build_decision_proof(
            **_decision_kwargs(
                decision_scope="TRANSFER",
                serious_transfer_decision=True,
                search_proof=_full_search_proof(eligible_universe_expected=657, eligible_universe_evaluated=657),
                owned_out_scan=_owned_out_scan(),
                pairwise_battles=[],
            )
        )


def test_42_pure_fixed_squad_decision_does_not_require_pairwise():
    proof = build_decision_proof(**_decision_kwargs(pairwise_battles=[]))
    assert proof["pairwise_battles"] == []
    assert proof["pairwise_empty_reason"] is None
