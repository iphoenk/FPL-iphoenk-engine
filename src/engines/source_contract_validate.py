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
    challenger_registry = _load(ROOT / "config" / "intelligence" / "challenger_registry.json")
    collector_policy = _load(ROOT / "config" / "runtime" / "collector_policy.json")

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
    assert source_policy.get("retired_sources_must_not_reappear_in_runtime_or_report_sweeps") is True
    official_first_health = validate_official_first_coverage(load_official_first_coverage())
    assert official_first_health.get("integrity_ok") is True

    report_time_health = validate_report_time_registry(report_time_registry)
    assert report_time_health.get("integrity_ok") is True, report_time_health
    report_sources = {row["id"]: row for row in report_time_registry.get("sources") or []}
    challenger_sources = {row["id"]: row for row in challenger_registry.get("providers") or []}
    deadline_sweep_sources = {
        source_id
        for tier in (collector_policy.get("deadline_source_sweep") or {}).get("tiers", {}).values()
        for source_id in tier
    }
    retired = set(source_policy.get("retired_source_ids") or [])
    assert retired
    assert retired.isdisjoint(registry_sources), ("retired_source_in_machine_registry", sorted(retired & set(registry_sources)))
    assert retired.isdisjoint(report_sources), ("retired_source_in_report_registry", sorted(retired & set(report_sources)))
    assert retired.isdisjoint(challenger_sources), ("retired_source_in_challenger_registry", sorted(retired & set(challenger_sources)))
    assert retired.isdisjoint(deadline_sweep_sources), ("retired_source_in_deadline_sweep", sorted(retired & deadline_sweep_sources))

    official_registry = registry_sources["official_fpl"]
    official = runtime_sources["official_fpl"]
    official_health_endpoints = [str(x) for x in official_registry.get("health_endpoints") or []]
    assert official_health_endpoints
    assert set((official.get("detail") or {}).get("critical_endpoints") or {}) == set(official_health_endpoints)
    assert official.get("status") == "LIVE"
    assert official.get("reachable") is True
    for state in (official.get("capabilities") or {}).values():
        assert state == "AUTHORITATIVE_NATIVE", state

    weather_registry = registry_sources["open_meteo"]
    weather_runtime = runtime_sources["open_meteo"]
    assert weather_registry.get("class") == "ENRICHMENT"
    assert weather_registry.get("critical") is False
    assert weather_registry.get("adapter") == "weather_artifact"
    weather_artifacts = [str(x) for x in weather_registry.get("artifact_paths") or []]
    assert len(weather_artifacts) == 1
    assert (weather_runtime.get("detail") or {}).get("artifact") == weather_artifacts[0]
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
    assert report_sources["onefpl"].get("enabled") is True
    assert report_sources["onefpl"].get("retrieval") == "REPORT_TIME_WEB"
    assert report_sources["onefpl"].get("class") == "MODEL_CHALLENGER"
    assert "onefpl" not in challenger_sources
    assert (challenger_registry.get("governance") or {}).get("report_time_only_providers_are_excluded_from_machine_scorecard") is True

    rows = observations.get("observations") or []
    for row in rows:
        assert row.get("contract") == "challenger_observation_v2"
        provider = row.get("provider") or row.get("source_id")
        assert provider in enabled, ("collector_observation_from_disabled_source", provider)
        assert provider != "onefpl"
        assert provider not in retired
        assert row.get("value") is not None
        assert row.get("source_url")
        assert row.get("fetched_at")
        assert row.get("observed_at")

    result = {
        "status": "PASS",
        "source_overall": health.get("overall"),
        "decision_blocking": health.get("decision_blocking"),
        "official_first": official_first_health,
        "source_lifecycle": {
            "retired": sorted(retired),
            "machine_challengers": sorted(challenger_sources),
            "deadline_sweep_count": len(deadline_sweep_sources),
        },
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
            "machine_scorecard_present": "onefpl" in challenger_sources,
        },
        "report_time_registry": report_time_health,
        "challenger_observations": len(rows),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
