import pytest

from src.v5.config_cache import load_json_config
from src.v5.intelligence import projection
from src.v5.intelligence.feature_fusion import fuse_advanced_attack, validate_feature_fusion_config
from src.v5.intelligence.native_feature_trace import build_native_feature_trace


def _fusion_cfg():
    return load_json_config("config/intelligence/projection.json")["authoritative_feature_fusion"]


def test_advanced_attack_fusion_requires_minimum_minutes():
    result = fuse_advanced_attack(
        position="MID",
        native_xg90=0.20,
        native_xa90=0.10,
        position_xg_prior=0.22,
        position_xa_prior=0.20,
        advanced={"minutes": 20, "xg": 1.0, "xa": 0.5},
        config=_fusion_cfg(),
    )
    assert result["status"] == "AVAILABLE_NOT_APPLIED"
    assert result["applied"] is False
    assert result["xg90_final"] == pytest.approx(0.20)
    assert result["xa90_final"] == pytest.approx(0.10)


def test_advanced_attack_fusion_is_bounded_secondary_evidence():
    result = fuse_advanced_attack(
        position="MID",
        native_xg90=0.20,
        native_xa90=0.10,
        position_xg_prior=0.22,
        position_xa_prior=0.20,
        advanced={"minutes": 90, "xg": 2.0, "xa": 1.0},
        config=_fusion_cfg(),
    )
    assert result["status"] == "APPLIED"
    assert result["applied"] is True
    assert 0.0 < result["weight"] <= 0.25
    assert result["xg"]["candidate_bounded"] <= result["xg"]["upper_bound"]
    assert result["xa"]["candidate_bounded"] <= result["xa"]["upper_bound"]
    assert result["xg90_final"] > result["xg90_native"]
    assert result["xa90_final"] > result["xa90_native"]
    assert result["xg90_final"] < result["xg"]["candidate_bounded"]
    assert result["xa90_final"] < result["xa"]["candidate_bounded"]
    assert result["used_fields"] == ["minutes", "xg", "xa"]


def test_advanced_attack_fusion_skips_goalkeeper():
    result = fuse_advanced_attack(
        position="GK",
        native_xg90=0.01,
        native_xa90=0.01,
        position_xg_prior=0.01,
        position_xa_prior=0.01,
        advanced={"minutes": 90, "xg": 1.0, "xa": 1.0},
        config=_fusion_cfg(),
    )
    assert result["status"] == "POSITION_INELIGIBLE"
    assert result["applied"] is False


def test_feature_fusion_registry_validation_rejects_invalid_weight():
    cfg = {**_fusion_cfg(), "advanced_attacking": {**_fusion_cfg()["advanced_attacking"], "maximum_weight": 1.5}}
    with pytest.raises(RuntimeError, match="maximum_weight"):
        validate_feature_fusion_config(cfg)


def test_native_feature_trace_claims_advanced_attack_only_when_applied():
    prediction = {
        "players": [
            {
                "element": 1,
                "team_id": 10,
                "current_season": {"starts": 1, "minutes": 90},
                "historical_prior": None,
                "xmins": {},
                "rates": {"historical_attacking_prior_weight": 0.0},
                "role": {},
                "fixtures": [{"event": 2, "xpts": 5.0}],
                "defensive_contribution": {},
                "authoritative_feature_fusion": {
                    "advanced_attacking": {
                        "applied": True,
                        "used_fields": ["minutes", "xg", "xa"],
                        "evidence_minutes": 90.0,
                        "weight": 0.035714,
                        "xg90_native": 0.20,
                        "xg90_final": 0.203,
                        "xa90_native": 0.10,
                        "xa90_final": 0.102,
                    },
                    "current_form": {
                        "status": "AVAILABLE_NOT_APPLIED",
                        "authoritative": False,
                        "reason": "no settled point-in-time rolling recency window yet",
                    },
                },
            }
        ]
    }
    enrichment = {
        "advanced_stats": {
            "source": "FPL-Core-Insights",
            "players": {"1": {"minutes": 90, "shots": 5, "xg": 0.9, "xa": 0.4}},
        },
        "current_form": {
            "source": "official_fpl+fpl_core_insights+understat_challenger",
            "players": {"1": {"official_form": 6.0}},
        },
        "schedule": {},
        "preseason": {"evidence_status": "UNAVAILABLE"},
    }
    trace = build_native_feature_trace(prediction, enrichment)
    attack = trace["players"]["1"]["states"]["advanced_attacking_stats"]
    current = trace["players"]["1"]["states"]["current_form_enrichment"]
    assert attack["state"] == "ACTIVE"
    assert attack["effect_scopes"] == ["AUTHORITATIVE_XPTS"]
    assert attack["authoritative_effect"] is True
    assert attack["consumption_evidence"][0]["contribution"]["used_fields"] == ["minutes", "xg", "xa"]
    assert "advanced_attacking_stats" not in trace["unintegrated_features"]
    assert current["state"] == "AVAILABLE"
    assert current["authoritative_effect"] is False
    assert "current_form_enrichment" in trace["unintegrated_features"]


