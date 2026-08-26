from __future__ import annotations

from datetime import datetime, timezone

from src.v5.decision.dss_evaluator import evaluate_dss
from src.v5.evaluation.evidence_guard import evaluate as evaluate_evidence_guard
from src.v5.intelligence.full_core_enrichment import build_full_core_enrichment
from src.v5.services.decision import handle as decision_handle
from src.v5.services.evaluation import handle as evaluation_handle
from src.v5.services.prediction import handle as prediction_handle
from src.v5.services.price import handle as price_handle
from src.v5.services.truth import _capabilities as truth_capabilities
from src.v5.source_authority import primary_authority, source_spec


def test_full_core_enrichment_uses_real_advanced_stats_and_fail_neutral_missing_evidence():
    bootstrap = {
        "teams": [{"id": 1, "name": "Arsenal"}],
        "elements": [{
            "id": 15, "team": 1, "form": "5.0", "points_per_game": "4.0", "total_points": 4,
            "starts": 1, "minutes": 90, "expected_goals": "0.1", "expected_assists": "0.2",
            "threat": "30", "creativity": "25", "transfers_in_event": 100, "transfers_out_event": 20,
        }],
    }
    fixtures = [
        {"team_h": 1, "team_a": 2, "kickoff_time": "2026-08-22T14:00:00Z"},
        {"team_h": 3, "team_a": 1, "kickoff_time": "2026-08-29T14:00:00Z"},
    ]
    result = build_full_core_enrichment(bootstrap, fixtures)
    assert result["status"] == "ACTIVE"
    assert set(result["capabilities"]) == {
        "advanced_stats_sync", "european_congestion", "domestic_cup_congestion", "international_load",
        "rest_days", "preseason_prior", "current_form",
    }
    advanced = result["advanced_stats"]
    assert advanced["status"] == "ACTIVE"
    assert advanced["shots_rows"] > 0
    assert advanced["match_rows"] > 0
    assert advanced["coverage_players"] > 0
    assert advanced["missing_player_behavior"] == "UNAVAILABLE_NOT_ZERO"
    schedule = result["schedule"]
    assert schedule["status"] == "ACTIVE"
    assert schedule["league_rest_days"]["1"]["minimum_pl_rest_days"] == 7.0
    assert schedule["governance"]["missing_specific_match_or_callup_is_unavailable_not_zero"] is True
    preseason = result["preseason"]
    assert preseason["status"] == "ACTIVE"
    assert preseason["never_fabricate_minutes_or_roles"] is True
    if preseason["evidence_status"] == "UNAVAILABLE":
        assert preseason["fallback"] == "historical_role_prior"


def test_v316_source_authority_keeps_official_native_fields_authoritative():
    assert primary_authority("player_identity").name == "official_public"
    assert primary_authority("fixtures").name == "official_public"
    assert source_spec("livefpl").kind == "challenger"
    assert source_spec("core_insights").kind == "enrichment"


def test_all_50_core_and_16_extensions_have_runtime_capability_contracts():
    truth_caps = truth_capabilities(
        {"validation": {"passed": True}, "finance": {"sell_value_complete": True}},
        {"legal": True},
    )
    prediction_caps = prediction_handle("status", {})["capabilities"]
    price_caps = price_handle("status", {})["capabilities"]
    decision_caps = decision_handle("status", {})["capabilities"]
    evaluation_caps = evaluation_handle("status", {})["capabilities"]
    guard = evaluate_evidence_guard(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "planning_gw": 2,
            "horizon_gws": 15,
            "ruleset_id": "FPL_2026_27",
            "prediction_quality": {"status": "HEALTHY"},
            "players": [],
        },
        {"planning_gw": 2, "deadline_time": "2026-08-28T17:30:00Z", "ruleset_id": "FPL_2026_27"},
        {"rules": {"ruleset_id": "FPL_2026_27"}, "team": {"validation": {"passed": True}}},
    )
    evaluation_caps = sorted({*evaluation_caps, *(guard.get("capabilities") or [])})
    result = evaluate_dss(
        {"capabilities": truth_caps},
        {"capabilities": price_caps},
        {"capabilities": prediction_caps},
        local_capabilities=decision_caps,
        external_capability_sources={"evaluation": evaluation_caps},
    )
    assert result["registry_integrity"] is True
    assert result["core"]["expected"] == 50
    assert result["core"]["counts"] == {"ACTIVE": 50}
    assert result["core"]["coverage_ratio"] == 1.0
    assert result["extensions"]["expected"] == 16
    assert result["extensions"]["counts"] == {"ACTIVE": 16}
    assert result["extensions"]["coverage_ratio"] == 1.0
    assert result["critical_partial_count"] == 0
    assert result["unqualified_go_allowed"] is True
