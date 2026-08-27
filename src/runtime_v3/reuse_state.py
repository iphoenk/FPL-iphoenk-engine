from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.utils import atomic_json, read_json


def _historical_prior_v1(canonical: Path, latest: dict[str, Any]) -> list[str]:
    prior = read_json(canonical / "prior_season.json", {})
    if not prior:
        raise RuntimeError("historical_prior reuse artifact is empty")
    latest["historical_prior_summary"] = {
        "model": prior.get("model"),
        "season": prior.get("season"),
        "fetch_mode": prior.get("fetch_mode"),
        "coverage": prior.get("coverage"),
    }
    latest.setdefault("files", {}).update({
        "prior_season": "data/prior_season.json",
        "vaastav_previous_season": "data/stats/vaastav_previous_season.json",
    })
    return ["historical_prior_summary"]


def _source_layer_v1(canonical: Path, latest: dict[str, Any]) -> list[str]:
    payload = read_json(canonical / "source_health.json", {})
    if not payload:
        raise RuntimeError("source_layer reuse artifact is empty")
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
    latest.setdefault("files", {}).update({
        "source_health": "data/source_health.json",
        "source_registry_runtime": "data/source_registry_runtime.json",
        "challenger_observations": "data/challenger_observations.json",
        "fixture_weather": "data/fixture_weather.json",
    })
    return ["source_layer_summary"]


def _official_detail_v1(canonical: Path, latest: dict[str, Any]) -> list[str]:
    payload = read_json(canonical / "official_detail.json", {})
    if not payload:
        raise RuntimeError("official_detail reuse artifact is empty")
    owned = [int(x) for x in payload.get("owned_element_ids") or []]
    details = payload.get("element_summaries") or {}
    detail_ids = payload.get("detail_element_ids") or []
    official_health = payload.get("official_health") or {}
    element_health = official_health.get("element_summary") or {}
    detail_live = int(element_health.get("live") or 0)
    detail_health = official_health.get("detail") or {}
    latest["official_detail_summary"] = {
        "generated_at": payload.get("generated_at"),
        "owned_detail_coverage": f"{sum(1 for element in owned if str(element) in details)}/{len(owned)}",
        "detail_requested": int(element_health.get("requested") or len(detail_ids)),
        "detail_live": detail_live,
        "set_piece_notes_status": (detail_health.get("set_piece_notes") or {}).get("status"),
        "dream_team_status": (detail_health.get("dream_team_season") or {}).get("status"),
        "entry_cup_status": (detail_health.get("entry_cup") or {}).get("status"),
        "overall": official_health.get("overall"),
        "file": "data/official_detail.json",
    }
    latest["official_health_panel"] = official_health
    return ["official_detail_summary", "official_health_panel"]


_HANDLERS: dict[str, Callable[[Path, dict[str, Any]], list[str]]] = {
    "historical_prior_v1": _historical_prior_v1,
    "source_layer_v1": _source_layer_v1,
    "official_detail_v1": _official_detail_v1,
}


def rehydrate_reused_latest(service_name: str, spec: dict[str, Any], canonical: Path) -> dict[str, Any]:
    latest_keys = [str(key) for key in spec.get("latest_keys") or []]
    latest_file_keys = [str(key) for key in spec.get("latest_file_keys") or []]
    handler_name = str(spec.get("reuse_latest_state_handler") or "").strip()
    if not latest_keys and not latest_file_keys:
        return {"status": "NOOP", "handler": None, "latest_keys": [], "latest_file_keys": []}
    if not handler_name:
        raise RuntimeError(f"reusable service {service_name} owns latest state but has no reuse_latest_state_handler")
    handler = _HANDLERS.get(handler_name)
    if handler is None:
        raise RuntimeError(f"unknown reuse latest-state handler for {service_name}: {handler_name}")

    latest_path = canonical / "latest.json"
    latest = read_json(latest_path, {})
    if not latest:
        raise RuntimeError(f"latest.json unavailable while rehydrating {service_name}")
    touched = handler(canonical, latest)

    missing_keys = [key for key in latest_keys if key not in latest]
    files = latest.get("files") if isinstance(latest.get("files"), dict) else {}
    missing_file_keys = [key for key in latest_file_keys if key not in files]
    if missing_keys or missing_file_keys:
        raise RuntimeError({
            "service": service_name,
            "handler": handler_name,
            "missing_latest_keys": missing_keys,
            "missing_latest_file_keys": missing_file_keys,
        })
    atomic_json(latest_path, latest)
    return {
        "status": "REHYDRATED",
        "handler": handler_name,
        "latest_keys": sorted(set(touched)),
        "latest_file_keys": latest_file_keys,
    }
