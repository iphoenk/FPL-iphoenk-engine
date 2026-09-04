from __future__ import annotations

from src.runtime_v6 import adapters, normalizer, registry
from src.runtime_v6.http_client import AcquisitionClient

def test_registry_is_data_only_and_has_exact_27_sources():
    cfg = registry.load_registry()
    ids = tuple(row["id"] for row in cfg["sources"])
    assert ids == registry.EXPECTED_SOURCE_IDS
    assert len(ids) == 27
    assert cfg["policy"]["data_only"] is True
    assert cfg["policy"]["decision_authority"] == "NONE"
    assert cfg["policy"]["prediction_authority"] == "NONE"
    assert cfg["policy"]["optimizer_authority"] == "NONE"

def test_all_sources_are_hourly_checked_and_fail_isolated():
    cfg = registry.load_registry()
    assert cfg["cadence"]["schedule"] == "hourly"
    assert cfg["cadence"]["check_every_source_each_cycle"] is True
    assert cfg["policy"]["source_failures_are_isolated"] is True
    assert cfg["policy"]["preserve_last_good_on_failure"] is True

def test_secret_backed_source_without_secret_is_config_required(monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    cfg = registry.load_registry()
    source = registry.source_map(cfg)["sportmonks"]
    result = AcquisitionClient(cfg["policy"]).fetch(source, source["requests"][0])
    assert result["status"] == "CONFIG_REQUIRED"
    assert result["health"] == "AMBER"

def test_http_last_good_cache_survives_failure(monkeypatch):
    cfg = registry.load_registry()
    source = {"id": "example", "name": "Example", "category": "test", "adapter": "http", "critical": False, "requests": [{"id": "one", "url": "https://example.invalid", "expect": "json"}]}
    previous = {"data": {"one": {"request_id": "one", "status": "AVAILABLE", "sha256": "old", "json": {"value": 1}, "checked_at": "2026-09-04T00:00:00+00:00"}}}
    import requests
    def fail(*args, **kwargs):
        raise requests.RequestException("down")
    monkeypatch.setattr("src.runtime_v6.http_client.requests.get", fail)
    result = adapters.collect_http(source, AcquisitionClient({**cfg["policy"], "retry_attempts": 1}), previous)
    assert result["health"] == "AMBER"
    assert result["effective_state"] == "STALE_CACHE"
    assert result["data"]["one"]["json"] == {"value": 1}
    assert result["data"]["one"]["data_origin"] == "LAST_GOOD_CACHE"

def test_price_predictor_is_derived_only_from_official():
    source = {"id": "official_price_predictor", "name": "Official FPL Price Predictor", "category": "market", "adapter": "official_price_predictor", "critical": True, "independence_group": "official_fpl", "derived_from": "official_fpl.bootstrap", "fields": ["id", "web_name", "price_change_percent", "price_change_projections"]}
    official = {"official": {"bootstrap": {"elements": [{"id": 1, "web_name": "Example", "price_change_percent": 72.4, "price_change_projections": [{"offset": 0, "projected_percent": 101.2}]}]}}}
    result = adapters.collect_price_predictor(source, official)
    assert result["health"] == "GREEN"
    assert result["coverage"]["coverage_ratio"] == 1.0
    assert result["governance"]["source"] == "OFFICIAL_FPL"
    assert result["governance"]["ui_scraping"] is False

def test_canonical_identity_is_official_fpl():
    official = {"official": {"bootstrap": {"elements": [{"id": 42, "code": 123, "web_name": "Player", "first_name": "Test", "second_name": "Player", "team": 1, "element_type": 3, "status": "a"}]}, "fixtures": [{"id": 9, "event": 2, "kickoff_time": "2026-09-01T15:00:00Z", "team_h": 1, "team_a": 2, "finished": False, "started": False}]}}
    players = normalizer.build_canonical_players(official, list(registry.EXPECTED_SOURCE_IDS))
    assert players["players"][0]["canonical_player_id"] == "fpl:42"
    assert players["players"][0]["official_fpl_element_id"] == 42
    assert players["players"][0]["identity_authority"] == "official_fpl"

def test_lineage_groups_correlated_opta_paths():
    cfg = registry.load_registry()
    lineage = normalizer.build_lineage_catalog(cfg)
    assert set(lineage["groups"]["opta_family"]) == {"opta_the_analyst", "fbref", "whoscored"}
