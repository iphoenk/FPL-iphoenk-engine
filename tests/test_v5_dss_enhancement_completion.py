from datetime import datetime, timedelta, timezone

from src.v5.decision.dss_evaluator import evaluate_dss
from src.v5.evaluation.evidence_guard import evaluate as evaluate_evidence_guard
from src.v5.governance.core import _audit_enhancements


def _healthy_truth(ruleset_id="FPL_2026_27"):
    return {"rules": {"ruleset_id": ruleset_id}, "team": {"validation": {"passed": True}}}


def test_evidence_guard_accepts_scalar_horizon_and_activates_native_contracts():
    now = datetime.now(timezone.utc)
    prediction = {
        "generated_at": (now - timedelta(seconds=2)).isoformat(),
        "planning_gw": 2,
        "horizon_gws": 5,
        "ruleset_id": "FPL_2026_27",
        "prediction_quality": {"status": "HEALTHY"},
        "players": [{"current_season": {"starts": 1}}],
    }
    context = {"planning_gw": 2, "deadline_time": (now + timedelta(days=1)).isoformat()}
    result = evaluate_evidence_guard(prediction, context, _healthy_truth())
    caps = set(result["capabilities"])
    assert result["leakage"]["pass"] is True
    assert result["leakage"]["horizon_gws"] == [2, 3, 4, 5, 6]
    assert result["freshness"]["pass"] is True
    assert result["reliability"]["pass"] is True
    assert {"leakage_guard", "data_freshness", "source_health", "reliability_overlay", "data_reliability_triangulation"}.issubset(caps)


def test_evidence_guard_rejects_future_timestamp_and_ruleset_mismatch():
    now = datetime.now(timezone.utc)
    prediction = {
        "generated_at": (now + timedelta(minutes=5)).isoformat(),
        "planning_gw": 2,
        "horizon_gws": [2, 3],
        "ruleset_id": "FPL_2026_27",
        "prediction_quality": {"status": "HEALTHY"},
        "players": [],
    }
    context = {"planning_gw": 2, "deadline_time": (now + timedelta(days=1)).isoformat()}
    result = evaluate_evidence_guard(prediction, context, _healthy_truth("OTHER_RULESET"))
    assert result["freshness"]["pass"] is False
    assert result["reliability"]["ruleset_match"] is False
    assert result["reliability"]["pass"] is False


def test_no_critical_partial_still_blocks_go_when_noncritical_dss_is_partial():
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
    assert report["all_modules_active_required_for_unqualified_go"] is True
    assert report["all_modules_active"] is False
    assert report["unqualified_go_allowed"] is False


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
