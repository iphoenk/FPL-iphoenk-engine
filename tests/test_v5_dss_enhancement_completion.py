from src.v5.decision.dss_evaluator import evaluate_dss
from src.v5.evaluation.evidence_guard import evaluate as evaluate_evidence_guard
from src.v5.governance.core import _audit_enhancements


def test_evidence_guard_activates_native_reliability_contracts():
    prediction = {
        "generated_at": "2099-01-01T00:00:00+00:00",
        "planning_gw": 2,
        "horizon_gws": [2, 3, 4, 5, 6],
        "ruleset_id": "FPL_2026_27",
        "prediction_quality": {"status": "HEALTHY"},
        "players": [{"current_season": {"starts": 1}}],
    }
    context = {"planning_gw": 2, "deadline_time": "2099-01-02T00:00:00Z"}
    result = evaluate_evidence_guard(prediction, context)
    caps = set(result["capabilities"])
    assert result["leakage"]["pass"] is True
    assert {"leakage_guard", "data_freshness", "source_health", "reliability_overlay", "data_reliability_triangulation"}.issubset(caps)


def test_no_critical_dss_partial_with_native_v5_capabilities():
    truth = {"capabilities": [
        "universe_identity", "universe_price_position", "universe_registration", "availability",
        "manual_authority", "defcon_rules", "sell_cost_affordability", "chip_context", "structural_fit",
    ]}
    prediction = {"capabilities": [
        "xmins", "xmins_distribution", "tactical_role", "system_fit", "rotation_competition",
        "set_piece_role", "penalty_role", "historical_prior", "last_season_integration", "price_value",
        "opponent_defence_dynamic", "horizon_3", "horizon_5", "horizon_10", "horizon_15",
        "projection_uncertainty", "small_sample_guard", "team_attacking_strength", "team_defensive_strength",
        "fixture_context", "fixture_swing", "ownership_context", "bonus_route", "clean_sheet_probability",
    ]}
    price = {"capabilities": ["price_intelligence", "transfer_momentum"]}
    local = [
        "direct_challenger", "structural_fit", "governed_optimizer", "package_churn_penalty",
        "package_structural", "multi_horizon", "decision_recheck", "early_season_change_cap",
        "lineup_governance", "captaincy", "lineup_robustness", "captain_dnp_guard", "bench_utility",
    ]
    external = {"evaluation": [
        "calibration_store", "learning_loop", "leakage_guard", "reliability_overlay",
        "data_freshness", "source_health",
    ]}
    report = evaluate_dss(truth, price, prediction, local_capabilities=local, external_capability_sources=external)
    assert report["registry_integrity"] is True
    assert report["critical_partial_count"] == 0, report["critical_partial"]
    assert report["unqualified_go_allowed"] is True


def test_all_critical_enhancement_layers_have_runtime_evidence():
    sources = {
        "data_reliability_triangulation": ["evaluation"],
        "leakage_guard": ["evaluation"],
        "uncertainty_robustness": ["governance-derived"],
        "multi_horizon": ["decision"],
        "price_intelligence": ["price"],
        "package_structural": ["decision"],
        "lineup_governance": ["decision"],
        "final_governance": ["governance"],
    }
    report = _audit_enhancements(sources)
    critical_partial = [x for x in report["items"] if x["critical"] and x["status"] != "ACTIVE"]
    assert report["integrity_ok"] is True
    assert critical_partial == []
