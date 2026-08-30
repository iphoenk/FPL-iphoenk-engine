import json
import re
from pathlib import Path

import pytest

from src.v5.intelligence.projection import _position_projection_diagnostics
from src.v5.intelligence.xmins import estimate_xmins
from src.v5.state import Phase, authority_chain

ROOT = Path(__file__).resolve().parents[1]
COMPILED_PLAN = "V3_COMPILED_EXECUTION_PLAN_V1"
COMPILED_PLAN_SHA = "af929aa55483f0e8959247a9d1794e70f7840d32f7bf6e5a7bc9d4ceac59e467"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def test_current_production_reanchor_is_exact_and_keeps_frozen_truth_baseline():
    manifest = _load("config/v5_convergence_manifest.json")
    acceptance = _load("config/v5_acceptance_registry.json")
    parity = _load("config/v5_capability_parity_registry.json")
    status = _load("IMPLEMENTATION_STATUS.json")

    deployed_sha = manifest["baselines"]["production_main_sha"]
    assert SHA40.fullmatch(deployed_sha), deployed_sha
    assert manifest["baselines"]["production_truth"] == "v3.20.0"
    assert manifest["baselines"]["production_code_commit"] == deployed_sha
    assert manifest["baselines"]["production_runtime_schema_version"] == 49
    assert manifest["baselines"]["production_execution_registry"] == "V3_EXECUTION_DOMAINS_V2"
    assert manifest["baselines"]["production_compiled_plan_registry"] == COMPILED_PLAN
    assert manifest["baselines"]["production_compiled_plan_sha256"] == COMPILED_PLAN_SHA
    assert manifest["baselines"]["production_capability_telemetry_registry"] == "V3_CAPABILITY_TELEMETRY_V1"
    assert acceptance["convergence"]["production_main_sha"] == deployed_sha
    assert acceptance["convergence"]["production_code_commit"] == deployed_sha
    assert acceptance["convergence"]["production_compiled_plan_registry"] == COMPILED_PLAN
    assert acceptance["convergence"]["production_compiled_plan_sha256"] == COMPILED_PLAN_SHA
    assert parity["current_production_reanchor"]["production_main_sha"] == deployed_sha
    assert parity["current_production_reanchor"]["production_code_commit"] == deployed_sha
    assert parity["authorities"]["current_production_code_commit"] == deployed_sha
    assert status["production_authority"]["main_sha"] == deployed_sha

    topology = parity["current_production_reanchor"]["v3_topology"]
    assert topology["compiled_plan_registry"] == COMPILED_PLAN
    assert topology["compiled_plan_sha256"] == COMPILED_PLAN_SHA
    assert topology["capability_telemetry_registry"] == "V3_CAPABILITY_TELEMETRY_V1"
    assert topology["sub3s_fast_lane_runtime_hardening_only"] is True
    assert topology["semantic_prediction_reuse_runtime_hardening_only"] is True
    assert topology["gameweek_lifecycle_reporting_hardening_only"] is True
    assert topology["bounded_warm_retry_runtime_workflow_hardening_only"] is True
    assert topology["official_phase_independent_fetch_overlap_runtime_hardening_only"] is True
    assert topology["authenticated_official_production_readiness_runtime_hardening_only"] is True
    assert topology["fingerprint_only_prediction_reuse_runtime_hardening_only"] is True
    assert topology["public_mini_league_membership_reporting_only"] is True
    assert parity["governance"]["reanchor_requires_full_v5_gate"] is True
    assert parity["governance"]["reanchor_does_not_change_frozen_football_truth_baseline"] is True
    assert parity["governance"]["reanchor_binds_to_deployed_runtime_not_unpublished_main_head"] is True
    assert parity["governance"]["deployed_runtime_must_be_ancestor_of_main"] is True


