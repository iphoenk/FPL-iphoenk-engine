from datetime import datetime, timezone

from src.v5.intelligence.weather_advisory import assert_advisory_governance, build_weather_shadow_evidence, classify_weather, select_governed_snapshot
from src.v5.intelligence.weather_shadow_runtime import enrich_weather_shadow
from src.v5.services import prediction as prediction_service


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


def test_same_precedence_prefers_newer_snapshot_without_timestamp_overflow():
    chosen=select_governed_snapshot([
        {"source_kind":"FRESH_FORECAST"},
        {"source_kind":"FRESH_FORECAST","timestamp":"2026-08-30T12:00:00Z","weather":{"temperature_c":20}},
    ])
    assert chosen["weather"]["temperature_c"] == 20


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


def test_prediction_runtime_consumes_weather_evidence_without_mutating_predictions(monkeypatch):
    monkeypatch.setattr(prediction_service, "build_full_core_enrichment", lambda *args, **kwargs: {"status":"ACTIVE","model":"test","capabilities":[],"advanced_stats":{},"observed_tactical_context":{},"competitive_load":{},"schedule":{},"preseason":{},"current_form":{},"source_fusion":{},"governance":{}})
    monkeypatch.setattr(prediction_service, "resolve_prior", lambda *args, **kwargs: {})
    monkeypatch.setattr(prediction_service, "build_predictions", lambda *args, **kwargs: {"generated_at":"now","schema_version":1,"model_version":"test","ruleset_id":"test","planning_gw":1,"horizon_gws":[1],"historical_prior":{},"team_strength":{},"role_intelligence":{},"players":[{"element":1,"name":"A","team_id":1,"position":"MID","mean_xpts":5.0}],"governance":{},"network_contract":{}})
    monkeypatch.setattr(prediction_service, "evaluate_prediction_quality", lambda *args, **kwargs: {"status":"HEALTHY","failed_checks":[]})
    monkeypatch.setattr(prediction_service, "enrich_prediction", lambda base, enrichment: {**base,"advanced_prediction":{"weather_mutation":False}})
    monkeypatch.setattr(prediction_service, "attach_tactical_matchups", lambda result, *args, **kwargs: result)

    base_payload={"bootstrap":{},"fixtures":[],"rules":{},"planning_gw":1}
    without_weather=prediction_service.handle("build",dict(base_payload))
    with_weather=prediction_service.handle("build",{**base_payload,"weather_evidence":{"snapshots":[{"source_kind":"LIVE_OBSERVED","confidence":0.9,"weather":{"precipitation_mm_h":5.0}}]}})

    assert with_weather["players"] == without_weather["players"]
    assert with_weather["full_core_enrichment"]["weather_shadow_research"]["Weather Context"] == "PASS"
    assert with_weather["full_core_enrichment"]["weather_shadow_research"]["decision_authority"] == "ZERO"
    assert "weather_shadow_research" in with_weather["capabilities"]
