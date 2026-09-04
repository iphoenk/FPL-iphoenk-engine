from __future__ import annotations

from pathlib import Path

from src.runtime_v6 import adapters, normalizer, registry
from src.runtime_v6.http_client import AcquisitionClient


def test_registry_is_data_only_and_registry_driven():
    cfg = registry.load_registry()
    ids = tuple(row["id"] for row in cfg["sources"])
    activation = cfg["activation"]

    assert ids == registry.EXPECTED_SOURCE_IDS
    assert len(ids) == activation["active_source_count"]
    assert activation["base_source_count"] == len(registry.BASE_SOURCE_IDS)
    assert activation["disabled_source_count"] == len(registry.DROPPED_SOURCE_IDS)
    assert activation["reference_only_source_count"] == len(registry.REFERENCE_ONLY_SOURCE_IDS)
    assert set(ids).isdisjoint(registry.DROPPED_SOURCE_IDS)
    assert set(ids).isdisjoint(registry.REFERENCE_ONLY_SOURCE_IDS)
    assert cfg["policy"]["data_only"] is True
    assert cfg["policy"]["decision_authority"] == "NONE"
    assert cfg["policy"]["prediction_authority"] == "NONE"
    assert cfg["policy"]["optimizer_authority"] == "NONE"


def test_all_active_sources_are_fail_isolated_and_concurrent():
    cfg = registry.load_registry()
    assert cfg["cadence"]["schedule"] == "hourly"
    assert cfg["cadence"]["check_every_source_each_cycle"] is True
    assert cfg["policy"]["source_failures_are_isolated"] is True
    assert cfg["policy"]["preserve_last_good_on_failure"] is True
    assert cfg["policy"]["source_workers"] >= 12
    assert cfg["policy"]["request_workers"] >= 2
    assert cfg["policy"]["conditional_revalidation"] is True


def test_dropped_and_reference_only_sources_never_enter_active_source_map():
    cfg = registry.load_registry()
    sources = registry.source_map(cfg)
    for source_id in registry.DROPPED_SOURCE_IDS:
        assert source_id not in sources
    for source_id in registry.REFERENCE_ONLY_SOURCE_IDS:
        assert source_id not in sources
    assert "fffix" in registry.REFERENCE_ONLY_SOURCE_IDS
    assert "ffhub" in registry.REFERENCE_ONLY_SOURCE_IDS
    assert "clubelo" in registry.REFERENCE_ONLY_SOURCE_IDS


def test_free_source_expansion_is_registered_with_safe_tiers():
    cfg = registry.load_registry()
    sources = registry.source_map(cfg)

    assert sources["solio_analytics"]["source_tier"] == "core"
    assert sources["solio_analytics"]["acquisition_kind"] == "rest_json"
    assert sources["open_meteo_weather"]["source_tier"] == "core"
    assert sources["open_meteo_weather"]["poll_interval_minutes"] == 60
    assert len(sources["open_meteo_weather"]["venues"]) == 20
    assert sources["open_meteo_weather"]["weather_contract"]["direct_xpts_multiplier"] is False
    assert sources["open_meteo_weather"]["weather_contract"]["weather_alone_can_trigger_transfer"] is False
    assert sources["check_the_chance"]["source_tier"] == "pilot"
    assert sources["fantasy_football_pundit"]["source_tier"] == "pilot"
    assert set(registry.REFERENCE_ONLY_SOURCE_IDS) == {
        "fffix",
        "ffhub",
        "clubelo",
        "bbc_team_news",
        "premier_injuries",
        "fpl_form",
        "fpl_review_free",
    }


def test_http_last_good_cache_survives_failure(monkeypatch):
    cfg = registry.load_registry()
    source = {
        "id": "example",
        "name": "Example",
        "category": "test",
        "adapter": "http",
        "critical": False,
        "requests": [{"id": "one", "url": "https://example.invalid", "expect": "json"}],
    }
    previous = {
        "data": {
            "one": {
                "request_id": "one",
                "status": "AVAILABLE",
                "sha256": "old",
                "json": {"value": 1},
                "checked_at": "2026-09-04T00:00:00+00:00",
            }
        }
    }

    import requests

    def fail(*args, **kwargs):
        raise requests.RequestException("down")

    monkeypatch.setattr("src.runtime_v6.http_client.AcquisitionClient._session", lambda self: type("S", (), {"get": fail})())
    result = adapters.collect_http(
        source,
        AcquisitionClient({**cfg["policy"], "retry_attempts": 1}),
        previous,
    )
    assert result["health"] == "AMBER"
    assert result["effective_state"] == "STALE_CACHE"
    assert result["data"]["one"]["json"] == {"value": 1}
    assert result["data"]["one"]["data_origin"] == "LAST_GOOD_CACHE"


