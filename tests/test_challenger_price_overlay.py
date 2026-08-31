from __future__ import annotations

from src.engines.price_challenger_overlay import apply_context
from src.engines.report_enrichment import _source_availability
from src.sources.observations import ChallengerObservation

NOW = "2026-08-26T21:00:00+00:00"


def _obs(source: str, direction: str, stale: bool = False, status: str = "AVAILABLE") -> dict:
    return ChallengerObservation(
        source_id=source,
        capability="price_prediction",
        value={"player": "Bowen", "direction": direction, "predicted_pct": 120.0},
        source_url="https://example.com/prices",
        fetched_at=NOW,
        observed_at=NOW,
        ttl_seconds=1800,
        parser_version="test-v1",
        subject={"player": "Bowen"},
        status=status,
        stale=stale,
    ).as_dict()


def test_price_overlay_is_context_only_and_preserves_official_fields():
    prices = {
        "players": [{"element": 1, "name": "Bowen", "now_cost": 78, "official_progress_pct": 59.1, "urgency": "HIGH"}],
        "top_rise_risk": [{"element": 1, "name": "Bowen", "now_cost": 78, "official_progress_pct": 59.1, "urgency": "HIGH"}],
    }
    observations = {
        "observations": [_obs("fffix", "RISE"), _obs("onefpl", "RISE")],
        "cross_source": [{"subject_key": "bowen", "player": "Bowen", "capability": "price_prediction", "state": "AGREEMENT", "providers": ["fffix", "onefpl"], "directions": ["RISE"]}],
    }
    enriched, summary = apply_context(prices, observations)
    row = enriched["players"][0]
    assert row["now_cost"] == 78
    assert row["official_progress_pct"] == 59.1
    assert row["urgency"] == "HIGH"
    assert row["challenger_price_context"]["state"] == "AGREEMENT"
    assert row["challenger_price_context"]["official_fields_overridden"] is False
    assert summary["matched_player_count"] == 1
    assert summary["official_fields_overridden"] is False


def test_price_overlay_ignores_stale_observation():
    stale = _obs("fffix", "RISE")
    stale["status"] = "STALE"
    stale["stale"] = True
    prices = {"players": [{"element": 1, "name": "Bowen", "now_cost": 78}]}
    enriched, summary = apply_context(prices, {"observations": [stale], "cross_source": []})
    assert "challenger_price_context" not in enriched["players"][0]
    assert summary["fresh_observation_count"] == 0


def test_user_source_availability_excludes_retired_livefpl_and_keeps_supported_challengers():
    source_health = {
        "sources": [
            {"id": "livefpl", "name": "LiveFPL", "status": "LIVE", "reachable": True},
            {"id": "onefpl", "name": "OneFPL", "status": "DISABLED", "reachable": False},
            {"id": "fffix", "name": "FFFix", "status": "LIVE", "reachable": True},
        ],
        "capability_health": [
            {"source_id": "livefpl", "capability": "price_prediction", "data_state": "AVAILABLE", "fresh_observations": 5},
            {"source_id": "onefpl", "capability": "price_prediction", "data_state": "DISABLED", "fresh_observations": 0},
            {"source_id": "fffix", "capability": "price_prediction", "data_state": "AVAILABLE", "fresh_observations": 2},
        ],
    }
    rendered = _source_availability(source_health)
    ids = {row["source_id"] for row in rendered["collector_challenger"]}
    assert "livefpl" not in ids
    assert "onefpl" in ids
    assert "fffix" in ids
    assert "livefpl" not in str(rendered).lower()
    assert "onefpl" in rendered["report_time"]
    assert "market momentum" in rendered["report_time"]["onefpl"]