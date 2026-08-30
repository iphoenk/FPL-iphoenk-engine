from datetime import datetime, timezone

from src.v5.intelligence.weather_advisory import assert_advisory_governance, build_weather_shadow_evidence, classify_weather, select_governed_snapshot
from src.v5.intelligence.weather_shadow_runtime import enrich_weather_shadow


def test_v5_weather_is_shadow_advisory_only():
    assert_advisory_governance()
    out = classify_weather({"source_kind":"LIVE_OBSERVED","weather":{"temperature_c":18,"precipitation_probability_pct":90,"precipitation_mm_h":6.0,"wind_speed_kmh":24,"wind_gust_kmh":40}})
    assert out["severity"] == "ADVERSE"
    assert out["mode"] == "SHADOW_ADVISORY_ONLY"
    assert out["decision_effect"] == "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION"
    assert out["governance"]["production_decision_authority"] is False


def test_v5_rain_probability_alone_is_not_intensity():
    out=classify_weather({"weather":{"precipitation_probability_pct":100,"precipitation_mm_h":0.0}})
    assert out["severity"] == "NORMAL"
    assert "precipitation_intensity" not in out["signals"]


def test_evidence_precedence_is_governed():
    chosen=select_governed_snapshot([{"source_kind":"FRESH_FORECAST"},{"source_kind":"CLOSEST_TO_KICKOFF_OBSERVATION"},{"source_kind":"LIVE_OBSERVED"}])
    assert chosen["source_kind"] == "LIVE_OBSERVED"


def test_health_exposes_stale_and_unavailable():
    assert classify_weather(None)["health"] == "UNAVAILABLE"
    stale=classify_weather({"source_kind":"STALE_FORECAST","timestamp":"2026-08-29T00:00:00Z"},now=datetime(2026,8,30,tzinfo=timezone.utc))
    assert stale["health"] == "STALE"


def test_research_starts_insufficient_and_never_promotes_automatically():
    result=build_weather_shadow_evidence(snapshots=[{"source_kind":"LIVE_OBSERVED","weather":{"precipitation_mm_h":5}}],observed_effects={"slips":2},calibration={"sample_size":5,"minimum_sample":30})
    assert result["attribution"] == "POSSIBLE_CONTRIBUTING_FACTOR"
    assert result["research_state"] == "INSUFFICIENT_SAMPLE"
    assert result["promotion_gate"]["quantitative_signal_authorized"] is False
    assert "WEATHER_CAUSED" not in str(result)


def test_runtime_wires_shadow_evidence_with_zero_decision_authority():
    runtime=enrich_weather_shadow({"snapshots":[{"source_kind":"FRESH_FORECAST","confidence":0.9,"weather":{"wind_speed_kmh":23}}],"confounders":{"opponent_strength":"controlled"}})
    assert runtime["runtime_state"] == "ACTIVE"
    assert runtime["Weather Context"] == "PASS"
    assert runtime["decision_authority"] == "ZERO"
    assert runtime["decision_mutations"] == {}


def test_candidate_validation_is_still_only_candidate_not_production_authority():
    checks={"sample_size":100,"minimum_sample":30,"sufficient_sample":True,"repeatability":True,"out_of_sample_validation":True,"calibration_improvement":True,"non_regression":True,"explicit_governance_authorization":True}
    result=build_weather_shadow_evidence(calibration=checks)
    assert result["research_state"] == "VALIDATED_CANDIDATE"
    assert result["promotion_gate"]["state"] == "SHADOW_ADVISORY_ONLY"
    assert result["promotion_gate"]["quantitative_signal_authorized"] is False
