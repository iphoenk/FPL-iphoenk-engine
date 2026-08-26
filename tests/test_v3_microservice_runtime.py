import json
from pathlib import Path

from src.runtime_v3.orchestrator import _expand_args, _load_registry, _merge_latest, _validate_dag
from src.sources import official_fpl


def test_v3_runtime_registry_is_dependency_aware_and_coarse_grained():
    registry = _load_registry()
    _validate_dag(registry)
    assert registry["schema_version"] >= 5
    assert registry["architecture"] == "V3_BOUNDED_PROCESS_MICROSERVICES"
    assert registry["policy"]["parallelize_independent_services"] is True
    assert registry["policy"]["latest_json_single_writer_during_fan_in"] is True
    assert registry["policy"]["raw_optimizer_is_not_final_decision"] is True
    assert registry["policy"]["postflight_gate0_requires_governed_lineup_and_package"] is True
    assert registry["policy"]["mechanical_validity_is_not_prediction_quality"] is True
    assert registry["policy"]["two_layer_report_contract"] is True
    assert registry["policy"]["full_dss_watchlist_generator"] is True
    services = registry["services"]
    assert set(services) == {
        "collector", "price", "historical_prior", "prediction", "authenticated_official", "rules",
        "official_detail", "prediction_evaluation", "lineup_governance", "challenger", "governance",
        "watchlist", "reporting",
    }
    assert services["price"]["depends_on"] == ["collector"]
    assert services["historical_prior"]["depends_on"] == ["collector"]
    assert services["prediction"]["depends_on"] == ["historical_prior"]
    assert services["official_detail"]["depends_on"] == ["price"]
    assert services["prediction_evaluation"]["depends_on"] == ["prediction"]
    assert services["lineup_governance"]["depends_on"] == ["prediction"]
    assert services["challenger"]["depends_on"] == ["prediction_evaluation"]
    assert set(services["governance"]["depends_on"]) == {
        "price", "prediction", "authenticated_official", "rules", "official_detail",
        "prediction_evaluation", "lineup_governance", "challenger",
    }
    assert services["watchlist"]["depends_on"] == ["governance"]
    assert services["reporting"]["depends_on"] == ["watchlist"]
    commands = services["governance"]["commands"]
    assert any(c.get("module") == "src.engines.framework_health_audit" and "postflight" in c.get("args", []) for c in commands)
    assert any(c.get("module") == "src.engines.lineup_framework_health_overlay" for c in commands)
    assert any(c.get("module") == "src.engines.decision_quality_overlay" for c in commands)
    assert services["watchlist"]["commands"] == [
        {"module": "src.engines.dss_watchlist", "args": []},
        {"module": "src.engines.watchlist_public_sanitize", "args": []},
    ]
    assert services["reporting"]["commands"] == [
        {"module": "src.engines.report_architecture", "args": []},
        {"module": "src.engines.report_enrichment", "args": []},
    ]


def test_collector_cli_flags_are_registry_driven():
    args = _expand_args(["{mode}", "{stats}", "{deep_stats}"], {"mode": "deadline", "stats": "--stats", "deep_stats": ""})
    assert args == ["deadline", "--stats"]


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

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr(official_fpl.requests, "get", fake_get)
    first, h1 = official_fpl.get_json("bootstrap-static/", retries=1)
    second, h2 = official_fpl.get_json("bootstrap-static/", retries=1)
    assert first == second == {"ok": True}
    assert len(calls) == 1
    assert h1["cache_hit"] is False
    assert h2["cache_hit"] is True
    assert len(list(Path(tmp_path).glob("*.json"))) == 1
