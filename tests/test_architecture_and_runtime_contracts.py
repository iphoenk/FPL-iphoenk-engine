import json
from pathlib import Path

import pytest

from src.engines import price_radar
from src.engines.refresh_policy import load_policy as load_refresh_policy
from src.engines.snapshot_meta import snapshot_id, changes
from src.runtime_v3.artifact_contracts import validate_artifact
from src.runtime_v3.orchestrator import (
    _attempt_promotion,
    _expand_args,
    _load_registry,
    _merge_latest,
    _validate_dag,
)
from src.settings import PROJECTION_HORIZON_GWS, STRATEGIC_HORIZON_GWS, TEAM_ID
from src.sources import official_fpl
from src.utils import atomic_json
from src.version import ENGINE_VERSION, SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_projection_horizons_are_owned_by_engine_config():
    engine = _json("config/engine.json")
    assert PROJECTION_HORIZON_GWS == int(engine["projection_horizon_gws"])
    assert STRATEGIC_HORIZON_GWS == int(engine["strategic_horizon_gws"])
    assert STRATEGIC_HORIZON_GWS >= PROJECTION_HORIZON_GWS
    service = (ROOT / "src/engines/prediction_service.py").read_text(encoding="utf-8")
    assert "horizon=15" not in service
    assert "STRATEGIC_HORIZON_GWS" in service


def test_price_radar_runtime_policy_is_registry_driven():
    policy = _json("config/intelligence/price_radar.json")
    market = policy["market_filter"]
    serving = policy["serving"]
    assert price_radar.MIN_OWNERSHIP_PCT == float(market["minimum_ownership_pct"])
    assert price_radar.MIN_ABS_NET == int(market["minimum_abs_net_transfers"])
    assert price_radar.HIGH_NET == int(market["high_confidence_abs_net_transfers"])
    assert price_radar.MAX_MARKET_WATCH == int(serving["market_watch_capacity"])
    source = (ROOT / "src/engines/price_radar.py").read_text(encoding="utf-8")
    for snippet in ("MIN_OWNERSHIP_PCT = 0.5", "MIN_ABS_NET = 5_000", "HIGH_NET = 25_000", "MAX_MARKET_WATCH = 50"):
        assert snippet not in source


def test_refresh_policy_is_config_owned():
    policy = load_refresh_policy()
    assert policy == _json("config/intelligence/refresh_policy.json")
    source = (ROOT / "src/engines/refresh_policy.py").read_text(encoding="utf-8")
    assert "if hours<=1: return 10" not in source
    assert "if hours<=4: return 15" not in source


def test_framework_registry_expected_counts_are_declared_by_registries():
    specs = {
        "config/dss_core_registry.json": ("modules", 50),
        "config/dss_extension_registry.json": ("modules", 16),
        "config/enhancement_layers_registry.json": ("layers", 8),
        "config/gate0_registry.json": ("checks", 16),
    }
    for path, (rows_key, expected) in specs.items():
        payload = _json(path)
        assert int(payload["expected_count"]) == expected
        assert len(payload[rows_key]) == int(payload["expected_count"])


def test_active_service_registry_uses_version_neutral_module_entrypoints():
    registry = _json("config/v3_service_registry.json")
    assert registry["schema_version"] >= 9
    assert registry["policy"]["version_neutral_service_entrypoints"] is True
    assert registry["policy"]["inline_python_service_commands_forbidden"] is True
    assert registry["services"]["prediction"]["commands"] == [{"module": "src.engines.prediction_service", "args": []}]
    assert registry["services"]["price"]["commands"] == [{"module": "src.engines.price_service", "args": []}]
    for service in registry["services"].values():
        for command in service.get("commands") or []:
            assert "code" not in command
            module = str(command.get("module") or "")
            assert "decision_intelligence_v313" not in module


def test_optimizer_random_seed_is_not_user_identity():
    optimizer = _json("config/intelligence/package_optimizer.json")
    assert int(optimizer["monte_carlo_seed"]) != TEAM_ID
    assert "independent of user/team identity" in optimizer["monte_carlo_seed_policy"]


def _valid_observations() -> dict:
    return {
        "schema_version": 2,
        "contract": "challenger_observation_v2",
        "generated_at": "2026-08-27T00:00:00+00:00",
        "observations": [],
        "counts": {"fresh": 0, "cached_last_known_good": 0, "stale": 0, "legacy": 0},
        "cross_source": [],
        "policy": {},
    }


def test_generic_declared_json_must_parse(tmp_path):
    path = tmp_path / "generic.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="malformed JSON artifact"):
        validate_artifact(path, "generic.json")


def test_challenger_observations_wrong_contract_is_integrity_failure(tmp_path):
    path = tmp_path / "challenger_observations.json"
    payload = _valid_observations()
    payload["contract"] = "wrong-contract"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="contract.*mismatch"):
        validate_artifact(path, "challenger_observations.json")


