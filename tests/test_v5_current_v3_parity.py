import json
from pathlib import Path

import pytest

from src.v5.intelligence.projection import _position_projection_diagnostics
from src.v5.intelligence.xmins import estimate_xmins
from src.v5.state import Phase, primary_authority

ROOT = Path(__file__).resolve().parents[1]
MAIN_SHA = "018099be08f755e0f45b2c7526309ccc76818e4d"
CODE_SHA = MAIN_SHA
COMPILED_PLAN = "V3_COMPILED_EXECUTION_PLAN_V1"
COMPILED_PLAN_SHA = "e013d5ccb9428382f87ba29b0c1c752b7e21758106e6ed6e81380074775e7538"


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def test_current_production_reanchor_is_exact_and_keeps_frozen_truth_baseline():
    manifest = _load("config/v5_convergence_manifest.json")
    acceptance = _load("config/v5_acceptance_registry.json")
    parity = _load("config/v5_capability_parity_registry.json")

    assert manifest["baselines"]["production_truth"] == "v3.20.0"
    assert manifest["baselines"]["production_main_sha"] == MAIN_SHA
    assert manifest["baselines"]["production_code_commit"] == CODE_SHA
    assert manifest["baselines"]["production_runtime_schema_version"] == 49
    assert manifest["baselines"]["production_execution_registry"] == "V3_EXECUTION_DOMAINS_V2"
    assert manifest["baselines"]["production_compiled_plan_registry"] == COMPILED_PLAN
    assert manifest["baselines"]["production_compiled_plan_sha256"] == COMPILED_PLAN_SHA
    assert acceptance["convergence"]["production_main_sha"] == MAIN_SHA
    assert acceptance["convergence"]["production_code_commit"] == CODE_SHA
    assert acceptance["convergence"]["production_compiled_plan_registry"] == COMPILED_PLAN
    assert acceptance["convergence"]["production_compiled_plan_sha256"] == COMPILED_PLAN_SHA
    assert parity["current_production_reanchor"]["production_main_sha"] == MAIN_SHA
    assert parity["current_production_reanchor"]["production_code_commit"] == CODE_SHA
    assert parity["current_production_reanchor"]["v3_topology"]["compiled_plan_registry"] == COMPILED_PLAN
    assert parity["current_production_reanchor"]["v3_topology"]["compiled_plan_sha256"] == COMPILED_PLAN_SHA
    assert parity["governance"]["reanchor_requires_full_v5_gate"] is True
    assert parity["governance"]["reanchor_does_not_change_frozen_football_truth_baseline"] is True


def test_compiled_v3_control_plane_is_reconciled_without_duplicate_v5_execution_truth():
    parity = _load("config/v5_capability_parity_registry.json")
    control = parity["current_production_reanchor"]["control_plane_equivalence"]
    assert set(control) == {
        "canonical_orchestration_registry",
        "single_service_module_ownership",
        "artifact_persistence_contract",
        "dependency_and_parallelism_contract",
    }
    for row in control.values():
        assert row["v5_owner"]
        assert (ROOT / row["evidence"]).exists()
    assert parity["governance"]["compiled_v3_control_plane_does_not_create_v5_service_or_business_authority"] is True
    assert parity["governance"]["duplicate_human_maintained_execution_truth_forbidden"] is True


def test_predeadline_current_team_prefers_authenticated_official():
    registry = _load("config/v5_phase_authority_registry.json")
    assert registry["pre_deadline_governance"]["official_authenticated_is_default_current_team_authority"] is True
    assert primary_authority(Phase.PRE_DEADLINE, "squad") == "official_authenticated"
    assert registry["phases"]["PRE_DEADLINE"]["squad"][:2] == ["official_authenticated", "user_lock"]


def test_xmins_explicit_probabilities_and_expected_minutes_reconcile():
    result = estimate_xmins(
        {
            "status": "a",
            "chance_of_playing_next_round": 100,
            "starts": 2,
            "minutes": 155,
        },
        {
            "team_matches_played": 2,
            "prior_start_probability": 0.82,
            "prior_evidence_minutes": 1600,
            "starter_minutes_prior": 78,
        },
    )
    assert result["probability_sum"] == pytest.approx(1.0, abs=0.002)
    assert result["overall_availability"] == result["availability"]
    assert result["expected_minutes_if_start"] == result["starter_minutes_if_start"]
    components = result["expected_minutes_components"]
    derived = components["start_minutes_contribution"] + components["bench_minutes_contribution"]
    assert derived == pytest.approx(result["expected_minutes"], abs=0.25)
    assert result["governance"]["expected_minutes_derived_from_explicit_probabilities"] is True


def test_projection_diagnostics_are_observational_and_component_based():
    players = [
        {
            "element": 1,
            "position": "DEF",
            "xpts_by_gw": [
                {
                    "fixtures": [
                        {
                            "mean": 5.0,
                            "components": {
                                "appearance": 1.5,
                                "attack": 1.0,
                                "clean_sheet": 1.5,
                                "saves": 0.0,
                                "defensive_contribution": 0.5,
                                "bonus": 0.5,
                            },
                        }
                    ]
                }
            ],
        }
    ]
    diagnostic = _position_projection_diagnostics(players)
    assert diagnostic["status"] == "READY"
    assert diagnostic["mutates_xpts"] is False
    row = diagnostic["positions"]["DEF"]
    assert row["mean_xpts_per_fixture"] == 5.0
    assert row["defensive_component_share"] == pytest.approx(0.5)
    assert row["ablation_mean_xpts_per_fixture"]["without_clean_sheet"] == 3.5
    assert diagnostic["governance"]["component_observability_does_not_change_projection_formula"] is True


def test_current_v3_capability_reanchor_has_explicit_equivalence_evidence():
    parity = _load("config/v5_capability_parity_registry.json")
    evidence = parity["current_production_reanchor"]["capability_equivalence"]
    required = {
        "gw_scoped_chip_override",
        "authenticated_official_predeadline_team",
        "explicit_xmins_probability_decomposition",
        "projection_component_observability",
        "tactical_xpts_immutability",
        "governed_lineup_uncertainty",
        "captain_safe_pool_and_independent_vice",
        "close_call_lineup_arbitration",
        "genuine_predeadline_decision_snapshot",
        "owned_challenger_comparator",
        "historical_prediction_settlement",
        "final_governed_publication",
    }
    assert required <= set(evidence)
    assert all(value.get("v5_owner") and value.get("evidence") for value in evidence.values())