def test_current_v3_control_plane_is_reconciled_without_duplicate_v5_execution_truth():
    parity = _load("config/v5_capability_parity_registry.json")
    control = parity["current_production_reanchor"]["control_plane_equivalence"]
    required = {
        "canonical_orchestration_registry",
        "single_service_module_ownership",
        "artifact_persistence_contract",
        "dependency_and_parallelism_contract",
        "rules_drift_governance_contract",
        "canonical_terminology_contract",
        "capability_telemetry_contract",
        "sub3s_fast_lane_contract",
        "semantic_prediction_reuse_contract",
        "fingerprint_only_prediction_reuse_contract",
        "gameweek_lifecycle_reporting_contract",
        "bounded_warm_retry_runtime_contract",
        "official_fetch_overlap_runtime_contract",
        "authenticated_official_readiness_contract",
        "public_mini_league_reporting_contract",
    }
    assert required <= set(control)
    for row in control.values():
        assert row["v5_owner"]
        evidence_path = str(row["evidence"]).split("::", 1)[0]
        assert (ROOT / evidence_path).exists(), evidence_path
    assert parity["governance"]["compiled_v3_control_plane_does_not_create_v5_service_or_business_authority"] is True
    assert parity["governance"]["duplicate_human_maintained_execution_truth_forbidden"] is True
    assert parity["governance"]["v3_capability_telemetry_is_observational_not_decision_authority"] is True
    assert parity["governance"]["v3_sub3s_fast_lane_is_runtime_hardening_not_decision_authority"] is True
    assert parity["governance"]["v3_semantic_prediction_reuse_is_runtime_hardening_not_decision_authority"] is True
    assert parity["governance"]["v3_fingerprint_only_prediction_reuse_is_runtime_hardening_not_decision_authority"] is True
    assert parity["governance"]["v3_gameweek_lifecycle_reporting_is_not_v5_prediction_or_decision_authority"] is True
    assert parity["governance"]["v3_bounded_warm_retry_is_runtime_workflow_hardening_not_decision_authority"] is True
    assert parity["governance"]["v3_official_phase_independent_fetch_overlap_is_runtime_hardening_not_decision_authority"] is True
    assert parity["governance"]["v3_authenticated_official_readiness_is_runtime_truth_hardening_not_v5_prediction_or_decision_authority"] is True
    assert parity["governance"]["v3_authenticated_official_readiness_does_not_create_squad_lineup_or_captaincy_authority"] is True
    assert parity["governance"]["v3_public_mini_league_membership_is_reporting_truth_not_prediction_or_decision_authority"] is True
    assert parity["governance"]["history_jsonl_is_noncanonical_and_must_be_bounded"] is True


def test_predeadline_authority_is_public_official_plus_scoped_user_capture():
    registry = _load("config/v5_phase_authority_registry.json")
    governance = registry["pre_deadline_governance"]
    squad_registry = _load("config/v5_squad_registry.json")

    assert governance["primary_authority_model"] == "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE"
    assert governance["official_public_submitted_is_default_planning_baseline"] is True
    assert governance["user_capture_may_override_only_for_explicit_target_gw"] is True
    assert governance["user_capture_requires_active_wc_fh_or_planning_override"] is True
    assert governance["stale_or_unscoped_user_capture_must_not_mask_official_submitted_team"] is True
    assert governance["authenticated_official_is_optional_private_enrichment"] is True
    assert governance["authenticated_official_must_not_be_squad_lineup_or_captaincy_authority"] is True
    assert squad_registry["pre_deadline"]["default_authority"] == "official_public"
    assert squad_registry["pre_deadline"]["conditional_override_authority"] == "user_lock"
    assert squad_registry["pre_deadline"]["override_requires_exact_target_gw"] is True
    assert squad_registry["pre_deadline"]["authenticated_official_role"] == "OPTIONAL_PRIVATE_ENRICHMENT"
    assert squad_registry["pre_deadline"]["authenticated_official_is_squad_authority"] is False
    chain = authority_chain(Phase.PRE_DEADLINE, "squad")
    assert chain[:2] == ("user_lock", "official_public")
    assert "official_authenticated" not in chain


def test_xmins_explicit_probabilities_and_expected_minutes_reconcile():
    result = estimate_xmins(
        {"status": "a", "chance_of_playing_next_round": 100, "starts": 2, "minutes": 155},
        {"team_matches_played": 2, "prior_start_probability": 0.82, "prior_evidence_minutes": 1600, "starter_minutes_prior": 78},
    )
    assert result["probability_sum"] == pytest.approx(1.0, abs=0.002)
    assert result["overall_availability"] == result["availability"]
    assert result["expected_minutes_if_start"] == result["starter_minutes_if_start"]
    components = result["expected_minutes_components"]
    derived = components["start_minutes_contribution"] + components["bench_minutes_contribution"]
    assert derived == pytest.approx(result["expected_minutes"], abs=0.25)
    assert result["governance"]["expected_minutes_derived_from_explicit_probabilities"] is True


def test_projection_diagnostics_are_observational_and_component_based():
    players = [{"element": 1, "position": "DEF", "xpts_by_gw": [{"fixtures": [{"mean": 5.0, "components": {"appearance": 1.5, "attack": 1.0, "clean_sheet": 1.5, "saves": 0.0, "defensive_contribution": 0.5, "bonus": 0.5}}]}]}]
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
        "gw_scoped_chip_override", "public_official_predeadline_default_baseline", "scoped_user_capture_predeadline_override",
        "authenticated_official_optional_private_enrichment", "public_mini_league_membership",
        "explicit_xmins_probability_decomposition", "projection_component_observability",
        "verified_competitive_load_observation_validation", "tactical_xpts_immutability", "governed_lineup_uncertainty",
        "captain_safe_pool_and_independent_vice", "close_call_lineup_arbitration", "genuine_predeadline_decision_snapshot",
        "owned_challenger_comparator", "historical_prediction_settlement", "final_governed_publication",
    }
    assert required <= set(evidence)
    assert "authenticated_official_predeadline_team" not in evidence
    assert "official_submitted_predeadline_fallback" not in evidence
    assert all(value.get("v5_owner") and value.get("evidence") for value in evidence.values())
    assert (ROOT / "src/v5/intelligence/competitive_load.py").exists()
    assert (ROOT / "src/v5/mini_league.py").exists()
