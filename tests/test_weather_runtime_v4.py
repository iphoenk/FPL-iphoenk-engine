from __future__ import annotations

from datetime import datetime, timezone

from src.engines.v4_weather_tactical_overlay import apply_weather_overlay
from src.intelligence.weather_advisory import (
    attribute_live_weather_incidents,
    collect_weather_context,
    player_weather_sensitivity,
    select_weather_evidence,
    system_weather_interactions,
    weather_uncertainty_advisory,
)
from src.services.weather_health_overlay import apply_weather_health


def _weather(mm=0.0, gust=10.0, wind=8.0, probability=0):
    return {
        "temperature_c": 16,
        "precipitation_probability_pct": probability,
        "precipitation_mm_h": mm,
        "wind_speed_kmh": wind,
        "wind_gust_kmh": gust,
        "weather_code": 61 if mm else 1,
    }


def test_evidence_precedence_live_over_closest_and_forecasts():
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    kickoff = datetime(2026, 8, 30, 13, tzinfo=timezone.utc)
    evidence = [
        {"source_kind": "STALE_FORECAST", "evidence_timestamp": "2026-08-29T00:00:00+00:00", "weather": _weather()},
        {"source_kind": "FRESH_FORECAST", "evidence_timestamp": "2026-08-30T11:00:00+00:00", "weather": _weather(mm=2)},
        {"source_kind": "CLOSEST_TO_KICKOFF_OBSERVATION", "evidence_timestamp": "2026-08-30T12:40:00+00:00", "weather": _weather(mm=4)},
        {"source_kind": "LIVE_OBSERVED", "evidence_timestamp": "2026-08-30T11:50:00+00:00", "weather": _weather(mm=6)},
    ]
    selected = select_weather_evidence(evidence, kickoff=kickoff, now=now)
    assert selected["source_kind"] == "LIVE_OBSERVED"
    assert selected["severity"] == "ADVERSE"


def test_player_archetype_and_system_interaction_are_not_blanket_modifiers():
    selected = {
        "severity": "ADVERSE",
        "signals": ["precipitation_intensity", "wind_gust"],
        "weather": _weather(mm=5, gust=48),
    }
    gk = player_weather_sensitivity("GK", selected, "sweeper_keeper")
    mid = player_weather_sensitivity("MID", selected, "press_resistant_8")
    assert "handling" in gk["affected_dimensions"]
    assert "first_touch" in mid["affected_dimensions"]
    assert gk["affected_dimensions"] != mid["affected_dimensions"]
    assert gk["blanket_modifier_applied"] is False

    interactions = system_weather_interactions(
        selected,
        own_system={"build_up": "short build-up, high defensive line"},
        opponent_system={"press": "aggressive press", "set_piece": "crossing and aerial reliance"},
        role="press_resistant_8",
    )
    names = {row["interaction"] for row in interactions}
    assert "WET_SHORT_BUILDUP_VS_AGGRESSIVE_PRESS" in names
    assert "WET_SURFACE_WITH_HIGH_DEFENSIVE_LINE" in names
    assert "STRONG_WIND_WITH_DELIVERY_RELIANCE" in names


def test_live_attribution_one_incident_low_repeated_pattern_material():
    selected = {"severity": "ADVERSE", "signals": ["precipitation_intensity"], "weather": _weather(mm=5)}
    one = attribute_live_weather_incidents(
        [{"incident_type": "SLIP", "credible": True, "observed_return": "opponent slip -> goal"}],
        selected,
    )
    assert one["label"] == "POSSIBLE_CONTRIBUTING_FACTOR"
    assert one["confidence"] == "LOW"
    assert one["causal_claim"] is False

    repeated = attribute_live_weather_incidents(
        [
            {"incident_type": "SLIP", "credible": True},
            {"incident_type": "MISCONTROL", "verified": True},
        ],
        selected,
    )
    assert repeated["state"] == "MATERIAL_ADVISORY"
    assert repeated["causal_claim"] is False


def test_uncertainty_first_never_changes_expected_xpts_mean():
    selected = {"severity": "EXTREME", "signals": ["wind_gust"], "weather": _weather(gust=70)}
    out = weather_uncertainty_advisory(
        selected,
        sensitivity={"risk_band": "VERY_HIGH"},
        interactions=[{"interaction": "STRONG_WIND_WITH_DELIVERY_RELIANCE"}],
        attribution={"state": "LOW_CONFIDENCE"},
    )
    assert out["variance"] == "WIDER_ADVISORY"
    assert out["floor_ceiling"] == "WIDER_ADVISORY"
    assert out["expected_xpts_mean_adjustment"] == 0.0
    assert out["numeric_weather_coefficient_applied"] is False


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "hourly": {
                "time": ["2026-08-31T16:00"],
                "temperature_2m": [15.0],
                "precipitation_probability": [90],
                "precipitation": [5.0],
                "wind_speed_10m": [24.0],
                "wind_gusts_10m": [42.0],
                "weather_code": [63],
            }
        }


def _snapshot():
    return {
        "schema": "snapshot.v1",
        "generated_at": "2026-08-30T12:00:00+00:00",
        "phase": {"planning_gw": 3},
        "official": {
            "bootstrap": {
                "teams": [
                    {"id": 1, "name": "Arsenal"},
                    {"id": 6, "name": "Chelsea"},
                ]
            },
            "fixtures": [
                {
                    "id": 101,
                    "event": 3,
                    "team_h": 1,
                    "team_a": 6,
                    "kickoff_time": "2026-08-31T15:00:00+00:00",
                    "started": False,
                    "finished": False,
                }
            ],
        },
    }