def test_projection_xpts_changes_only_when_advanced_attack_fusion_is_applied(monkeypatch):
    bootstrap = {
        "teams": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        "elements": [
            {
                "id": 10,
                "web_name": "P10",
                "team": 1,
                "element_type": 3,
                "now_cost": 70,
                "status": "a",
                "selected_by_percent": "10.0",
                "starts": 1,
                "minutes": 90,
                "expected_goals": 0.20,
                "expected_assists": 0.10,
                "bonus": 0,
                "saves": 0,
            }
        ],
    }
    rules = {
        "goal_points": {"1": 6, "2": 6, "3": 5, "4": 4},
        "clean_sheet_points": {"1": 4, "2": 4, "3": 1, "4": 0},
        "assist_points": 3,
        "ruleset_id": "FPL_2026_27",
    }
    strength = {
        "baseline": {"home_goals": 1.5, "away_goals": 1.2},
        "teams": [{"team_id": 1, "matches_played": 1}, {"team_id": 2, "matches_played": 1}],
        "matchups": [
            {
                "event": 2,
                "team_h": 1,
                "team_a": 2,
                "kickoff_time": "2026-08-29T14:00:00+00:00",
                "home_expected_goals": 1.5,
                "away_expected_goals": 1.0,
                "home_clean_sheet_probability": 0.30,
                "away_clean_sheet_probability": 0.20,
            }
        ],
    }
    monkeypatch.setattr(projection, "build_team_strength", lambda *args, **kwargs: strength)
    monkeypatch.setattr(
        projection,
        "build_role_intelligence",
        lambda *args, **kwargs: {
            "model": "test-role",
            "players": {10: {"role_start_probability": 1.0, "rotation_risk": 0.0, "set_piece_share": 0.0, "penalty_share": 0.0}},
            "projection_adjustment": {"set_piece_assist_uplift": 0.08, "penalty_goal_uplift": 0.18},
            "capabilities": [],
            "non_claims": [],
        },
    )
    monkeypatch.setattr(
        projection,
        "estimate_xmins",
        lambda *args, **kwargs: {
            "start_probability": 1.0,
            "bench_probability": 0.0,
            "dnp_probability": 0.0,
            "expected_minutes": 90.0,
            "starter_minutes_if_start": 90.0,
            "minutes_std": 0.0,
            "small_sample_guard": False,
            "confidence": "HIGH",
        },
    )
    monkeypatch.setattr(
        projection,
        "build_rate_bundle",
        lambda **kwargs: {"expected_points90": 0.0, "source": "position_prior_probability_calibrated", "eligible": False},
    )
    monkeypatch.setattr(projection, "project_fixture_points", lambda *args, **kwargs: {"points": 0.0})

    no_evidence = projection.build_predictions(bootstrap, [], rules, 2, horizon=1, full_enrichment={"advanced_stats": {"players": {}}})
    with_evidence = projection.build_predictions(
        bootstrap,
        [],
        rules,
        2,
        horizon=1,
        full_enrichment={"advanced_stats": {"source": "FPL-Core-Insights", "players": {"10": {"minutes": 90, "xg": 1.0, "xa": 0.5}}}},
    )
    base_player = no_evidence["players"][0]
    fused_player = with_evidence["players"][0]
    assert base_player["authoritative_feature_fusion"]["advanced_attacking"]["applied"] is False
    assert fused_player["authoritative_feature_fusion"]["advanced_attacking"]["applied"] is True
    assert fused_player["rates"]["xg90"] != fused_player["rates"]["native_pre_feature_fusion"]["xg90"]
    assert fused_player["rates"]["xa90"] != fused_player["rates"]["native_pre_feature_fusion"]["xa90"]
    assert fused_player["mean_xpts"] > base_player["mean_xpts"]
    assert with_evidence["authoritative_feature_fusion"]["advanced_attacking_players_applied"] == 1
    assert with_evidence["authoritative_feature_fusion"]["current_form_authoritative"] is False
    assert with_evidence["authoritative_feature_fusion"]["rest_congestion_authoritative"] is False
