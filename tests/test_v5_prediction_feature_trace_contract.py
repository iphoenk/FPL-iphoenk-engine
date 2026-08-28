from src.v5.services import prediction as prediction_service


def test_prediction_contract_exposes_player_and_aggregate_feature_use(monkeypatch):
    enrichment = {"capabilities": [], "advanced_stats": {}, "schedule": {}, "preseason": {}, "current_form": {}}
    base = {
        "generated_at": "2026-08-28T00:00:00+00:00",
        "schema_version": 515,
        "model_version": "m1",
        "ruleset_id": "FPL_2026_27",
        "planning_gw": 2,
        "horizon_gws": 15,
        "historical_prior": {},
        "defensive_contribution": {},
        "team_strength": {},
        "role_intelligence": {},
        "network_contract": {},
        "players": [
            {
                "element": 1,
                "name": "P1",
                "team_id": 1,
                "position": "MID",
                "now_cost": 70,
                "status": "a",
                "ownership_pct": 10.0,
                "current_season": {"starts": 1, "minutes": 90},
                "historical_prior": None,
                "xmins": {},
                "role": {},
                "xpts_by_gw": [],
                "horizons": {},
                "xpts_3": 0.0,
                "xpts_5": 0.0,
                "xpts_10": 0.0,
                "xpts_15": 0.0,
                "mean_xpts": 0.0,
                "uncertainty": 0.0,
                "fixtures": [],
                "projection_confidence": "LOW",
                "defensive_contribution": {},
            }
        ],
    }
    player_overlay = {
        "application_mode": "SHADOW_ONLY",
        "fixtures": [],
        "evaluated_fixtures": 0,
        "fixtures_with_rest_evidence": 0,
        "applied_fixtures": 0,
        "authoritative_xmins_replaced": False,
        "authoritative_xpts_replaced": False,
    }
    overlay = {
        "schema_version": 1,
        "model": "adjacent_fixture_rest_role_weighted_v1",
        "application_mode": "SHADOW_ONLY",
        "players": {"1": player_overlay},
        "summary": {"evaluated_fixtures": 0},
        "governance": {"authoritative_prediction_unchanged": True},
    }
    player_trace = {"schema_version": 2, "states": {"current_season_official": {"state": "ACTIVE"}}}
    native_trace = {
        "schema_version": 2,
        "model": "native_projection_feature_use_v1",
        "players": {"1": player_trace},
        "aggregate_feature_bundle": {"schema_version": 2, "states": {}},
        "unintegrated_features": ["current_form_enrichment"],
        "shadow_only_features": [],
        "available_only_features": ["current_form_enrichment"],
        "governance": {"telemetry_does_not_change_prediction_values": True},
    }

    monkeypatch.setattr(prediction_service, "build_full_core_enrichment", lambda *args, **kwargs: enrichment)
    monkeypatch.setattr(prediction_service, "resolve_prior", lambda *args, **kwargs: {})
    monkeypatch.setattr(prediction_service, "build_predictions", lambda *args, **kwargs: base)
    monkeypatch.setattr(prediction_service, "build_fixture_congestion_overlay", lambda *args, **kwargs: overlay)
    monkeypatch.setattr(prediction_service, "build_native_feature_trace", lambda *args, **kwargs: native_trace)
    monkeypatch.setattr(prediction_service, "evaluate_prediction_quality", lambda *args, **kwargs: {"status": "HEALTHY"})
    monkeypatch.setattr(prediction_service, "enrich_prediction", lambda prediction, full_enrichment: prediction)

    out = prediction_service.handle(
        "build",
        {
            "bootstrap": {"elements": []},
            "fixtures": [],
            "rules": {"goal_points": {}, "clean_sheet_points": {}},
            "planning_gw": 2,
        },
    )

    assert out["players"][0]["fixture_congestion_overlay"] == player_overlay
    assert out["players"][0]["feature_use"] == player_trace
    assert out["fixture_congestion_overlay"]["application_mode"] == "SHADOW_ONLY"
    assert "players" not in out["fixture_congestion_overlay"]
    assert out["native_feature_use"]["model"] == "native_projection_feature_use_v1"
    assert "players" not in out["native_feature_use"]
    assert out["native_feature_use"]["unintegrated_features"] == ["current_form_enrichment"]
    assert "native_authoritative_feature_trace" in out["capabilities"]
    assert "fixture_specific_congestion_shadow" in out["capabilities"]