def test_runtime_ingestion_precedence_and_health():
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)

    def fetcher(*args, **kwargs):
        return _Response()

    live = {
        "fixtures": [{
            "fixture_id": 101,
            "evidence": [{
                "source_kind": "LIVE_OBSERVED",
                "evidence_timestamp": "2026-08-30T11:45:00+00:00",
                "weather": _weather(mm=6, gust=48),
                "provenance": {"source": "verified observation"},
            }],
            "incidents": [{"incident_type": "SLIP", "credible": True}],
        }]
    }
    out = collect_weather_context(_snapshot(), live_evidence=live, now=now, fetcher=fetcher)
    assert out["contract"] == "V4_WEATHER_CONTEXT_RUNTIME_V1"
    assert out["health"]["status"] == "PASS"
    assert out["fixtures"][0]["evidence_state"] == "LIVE_OBSERVED"
    assert out["fixtures"][0]["selected_evidence"]["severity"] == "ADVERSE"
    assert out["governance"]["expected_xpts_mean_adjustment"] == 0.0


def test_runtime_ingestion_unavailable_downgrades_tactical_completeness():
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)

    def broken(*args, **kwargs):
        raise RuntimeError("weather provider unavailable")

    out = collect_weather_context(_snapshot(), now=now, fetcher=broken)
    assert out["health"]["status"] == "UNAVAILABLE"
    assert out["health"]["tactical_context_completeness"] == "PARTIAL"


def test_tactical_overlay_preserves_prediction_and_watchlist_rank():
    predictions = {
        "players": [{
            "element": 10,
            "xpts_5": 25.0,
            "xpts_15": 70.0,
            "value": {"xpts5_per_million": 4.2},
            "fixtures": [
                {
                    "event": 3,
                    "xpts": 5.0,
                    "lower80": 2.0,
                    "upper80": 8.0,
                    "xmins": {"start_probability": 0.9},
                    "rates": {"xg90": 0.4, "xa90": 0.3},
                },
                {"event": 4, "xpts": 5.0},
                {"event": 5, "xpts": 5.0},
            ],
        }]
    }
    tactical = {
        "owned": [],
        "watchlist": [{
            "element": 10,
            "name": "Player",
            "position": "MID",
            "team": "Arsenal",
            "score": 30.0,
            "replacement_context": {"owned_element": 20},
            "tactical": {
                "player_role": "press_resistant_8",
                "evidence_state": "VERIFIED",
                "build_up_press_block_traits": "aggressive press",
                "role_vs_opponent_fit": "positive",
            },
        }],
        "guardrails": {},
    }
    weather = {
        "health": {
            "status": "PASS",
            "required_for_tactical_context": True,
            "tactical_context_completeness": "FULL",
        },
        "fixture_count": 1,
        "available_count": 1,
        "material_count": 1,
        "evidence_precedence": ["LIVE_OBSERVED", "CLOSEST_TO_KICKOFF_OBSERVATION", "FRESH_FORECAST", "STALE_FORECAST"],
        "fixtures": [{
            "fixture_id": 101,
            "event": 3,
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "evidence_state": "LIVE_OBSERVED",
            "selected_evidence": {
                "source_kind": "LIVE_OBSERVED",
                "severity": "ADVERSE",
                "signals": ["precipitation_intensity"],
                "weather": _weather(mm=5),
            },
            "live_attribution": {
                "state": "LOW_CONFIDENCE",
                "confidence": "LOW",
                "label": "POSSIBLE_CONTRIBUTING_FACTOR",
                "credible_incidents": [{"incident_type": "SLIP", "observed_return": "goal"}],
                "causal_claim": False,
            },
        }],
    }
    competitive = {"players": [{"element": 10, "current_gw_matches": []}]}
    before_score = tactical["watchlist"][0]["score"]
    before_xpts = predictions["players"][0]["fixtures"][0]["xpts"]
    out = apply_weather_overlay(
        tactical,
        predictions=predictions,
        universe={"players": []},
        weather=weather,
        external={"teams": {"Arsenal": {"build_up": "short build-up"}}},
        competitive=competitive,
        write=False,
    )
    row = out["watchlist"][0]
    assert row["score"] == before_score
    assert predictions["players"][0]["fixtures"][0]["xpts"] == before_xpts
    assert row["tactical"]["weather_context"]["uncertainty"]["base_mean_xpts"] == before_xpts
    assert row["tactical"]["weather_context"]["uncertainty"]["expected_xpts_mean_adjustment"] == 0.0
    assert row["tactical"]["weather_context"]["challenger_governance"]["weather_can_independently_promote_player"] is False
    assert row["tactical"]["weather_context"]["sustainability"]["sustainable_attacking_expectation_adjustment"] == 0.0


def test_weather_health_propagation_downgrades_tactical_not_core_pipeline():
    health = {
        "pipeline_health": "GREEN",
        "capability_telemetry": {
            "capabilities": {
                "Tactical Matchup": {"state": "ACTIVE", "evidence": {"owned": 15, "watchlist": 20}},
                "Prediction": {"state": "ACTIVE", "evidence": {}},
            },
            "summary": {"ACTIVE": 2},
        },
        "governance": {},
    }
    weather = {
        "health": {
            "status": "UNAVAILABLE",
            "reason": "NO_WEATHER_EVIDENCE",
            "required_for_tactical_context": True,
            "tactical_context_completeness": "PARTIAL",
        },
        "governance": {"advisory_only": True},
    }
    out = apply_weather_health(health, weather=weather, tactical={}, write=False)
    assert out["pipeline_health"] == "GREEN"
    assert out["weather_context"]["status"] == "UNAVAILABLE"
    assert out["capability_telemetry"]["capabilities"]["Tactical Matchup"]["state"] == "PARTIAL"
    assert out["pipeline_components"]["Weather Context"] == "UNAVAILABLE"
