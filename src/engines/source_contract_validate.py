from __future__ import annotations

import json

from src.engines.report_time_intelligence import validate_registry as validate_report_time_registry
from src.sources.official_first import load_official_first_coverage, validate_official_first_coverage
from src.utils import DATA, ROOT


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run() -> dict:
    health = _load(DATA / "source_health.json")
    registry = _load(ROOT / "config" / "sources" / "registry.json")
    observations = _load(DATA / "challenger_observations.json")
    weather = _load(DATA / "fixture_weather.json")
    report_time_registry = _load(ROOT / "config" / "sources" / "report_time_registry.json")

    registry_sources = {row["id"]: row for row in registry.get("sources") or []}
    runtime_sources = {row["id"]: row for row in health.get("sources") or []}
    enabled = {source_id for source_id, row in registry_sources.items() if row.get("enabled") is True}

    assert (health.get("registry") or {}).get("integrity_ok") is True
    assert enabled <= set(runtime_sources), ("missing_runtime_sources", sorted(enabled - set(runtime_sources)))
    assert health.get("critical_failed") == [], health.get("critical_failed")

    source_policy = registry.get("policy") or {}
    assert source_policy.get("official_fpl_is_native_authority") is True
    assert source_policy.get("official_first_rec_coverage_required") is True
    assert source_policy.get("official_first_rec_coverage_ref") == "config/sources/official_first_coverage.json"
    assert source_policy.get("fallback_requires_explicit_official_disposition") is True
    official_first_health = validate_official_first_coverage(load_official_first_coverage())
    assert official_first_health.get("integrity_ok") is True

    official = runtime_sources["official_fpl"]
    assert official.get("status") == "LIVE"
    assert official.get("reachable") is True
    for state in (official.get("capabilities") or {}).values():
        assert state == "AUTHORITATIVE_NATIVE", state

    weather_registry = registry_sources["open_meteo"]
    weather_runtime = runtime_sources["open_meteo"]
    assert weather_registry.get("class") == "ENRICHMENT"
    assert weather_registry.get("critical") is False
    assert weather_registry.get("adapter") == "weather_artifact"
    assert weather.get("schema_version") == 2
    assert weather.get("provider") == "open_meteo"
    assert weather.get("model") == "weather_context_governed_v2"
    assert (weather.get("governance") or {}).get("advisory_only") is True
    assert (weather.get("governance") or {}).get("rain_probability_is_not_rain_intensity") is True
    assert weather_runtime.get("status") in {"LIVE", "PARTIAL"}
    weather_states = set((weather_runtime.get("capabilities") or {}).values())
    assert weather_states <= {"AVAILABLE", "NO_FORECAST_IN_WINDOW", "UNAVAILABLE"}, weather_states

    onefpl_registry = registry_sources["onefpl"]
    onefpl_runtime = runtime_sources["onefpl"]
    assert onefpl_registry.get("enabled") is False
    assert onefpl_registry.get("adapter") == "disabled"
    assert onefpl_registry.get("delegated_to") == "REPORT_TIME_SOURCE_REGISTRY_V1"
    assert onefpl_runtime.get("status") == "DISABLED"
    assert onefpl_runtime.get("reachable") is False
    assert all(state == "DISABLED" for state in (onefpl_runtime.get("capabilities") or {}).values())

    report_time_health = validate_report_time_registry(report_time_registry)
    assert report_time_health.get("integrity_ok") is True, report_time_health
    report_sources = {row["id"]: row for row in report_time_registry.get("sources") or []}
    assert report_sources["onefpl"].get("enabled") is True
    assert report_sources["onefpl"].get("retrieval") == "REPORT_TIME_WEB"
    assert report_sources["onefpl"].get("class") == "MODEL_CHALLENGER"

    rows = observations.get("observations") or []
    for row in rows:
        assert row.get("contract") == "challenger_observation_v2"
        provider = row.get("provider") or row.get("source_id")
        assert provider in enabled, ("collector_observation_from_disabled_source", provider)
        assert provider != "onefpl"
        assert row.get("value") is not None
        assert row.get("source_url")
        assert row.get("fetched_at")
        assert row.get("observed_at")

    result = {
        "status": "PASS",
        "source_overall": health.get("overall"),
        "decision_blocking": health.get("decision_blocking"),
        "official_first": official_first_health,
        "weather": {
            "status": weather_runtime.get("status"),
            "capabilities": weather_runtime.get("capabilities"),
            "fixture_count": weather.get("fixture_count"),
            "available_count": weather.get("available_count"),
            "material_count": weather.get("material_count"),
            "advisory_only": (weather.get("governance") or {}).get("advisory_only"),
        },
        "onefpl": {
            "collector_status": onefpl_runtime.get("status"),
            "collector_enabled": onefpl_registry.get("enabled"),
            "delegated_to": onefpl_registry.get("delegated_to"),
            "report_time_enabled": report_sources["onefpl"].get("enabled"),
            "retrieval": report_sources["onefpl"].get("retrieval"),
        },
        "report_time_registry": report_time_health,
        "challenger_observations": len(rows),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
