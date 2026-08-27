from __future__ import annotations

import json

from src.sources.manager import collect_sources
from src.sources.registry import load_source_registry
from src.sources.weather_open_meteo import collect_weather_context
from src.utils import DATA, atomic_json, iso_now, read_json

OUT = DATA / "source_health.json"
RUNTIME_OUT = DATA / "source_registry_runtime.json"
OBSERVATION_OUT = DATA / "challenger_observations.json"
WEATHER_OUT = DATA / "fixture_weather.json"


def _collector_owned_observations(observations: dict, payload: dict) -> dict:
    registry = load_source_registry()
    enabled_ids = {str(row.get("id")) for row in registry.get("sources") or [] if row.get("enabled") is True}
    rows = []
    for row in observations.get("observations") or []:
        source_id = str(row.get("source_id") or row.get("provider") or "")
        if source_id and source_id not in enabled_ids:
            continue
        rows.append(row)
    cross_source = []
    for row in observations.get("cross_source") or []:
        providers = [str(value) for value in row.get("providers") or []]
        active = [value for value in providers if value in enabled_ids]
        if not active:
            continue
        item = dict(row)
        item["providers"] = active
        item["state"] = "SINGLE_SOURCE" if len(active) == 1 else item.get("state")
        cross_source.append(item)
    fresh = sum(1 for row in rows if row.get("status") == "AVAILABLE" and not row.get("stale"))
    cached = sum(1 for row in rows if row.get("status") == "CACHED_LAST_KNOWN_GOOD")
    stale = sum(1 for row in rows if row.get("status") == "STALE")
    legacy = sum(1 for row in rows if row.get("contract") != observations.get("contract"))
    disagreements = sum(1 for row in cross_source if row.get("state") == "DISAGREEMENT")
    sanitized = dict(observations)
    sanitized["observations"] = rows
    sanitized["cross_source"] = cross_source
    sanitized["counts"] = {"fresh": fresh, "cached_last_known_good": cached, "stale": stale, "legacy": legacy}
    payload["structured_observation_count"] = fresh
    payload["structured_cached_count"] = cached
    payload["structured_stale_count"] = stale
    payload["disagreement_count"] = disagreements
    return sanitized


def run() -> dict:
    weather = collect_weather_context(DATA)
    payload = collect_sources(DATA)
    observations = payload.pop("challenger_observations_payload", {"schema_version": 2, "observations": []})
    observations = _collector_owned_observations(observations, payload)
    payload["generated_at"] = iso_now()
    payload["weather_summary"] = {
        "provider": weather.get("provider"),
        "fixture_count": weather.get("fixture_count", 0),
        "available_count": weather.get("available_count", 0),
        "material_count": weather.get("material_count", 0),
        "advisory_only": bool((weather.get("governance") or {}).get("advisory_only")),
    }
    atomic_json(OUT, payload)
    atomic_json(OBSERVATION_OUT, observations)

    runtime = {
        "generated_at": payload["generated_at"],
        "registry": payload.get("registry"),
        "sources": [{"id": row.get("id"), "class": row.get("class"), "status": row.get("status"), "reachable": row.get("reachable"), "observation_count": row.get("observation_count")} for row in payload.get("sources") or []],
        "capability_health": payload.get("capability_health") or [],
        "structured_observations": {"fresh": payload.get("structured_observation_count", 0), "cached_last_known_good": payload.get("structured_cached_count", 0), "stale": payload.get("structured_stale_count", 0), "disagreements": payload.get("disagreement_count", 0)},
        "weather": payload.get("weather_summary"),
        "policy": payload.get("policy"),
    }
    atomic_json(RUNTIME_OUT, runtime)

    latest = read_json(DATA / "latest.json", {})
    latest["source_layer_summary"] = {
        "overall": payload.get("overall"),
        "decision_blocking": payload.get("decision_blocking"),
        "enabled": payload.get("enabled_count"),
        "challenger_live": payload.get("challenger_live_count"),
        "challenger_live_ids": payload.get("challenger_live"),
        "structured_observations_fresh": payload.get("structured_observation_count", 0),
        "structured_observations_cached": payload.get("structured_cached_count", 0),
        "structured_observations_stale": payload.get("structured_stale_count", 0),
        "structured_disagreements": payload.get("disagreement_count", 0),
        "weather": payload.get("weather_summary"),
        "capability_count": len(payload.get("capability_health") or []),
        "elapsed_ms": payload.get("elapsed_ms"),
    }
    latest.setdefault("files", {})["source_health"] = "data/source_health.json"
    latest["files"]["source_registry_runtime"] = "data/source_registry_runtime.json"
    latest["files"]["challenger_observations"] = "data/challenger_observations.json"
    latest["files"]["fixture_weather"] = "data/fixture_weather.json"
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(latest["source_layer_summary"], ensure_ascii=False))
    return payload


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
