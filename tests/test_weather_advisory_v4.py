from datetime import datetime, timezone

from src.intelligence.weather_advisory import (
    assert_advisory_governance,
    attribute_live_weather_incidents,
    classify_weather,
    select_weather_evidence,
)


def test_weather_advisory_cannot_directly_mutate_decisions():
    assert_advisory_governance()
    out = classify_weather({
        "source_kind": "LIVE_OBSERVED_ADVISORY",
        "weather": {
            "temperature_c": 18,
            "precipitation_probability_pct": 90,
            "precipitation_mm_h": 6.0,
            "wind_speed_kmh": 24,
            "wind_gust_kmh": 40,
        },
    })
    assert out["severity"] == "ADVERSE"
    assert out["decision_effect"] == "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION"
    assert out["mode"] == "ADVISORY_ONLY"
    assert out["governance"]["may_directly_change_xpts"] is False
    assert out["governance"]["may_directly_change_starting_xi"] is False
    assert out["governance"]["may_directly_change_transfer_decision"] is False


def test_rain_probability_is_not_intensity():
    out = classify_weather({
        "weather": {"precipitation_probability_pct": 100, "precipitation_mm_h": 0.0}
    })
    assert out["severity"] == "NORMAL"
    assert "precipitation_intensity" not in out["signals"]


def test_live_observation_overrides_closest_to_kickoff_and_forecast():
    now = datetime(2026, 9, 2, 18, 10, tzinfo=timezone.utc)
    kickoff = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
    evidence = [
        {
            "source_kind": "FRESH_FORECAST",
            "evidence_timestamp": "2026-09-02T16:00:00+00:00",
            "weather": {"precipitation_mm_h": 0.0},
        },
        {
            "source_kind": "CLOSEST_TO_KICKOFF_OBSERVATION",
            "evidence_timestamp": "2026-09-02T17:58:00+00:00",
            "weather": {"precipitation_mm_h": 2.5},
        },
        {
            "source_kind": "LIVE_OBSERVED",
            "evidence_timestamp": "2026-09-02T18:05:00+00:00",
            "weather": {"precipitation_mm_h": 6.0},
        },
    ]

    selected = select_weather_evidence(evidence, kickoff=kickoff, now=now)

    assert selected is not None
    assert selected["source_kind"] == "LIVE_OBSERVED"
    assert selected["weather"]["precipitation_mm_h"] == 6.0


def test_closest_to_kickoff_observation_overrides_forecast_without_live_evidence():
    now = datetime(2026, 9, 2, 18, 10, tzinfo=timezone.utc)
    kickoff = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
    evidence = [
        {
            "source_kind": "FRESH_FORECAST",
            "evidence_timestamp": "2026-09-02T16:00:00+00:00",
            "weather": {"precipitation_mm_h": 0.0},
        },
        {
            "source_kind": "CLOSEST_TO_KICKOFF_OBSERVATION",
            "evidence_timestamp": "2026-09-02T17:40:00+00:00",
            "weather": {"precipitation_mm_h": 1.5},
        },
        {
            "source_kind": "CLOSEST_TO_KICKOFF_OBSERVATION",
            "evidence_timestamp": "2026-09-02T17:59:00+00:00",
            "weather": {"precipitation_mm_h": 3.0},
        },
    ]

    selected = select_weather_evidence(evidence, kickoff=kickoff, now=now)

    assert selected is not None
    assert selected["source_kind"] == "CLOSEST_TO_KICKOFF_OBSERVATION"
    assert selected["evidence_timestamp"] == "2026-09-02T17:59:00+00:00"


def test_live_weather_incident_attribution_is_advisory_not_causal():
    selected = classify_weather({
        "source_kind": "LIVE_OBSERVED",
        "evidence_timestamp": "2026-09-02T18:05:00+00:00",
        "weather": {
            "precipitation_mm_h": 6.0,
            "wind_speed_kmh": 24,
            "wind_gust_kmh": 40,
        },
    })
    incidents = [
        {"type": "SLIP", "credible": True, "player": "example-a"},
        {"type": "MISCONTROL", "verified": True, "player": "example-b"},
    ]

    attributed = attribute_live_weather_incidents(incidents, selected)

    assert attributed["state"] == "MATERIAL_ADVISORY"
    assert attributed["label"] == "POSSIBLE_CONTRIBUTING_FACTOR"
    assert attributed["causal_claim"] is False
    assert len(attributed["credible_incidents"]) == 2
    assert all(
        row["attribution"] == "POSSIBLE_CONTRIBUTING_FACTOR"
        for row in attributed["credible_incidents"]
    )
