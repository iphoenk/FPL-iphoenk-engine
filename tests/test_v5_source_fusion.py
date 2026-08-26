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
    assert result["reason"] == "API_KEY_MISSING"
    assert result["governance"]["missing_is_unavailable_not_zero"] is True


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