def test_challenger_observations_valid_empty_is_allowed(tmp_path):
    path = tmp_path / "challenger_observations.json"
    path.write_text(json.dumps(_valid_observations()), encoding="utf-8")
    result = validate_artifact(path, "challenger_observations.json")
    assert result["validation"] == "CONTRACT_VALID"


def test_malformed_isolated_artifact_fails_before_promotion(tmp_path):
    service_dir = tmp_path / "service"
    canonical = tmp_path / "canonical"
    service_dir.mkdir()
    canonical.mkdir()
    (service_dir / "bad.json").write_text("[broken", encoding="utf-8")
    spec = {"critical": True, "isolated": True, "inputs": [], "artifacts": ["bad.json"], "latest_keys": [], "latest_file_keys": []}
    result = {"service": "bad", "status": "SUCCESS", "isolated": True, "data_dir": str(service_dir), "elapsed_ms": 1.0, "commands": []}
    accepted = _attempt_promotion("bad", result, spec, canonical)
    assert accepted["status"] == "FAILED"
    assert accepted["failure_stage"] == "artifact_validation"
    assert not (canonical / "bad.json").exists()


def test_malformed_nonisolated_artifact_also_fails_contract(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "bad.json").write_text("{broken", encoding="utf-8")
    spec = {"critical": True, "isolated": False, "inputs": [], "artifacts": ["bad.json"], "latest_keys": [], "latest_file_keys": []}
    result = {"service": "bad", "status": "SUCCESS", "isolated": False, "data_dir": str(canonical), "elapsed_ms": 1.0, "commands": []}
    accepted = _attempt_promotion("bad", result, spec, canonical)
    assert accepted["status"] == "FAILED"
    assert accepted["failure_stage"] == "artifact_validation"


def test_decision_brief_is_compact_without_changing_json_semantics(tmp_path):
    brief = tmp_path / "decision_brief.json"
    other = tmp_path / "other.json"
    payload = {"owned_15": [{"element": 1, "name": "Player"}], "watchlist_20": {"GK": []}}
    atomic_json(brief, payload)
    atomic_json(other, payload)
    brief_text = brief.read_text(encoding="utf-8")
    other_text = other.read_text(encoding="utf-8")
    assert json.loads(brief_text) == payload
    assert json.loads(other_text) == payload
    assert "\n" not in brief_text
    assert len(brief_text.encode("utf-8")) < len(other_text.encode("utf-8"))


def test_runtime_registry_declares_artifact_integrity_policy():
    registry = _json("config/v3_service_registry.json")
    contracts = _json("config/runtime/artifact_contracts.json")
    assert registry["schema_version"] >= 12
    assert registry["policy"]["declared_json_artifacts_are_validated_before_acceptance"] is True
    assert registry["policy"]["malformed_internal_artifact_is_integrity_failure"] is True
    assert contracts["contracts"]["challenger_observations.json"]["equals"]["contract"] == "challenger_observation_v2"


def test_release_metadata_shape():
    parts = ENGINE_VERSION.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
    assert int(parts[0]) == 3
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION > 0


def test_snapshot_id_stable():
    assert snapshot_id({"b": 2, "a": 1}) == snapshot_id({"a": 1, "b": 2})


def test_change_log():
    assert changes({"rank": 10}, {"rank": 9}, ["rank"]) == [{"field": "rank", "old": 10, "new": 9}]


def test_price_noise_filter():
    assert price_radar.classify(1000, 0.1, 100)["confidence"] == "NOISE"
    assert price_radar.classify(30000, 2.0, 100000)["confidence"] == "HIGH"


def test_runtime_registry_is_dependency_aware_and_artifact_owned():
    registry = _load_registry()
    _validate_dag(registry)
    assert registry["schema_version"] >= 15
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
        "tactical_context_is_separate_bounded_evidence_service", "tactical_context_never_infers_missing_coach_style_or_true_pressing",
        "tactical_context_rolling_history_is_service_owned", "required_core_and_optional_private_enrichment_are_distinct",
        "optional_private_enrichment_never_blocks_required_core",
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
    assert {"official_snapshot.json", "player_features.json", "stats/shots_current.json", "stats/playermatchstats_current.json", "recent_tactical_form.json"} <= set(services["tactical_context"]["inputs"])
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
    assert set(services["governance"]["depends_on"]) == {"source_layer", "price", "prediction", "rules", "official_detail", "prediction_evaluation", "lineup_governance", "challenger"}
    assert services["authenticated_official"]["critical"] is False
    assert services["authenticated_official"]["criticality_class"] == "OPTIONAL_PRIVATE_ENRICHMENT"
    assert services["authenticated_official"]["failure_policy"] == "FAIL_SOFT"
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
    canonical.mkdir()
    service.mkdir()
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
