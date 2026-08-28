import json
from pathlib import Path

from src.runtime_v3.orchestrator import _expand_args, _load_registry, _merge_latest, _validate_dag
from src.sources import official_fpl


def test_v3_runtime_registry_is_dependency_aware_and_artifact_owned():
    registry = _load_registry()
    _validate_dag(registry)
    assert registry["schema_version"] >= 13
    assert registry["architecture"] == "V3_BOUNDED_PROCESS_MICROSERVICES"
    policy = registry["policy"]
    for key in (
        "parallelize_independent_services", "generic_root_service_scheduling", "single_owner_for_standard_official_network_fetches",
        "latest_json_single_writer_during_base_fan_in", "service_boundaries_follow_artifact_ownership_not_file_size",
        "raw_optimizer_is_not_final_decision", "postflight_gate0_requires_governed_lineup_and_package",
        "mechanical_validity_is_not_prediction_quality", "two_layer_report_contract", "full_dss_watchlist_generator",
        "report_materializer_is_serving_only", "report_serving_requires_15_owned_and_20_external_watchlist",
        "source_registry_is_separate_infrastructure_layer", "official_fpl_remains_native_authority",
        "challenger_source_failure_does_not_block_decisions", "source_reachability_is_separate_from_capability_data_health",
        "version_neutral_service_entrypoints", "weather_enrichment_lives_inside_source_layer_not_new_microservice",
        "weather_is_observational_and_advisory_only", "weather_never_directly_mutates_xpts_or_decisions",
        "owned_report_rows_require_current_gw_xpts", "settled_prediction_validation_is_exposed_to_reports",
        "tactical_context_is_separate_bounded_evidence_service", "tactical_context_never_infers_missing_coach_style_or_recent_patterns",
    ):
        assert policy[key] is True, key

    services = registry["services"]
    assert len(services) == 21
    assert set(services) == {
        "official_snapshot", "rules", "team_state", "market_state", "live_state", "advanced_stats", "tactical_context", "base_snapshot",
        "historical_prior", "source_layer", "price", "prediction", "authenticated_official", "official_detail",
        "prediction_evaluation", "lineup_governance", "challenger", "governance", "watchlist", "reporting", "report_materializer",
    }
    assert "collector" not in services
    assert not any("weather" in name.lower() for name in services)
    assert services["official_snapshot"]["depends_on"] == []
    assert services["rules"]["depends_on"] == []
    assert services["team_state"]["depends_on"] == ["official_snapshot"]
    assert services["market_state"]["depends_on"] == ["official_snapshot"]
    assert services["live_state"]["depends_on"] == ["official_snapshot"]
    assert services["advanced_stats"]["depends_on"] == ["official_snapshot"]
    assert set(services["tactical_context"]["depends_on"]) == {"advanced_stats", "official_snapshot"}
    assert set(services["base_snapshot"]["depends_on"]) == {"official_snapshot", "team_state", "market_state", "live_state", "advanced_stats"}
    assert set(services["historical_prior"]["depends_on"]) == {"base_snapshot", "official_snapshot"}
    assert set(services["prediction"]["depends_on"]) == {"historical_prior", "official_snapshot", "tactical_context"}
    assert {"official_snapshot.json", "tactical_team_profiles.json", "player_role_profiles.json", "recent_tactical_form.json"} <= set(services["prediction"]["inputs"])
    assert set(services["source_layer"]["depends_on"]) == {"base_snapshot", "historical_prior", "official_snapshot"}
    assert "official_snapshot.json" in services["source_layer"]["inputs"]
    assert "fixture_weather.json" in services["source_layer"]["artifacts"]
    assert services["price"]["depends_on"] == ["base_snapshot", "source_layer"]
    assert set(services["official_detail"]["depends_on"]) == {"price", "official_snapshot"}
    assert set(services["prediction_evaluation"]["depends_on"]) == {"prediction", "official_snapshot"}
    assert services["lineup_governance"]["depends_on"] == ["prediction"]
    assert set(services["challenger"]["depends_on"]) == {"prediction_evaluation", "source_layer"}
    assert set(services["governance"]["depends_on"]) == {"source_layer", "price", "prediction", "authenticated_official", "rules", "official_detail", "prediction_evaluation", "lineup_governance", "challenger"}
    assert services["watchlist"]["depends_on"] == ["governance"]
    assert services["reporting"]["depends_on"] == ["watchlist"]
    assert set(services["report_materializer"]["depends_on"]) == {"reporting", "official_detail", "source_layer", "lineup_governance", "prediction_evaluation"}

    assert services["official_snapshot"]["commands"] == [{"module": "src.engines.official_snapshot_service", "args": []}]
    assert services["tactical_context"]["commands"] == [{"module": "src.engines.tactical_context_service", "args": []}]
    assert services["source_layer"]["commands"] == [{"module": "src.engines.source_layer", "args": []}]
    assert services["price"]["commands"] == [{"module": "src.engines.price_service", "args": []}]
    assert services["prediction"]["commands"] == [{"module": "src.engines.prediction_service", "args": []}]
    assert services["report_materializer"]["commands"] == [
        {"module": "src.engines.report_materializer", "args": []},
        {"module": "src.engines.report_transparency_overlay", "args": []},
        {"module": "src.engines.report_serving_validate", "args": []},
    ]
    for service in services.values():
        for command in service.get("commands") or []:
            assert "code" not in command
            assert command.get("module") != "src.engine"


def test_service_cli_flags_are_registry_driven():
    args = _expand_args(["{mode}", "{stats}", "{deep_stats}"], {"mode": "deadline", "stats": "--stats", "deep_stats": ""})
    assert args == ["deadline", "--stats"]
    deep = _expand_args(["{stats}", "{deep_stats}"], {"stats": "--stats", "deep_stats": "--deep-stats"})
    assert deep == ["--stats", "--deep-stats"]


def test_latest_fan_in_merges_only_owned_keys(tmp_path):
    canonical = tmp_path / "canonical"
    service = tmp_path / "service"
    canonical.mkdir(); service.mkdir()
    (canonical / "latest.json").write_text(json.dumps({"base": 1, "files": {"team": "data/team.json"}, "price_summary": {"old": True}}))
    (service / "latest.json").write_text(json.dumps({"base": 999, "price_summary": {"new": True}, "files": {"price_alerts": "data/price_alerts.json", "team": "bad"}}))
    _merge_latest(canonical, service, {"latest_keys": ["price_summary"], "latest_file_keys": ["price_alerts"]})
    merged = json.loads((canonical / "latest.json").read_text())
    assert merged["base"] == 1
    assert merged["price_summary"] == {"new": True}
    assert merged["files"]["team"] == "data/team.json"
    assert merged["files"]["price_alerts"] == "data/price_alerts.json"


def test_official_fpl_shared_cache_deduplicates_requests(monkeypatch, tmp_path):
    monkeypatch.setenv("FPL_HTTP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FPL_HTTP_CACHE_TTL_SECONDS", "60")
    calls = []

    class Response:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"ok": True}

    def fake_get(url, timeout, headers=None):
        calls.append((url, timeout, headers))
        return Response()

    monkeypatch.setattr(official_fpl.requests, "get", fake_get)
    first, h1 = official_fpl.get_json("bootstrap-static/", retries=1)
    second, h2 = official_fpl.get_json("bootstrap-static/", retries=1)
    assert first == second == {"ok": True}
    assert len(calls) == 1
    assert calls[0][2] and "User-Agent" in calls[0][2]
    assert h1["cache_hit"] is False
    assert h2["cache_hit"] is True
    assert len(list(Path(tmp_path).glob("*.json"))) == 1
