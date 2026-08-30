from datetime import datetime, timedelta, timezone

import pytest

from src.v5.intelligence.weather_advisory import (
    assert_advisory_governance,
    classify_weather,
    select_evidence,
)
from src.v5.intelligence.weather_research import (
    build_weather_research,
    promotion_gate,
    research_state,
    retain_observed_effects,
)


def test_v5_weather_is_shadow_advisory_only():
    assert_advisory_governance()
    out = classify_weather({
        "source_kind": "LIVE_OBSERVED",
        "evidence_state": "LIVE_OBSERVED",
        "weather": {
            "temperature_c": 18,
            "precipitation_probability_pct": 90,
            "precipitation_mm_h": 6.0,
            "wind_speed_kmh": 24,
            "wind_gust_kmh": 40,
        },
    })
    assert out["severity"] == "ADVERSE"
    assert out["mode"] == "SHADOW_ADVISORY_ONLY"
    assert out["decision_effect"] == "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION"
    assert out["governance"]["v5_production_decision_authority"] is False
    assert out["governance"]["quantitative_weather_signal_consumption"] is False
    assert out["governance"]["may_directly_change_xpts"] is False
    assert out["governance"]["may_directly_change_captaincy"] is False
    assert out["governance"]["may_directly_change_transfer_decision"] is False


def test_v5_rain_probability_alone_is_not_intensity():
    out = classify_weather({"weather": {"precipitation_probability_pct": 100, "precipitation_mm_h": 0.0}})
    assert out["severity"] == "NORMAL"
    assert "precipitation_intensity" not in out["signals"]


def test_weather_evidence_precedence_live_then_closest_then_forecast():
    now = datetime.now(timezone.utc)
    forecast = {
        "fetched_at": now.isoformat(),
        "forecast_confidence": "HIGH",
        "weather": {"precipitation_mm_h": 1.0},
    }
    closest = {"observed_at": (now - timedelta(minutes=15)).isoformat(), "weather": {"precipitation_mm_h": 2.0}}
    live = {"observed_at": now.isoformat(), "weather": {"precipitation_mm_h": 3.0}}
    selected = select_evidence(
        live_observation=live,
        closest_to_kickoff_observation=closest,
        forecast_snapshots=[forecast],
        now=now,
    )
    assert selected["evidence_kind"] == "LIVE_OBSERVED"
    selected = select_evidence(
        closest_to_kickoff_observation=closest,
        forecast_snapshots=[forecast],
        now=now,
    )
    assert selected["evidence_kind"] == "CLOSEST_TO_KICKOFF_OBSERVATION"
    selected = select_evidence(forecast_snapshots=[forecast], now=now)
    assert selected["evidence_kind"] == "FRESH_FORECAST"


def test_observed_effects_require_reliable_evidence_and_never_claim_weather_caused():
    retained = retain_observed_effects({
        "slips": {"value": 2, "reliability": "HIGH", "source": "verified_event_review"},
        "handling_errors": {"value": 1, "reliability": "LOW", "source": "uncorroborated"},
    })
    assert retained["slips"]["attribution"] == "POSSIBLE_CONTRIBUTING_FACTOR"
    assert "handling_errors" not in retained
    assert "WEATHER_CAUSED" not in str(retained)


def test_research_controls_and_candidate_signals_are_shadow_only():
    research = build_weather_research([])
    assert research["state"] == "INSUFFICIENT_SAMPLE"
    assert {
        "opponent_strength",
        "tactical_change",
        "venue",
        "red_cards",
        "injury",
        "rotation",
        "role_change",
        "game_state",
        "sample_noise",
    }.issubset(set(research["confounders"]))
    assert {
        "position",
        "player_archetype",
        "team_system",
        "opponent_system",
        "competitive_load_rest",
    }.issubset(set(research["interactions"]))
    for signal in research["candidate_signals"].values():
        assert signal["quantitative_modifier"] is None
        assert signal["promotion_gate"]["eligible"] is False


def test_validated_candidate_still_cannot_promote_without_explicit_governance():
    cohort = {
        "weather_matches": 100,
        "matched_controls": 100,
        "distinct_venues": 10,
        "distinct_gameweeks": 10,
    }
    validation = {
        "repeatability": True,
        "out_of_sample_validation": True,
        "calibration_improvement": True,
        "non_regression": True,
    }
    state = research_state(cohort, validation)
    assert state == "VALIDATED_CANDIDATE"
    gate = promotion_gate(state, validation)
    assert gate["eligible"] is False
    assert gate["checks"]["explicit_governance_authorization"] is False
    assert gate["current_authority"] == "SHADOW_ADVISORY_ONLY"


