from __future__ import annotations

from src.v5.intelligence.full_core_enrichment import build_full_core_enrichment
from src.v5.sources import api_football


def _bootstrap():
    return {
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
        "elements": [{
            "id": 10, "web_name": "Player", "first_name": "Test", "second_name": "Player",
            "form": "4.0", "points_per_game": "4.0", "total_points": 8, "starts": 2, "minutes": 180,
            "expected_goals": "0.5", "expected_assists": "0.3", "threat": "100", "creativity": "80",
            "transfers_in_event": 100, "transfers_out_event": 20,
        }],
    }


def test_api_football_missing_secret_is_fail_neutral(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    result = api_football.collect(_bootstrap())
    assert result["status"] == "UNAVAILABLE"
    assert result["availability_class"] == "CREDENTIAL_MISSING"
    assert result["reason"] == "API_KEY_MISSING"
    assert result["governance"]["missing_is_unavailable_not_zero"] is True


def test_api_football_plan_restriction_is_classified_and_cached(monkeypatch, tmp_path):
    cfg = {
        "enabled": True,
        "base_url": "https://example.invalid",
        "api_key_env": "API_FOOTBALL_KEY",
        "api_key_header": "x-apisports-key",
        "timeout_seconds": 1.0,
        "cache_ttl_seconds": 3600,
        "availability_cache_ttl_seconds": 3600,
        "cache_dir": str(tmp_path),
        "resolve_league_ids_dynamically": True,
        "availability_classification": {
            "PLAN_RESTRICTED": {
                "contains_any": ["do not have access to this season"]
            }
        },
        "cacheable_unavailability_classes": ["PLAN_RESTRICTED"],
        "team_matching": {
            "minimum_similarity": 0.72,
            "minimum_unique_margin": 0.08,
            "include_official_short_name": True,
        },
        "competitions": {"uefa_champions_league": ["Champions League"]},
        "fixture_window_days_before": 14,
        "fixture_window_days_after": 60,
        "max_competition_requests_per_refresh": 1,
        "rate_limit_headers": {"remaining": [], "limit": []},
        "international": {},
    }
    monkeypatch.setattr(api_football, "load_json_config", lambda _: {"api_football": cfg})
    monkeypatch.setattr(
        api_football,
        "season_authority",
        lambda: {"season": "2026/27", "start_year": 2026, "authority": "Official FPL"},
    )
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")

    calls = {"count": 0}

    def plan_restricted(*args, **kwargs):
        calls["count"] += 1
        raise RuntimeError(
            "API-Football errors: {'plan': 'Free plans do not have access to this season, try from 2022 to 2024.'}"
        )

    monkeypatch.setattr(api_football, "_resolve_league", plan_restricted)
    first = api_football.collect(_bootstrap())
    assert first["status"] == "UNAVAILABLE"
    assert first["availability_class"] == "PLAN_RESTRICTED"
    assert first["governance"]["fail_neutral"] is True
    assert first["observability"]["credential_present"] is True
    assert first["observability"]["competitions_attempted"] == 1
    assert calls["count"] == 1

    def should_not_call_provider(*args, **kwargs):
        raise AssertionError("cached plan restriction should suppress a repeated provider call")

    monkeypatch.setattr(api_football, "_resolve_league", should_not_call_provider)
    second = api_football.collect(_bootstrap())
    assert second["status"] == "UNAVAILABLE"
    assert second["availability_class"] == "PLAN_RESTRICTED"
    assert second["governance"]["cached_provider_restriction"] is True
    assert second["observability"]["availability_cache_hits"] == 1
    assert second["observability"]["cache_hits"] == 1
    assert second["observability"]["competitions_attempted"] == 1
    assert calls["count"] == 1


def test_full_core_keeps_fpl_core_insights_primary_for_box_touches():
    fusion = {
        "status": "ACTIVE",
        "sources": {
            "understat": {
                "status": "ACTIVE",
                "players": [{"player_name": "Test Player", "shots": "4", "xg": "1.2", "xa": "0.5", "key_passes": "3"}],
            },
            "api_football": {"status": "UNAVAILABLE", "fixtures": []},
        },
    }
    result = build_full_core_enrichment(_bootstrap(), [], source_fusion=fusion)
    advanced = result["advanced_stats"]
    assert advanced["governance"]["fpl_core_insights_primary"] is True
    assert advanced["governance"]["understat_challenger_only"] is True
    assert advanced["governance"]["shot_in_box_is_not_box_touch"] is True
    assert advanced["understat_identity_matches"] == 1


def test_missing_external_enrichment_does_not_disable_full_core():
    result = build_full_core_enrichment(_bootstrap(), [], source_fusion={"status": "UNAVAILABLE", "sources": {}})
    assert result["status"] == "ACTIVE"
    assert result["governance"]["missing_external_evidence_is_unavailable_not_zero"] is True
    assert "source_fusion" in result["capabilities"]
