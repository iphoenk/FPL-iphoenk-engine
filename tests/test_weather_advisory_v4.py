from src.intelligence.weather_advisory import assert_advisory_governance, classify_weather


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