def test_sustainability_keeps_return_event_and_repeatability_separate():
    research = build_weather_research([{
        "fixture_id": 99,
        "sustainability": {
            "actual_fpl_return": {"points": 8},
            "opportunity_quality": {"xg": 0.12},
            "weather_associated_event": {"type": "opponent_slip"},
            "future_repeatability": "UNPROVEN",
        },
    }])
    row = research["sustainability"]["99"]
    assert row["actual_fpl_return"] == {"points": 8}
    assert row["opportunity_quality"] == {"xg": 0.12}
    assert row["future_repeatability"] == "UNPROVEN"
    assert row["governance"]["opponent_slip_goal_does_not_raise_attacking_rate_by_itself"] is True


def test_weather_source_health_partial_when_forecast_exists_but_observation_is_missing(monkeypatch):
    from src.v5.sources import weather as source

    now = datetime.now(timezone.utc)
    kickoff = now + timedelta(hours=2)
    monkeypatch.setattr(source, "_fetch_forecast", lambda venue, ko, current: {
        "provider": "test",
        "fetched_at": current.isoformat(),
        "forecast_for": ko.isoformat(),
        "forecast_confidence": "HIGH",
        "source_kind": "FRESH_FORECAST",
        "evidence_state": "FORECAST",
        "freshness": "FRESH",
        "severity": "ADVERSE",
        "signals": ["precipitation_intensity"],
        "weather": {
            "temperature_c": 15,
            "precipitation_probability_pct": 90,
            "precipitation_mm_h": 5,
            "wind_speed_kmh": 20,
            "wind_gust_kmh": 30,
            "weather_code": 61,
        },
    })
    bootstrap = {"teams": [{"id": 1, "name": "Arsenal"}, {"id": 2, "name": "Aston Villa"}]}
    fixtures = [{
        "id": 10,
        "event": 2,
        "team_h": 1,
        "team_a": 2,
        "kickoff_time": kickoff.isoformat(),
        "started": False,
        "finished": False,
    }]
    out = source.collect(bootstrap, fixtures, previous={})
    assert out["weather_context_status"] in {"PASS", "PARTIAL"}
    assert out["fixtures"][0]["forecast_snapshots"]
    assert out["fixtures"][0]["live_observation"] is None
    assert out["governance"]["decision_effect"] == "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION"


def test_source_fusion_wires_weather_as_runtime_enrichment(monkeypatch):
    from src.v5.sources import fusion

    monkeypatch.setattr(fusion, "read_artifact", lambda name, default=None: {})
    monkeypatch.setattr(fusion, "collect_understat", lambda: {"status": "ACTIVE", "players": []})
    monkeypatch.setattr(fusion, "collect_api_football", lambda bootstrap: {"status": "ACTIVE", "fixtures": []})
    monkeypatch.setattr(
        fusion,
        "collect_weather",
        lambda bootstrap, fixtures, previous=None: {
            "status": "ACTIVE",
            "availability_class": "PARTIAL",
            "weather_context_status": "PARTIAL",
            "fixtures": [{"fixture_id": 1}],
            "research": {"state": "INSUFFICIENT_SAMPLE"},
            "observability": {"network_requests": 0},
            "governance": {"decision_effect": "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION"},
        },
    )
    out = fusion.collect({"teams": []}, [{"id": 1}])
    assert "weather_context" in out["sources"]
    assert out["health"]["weather_context"] == "PARTIAL"
    assert out["health"]["weather_research_state"] == "INSUFFICIENT_SAMPLE"
    assert out["governance"]["weather_has_zero_production_decision_authority"] is True


def test_ingestion_owns_weather_fixture_acquisition(monkeypatch):
    from src.v5.services import ingestion

    def fake_fetch_many(specs):
        return ({"weather_fixtures": [{"id": 1}]}, {"weather_fixtures": {"status": "AVAILABLE"}})

    captured = {}

    def fake_fusion(bootstrap, fixtures):
        captured["fixtures"] = fixtures
        return {"status": "ACTIVE", "sources": {}, "health": {}}

    monkeypatch.setattr(ingestion, "fetch_many", fake_fetch_many)
    monkeypatch.setattr(ingestion, "collect_source_fusion", fake_fusion)
    out = ingestion.handle("collect_enrichment", {"bootstrap": {"teams": []}})
    assert captured["fixtures"] == [{"id": 1}]
    assert out["weather_fixture_acquisition"]["status"] == "FETCHED_BY_INGESTION"