def test_conditional_not_modified_is_green_and_revalidated():
    source = {
        "id": "example",
        "name": "Example",
        "category": "test",
        "adapter": "http",
        "critical": False,
        "requests": [{"id": "one", "url": "https://example.invalid", "expect": "json"}],
    }
    previous = {
        "data": {
            "one": {
                "request_id": "one",
                "status": "AVAILABLE",
                "sha256": "old",
                "etag": "\"abc\"",
                "json": {"value": 1},
                "checked_at": "2026-09-04T00:00:00+00:00",
            }
        }
    }

    class FakeClient:
        request_workers = 2
        conditional_revalidation = True

        def fetch(self, source, request_cfg, *, previous=None):
            return {
                "request_id": request_cfg["id"],
                "status": "NOT_MODIFIED",
                "health": "GREEN",
                "checked_at": "2026-09-04T03:00:00+00:00",
                "content_changed": False,
                "etag": "\"abc\"",
            }

    result = adapters.collect_http(source, FakeClient(), previous)
    assert result["health"] == "GREEN"
    assert result["effective_state"] == "LIVE_UNCHANGED"
    assert result["data"]["one"]["json"] == {"value": 1}
    assert result["data"]["one"]["data_origin"] == "REVALIDATED_CACHE"
    assert result["coverage"]["revalidated_not_modified"] == 1


def test_price_predictor_is_derived_only_from_official():
    source = {
        "id": "official_price_predictor",
        "name": "Official FPL Price Predictor",
        "category": "market",
        "adapter": "official_price_predictor",
        "critical": True,
        "independence_group": "official_fpl",
        "derived_from": "official_fpl.bootstrap",
        "fields": ["id", "web_name", "price_change_percent", "price_change_projections"],
    }
    official = {
        "health": "GREEN",
        "effective_state": "LIVE_UNCHANGED",
        "official": {
            "bootstrap": {
                "elements": [
                    {
                        "id": 1,
                        "web_name": "Example",
                        "price_change_percent": 72.4,
                        "price_change_projections": [{"offset": 0, "projected_percent": 101.2}],
                    }
                ]
            }
        },
    }
    result = adapters.collect_price_predictor(source, official)
    assert result["health"] == "GREEN"
    assert result["coverage"]["coverage_ratio"] == 1.0
    assert result["governance"]["source"] == "OFFICIAL_FPL"
    assert result["governance"]["ui_scraping"] is False


def test_price_predictor_inherits_cached_official_degradation():
    source = {
        "id": "official_price_predictor",
        "name": "Official FPL Price Predictor",
        "category": "market",
        "adapter": "official_price_predictor",
        "critical": True,
        "independence_group": "official_fpl",
        "derived_from": "official_fpl.bootstrap",
        "fields": ["id", "web_name", "price_change_percent", "price_change_projections"],
    }
    official = {
        "health": "AMBER",
        "effective_state": "STALE_CACHE",
        "official": {
            "bootstrap": {
                "elements": [
                    {
                        "id": 1,
                        "web_name": "Example",
                        "price_change_percent": 72.4,
                        "price_change_projections": [],
                    }
                ]
            }
        },
    }
    result = adapters.collect_price_predictor(source, official)
    assert result["health"] == "AMBER"
    assert result["effective_state"] == "CACHED_DERIVED"


def test_canonical_identity_is_official_fpl():
    official = {
        "official": {
            "bootstrap": {
                "elements": [
                    {
                        "id": 42,
                        "code": 123,
                        "web_name": "Player",
                        "first_name": "Test",
                        "second_name": "Player",
                        "team": 1,
                        "element_type": 3,
                        "status": "a",
                    }
                ]
            },
            "fixtures": [
                {
                    "id": 9,
                    "event": 2,
                    "kickoff_time": "2026-09-01T15:00:00Z",
                    "team_h": 1,
                    "team_a": 2,
                    "finished": False,
                    "started": False,
                }
            ],
        }
    }
    players = normalizer.build_canonical_players(official, list(registry.EXPECTED_SOURCE_IDS))
    assert players["players"][0]["canonical_player_id"] == "fpl:42"
    assert players["players"][0]["official_fpl_element_id"] == 42
    assert players["players"][0]["identity_authority"] == "official_fpl"


def test_lineage_reflects_only_active_opta_family_paths():
    cfg = registry.load_registry()
    lineage = normalizer.build_lineage_catalog(cfg)
    assert set(lineage["groups"]["opta_family"]) == {"opta_the_analyst"}


def test_workflow_hydrates_runtime_last_good_before_collection():
    workflow = Path(".github/workflows/v6-hourly-data-ingestion.yml").read_text(encoding="utf-8")
    hydrate = workflow.index("Hydrate previous V6 last-good snapshot")
    collect = workflow.index("Run active V6 acquisition cycle")
    assert hydrate < collect
    assert 'git archive "origin/${RUNTIME_BRANCH}" data/v6' in workflow


def test_workflow_does_not_inject_dropped_paid_provider_secrets_or_hardcode_source_count():
    workflow = Path(".github/workflows/v6-hourly-data-ingestion.yml").read_text(encoding="utf-8")
    assert "SPORTMONKS_API_TOKEN" not in workflow
    assert "API_FOOTBALL_KEY" not in workflow
    assert "FOOTBALL_DATA_ORG_TOKEN" not in workflow
    assert 'manifest["source_count"] == 20' not in workflow
    assert 'registry["activation"]["active_source_count"]' in workflow


def test_workflow_force_adds_ignored_runtime_snapshot():
    workflow = Path(".github/workflows/v6-hourly-data-ingestion.yml").read_text(encoding="utf-8")
    assert "git add -f data/v6" in workflow
    assert "git add data/v6" not in workflow
