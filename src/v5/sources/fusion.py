from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.persistence import read_artifact
from src.v5.sources.api_football import collect as collect_api_football
from src.v5.sources.season import season_authority
from src.v5.sources.understat import collect as collect_understat
from src.v5.sources.weather import collect as collect_weather

CONFIG = "config/intelligence/source_fusion.json"


def _source_summary(source: dict[str, Any]) -> dict[str, Any]:
    observability = source.get("observability") if isinstance(source.get("observability"), dict) else {}
    governance = source.get("governance") if isinstance(source.get("governance"), dict) else {}
    health = source.get("health") if isinstance(source.get("health"), dict) else {}
    return {
        "status": source.get("status"),
        "availability_class": source.get("availability_class"),
        "reason": source.get("reason"),
        "fetch_mode": source.get("fetch_mode"),
        "player_count": source.get("player_count", len(source.get("players") or [])),
        "fixture_count": len(source.get("fixtures") or []),
        "weather_context_status": source.get("weather_context_status") or health.get("status"),
        "research_state": ((source.get("research") or {}).get("state") if isinstance(source.get("research"), dict) else None),
        "credential_present": observability.get("credential_present"),
        "network_requests": observability.get("network_requests"),
        "cache_hits": observability.get("cache_hits"),
        "availability_cache_hits": observability.get("availability_cache_hits"),
        "competitions_attempted": observability.get("competitions_attempted"),
        "competitions_resolved": observability.get("competitions_resolved"),
        "quota_remaining": observability.get("quota_remaining"),
        "quota_limit": observability.get("quota_limit"),
        "fail_neutral": governance.get("fail_neutral"),
    }


def collect(bootstrap: dict[str, Any], fixtures: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    season = season_authority()
    previous_fusion = read_artifact("source_fusion", {})
    previous_sources = previous_fusion.get("sources") if isinstance(previous_fusion, dict) and isinstance(previous_fusion.get("sources"), dict) else {}
    previous_weather = previous_sources.get("weather_context") if isinstance(previous_sources.get("weather_context"), dict) else {}
    official_fixtures = fixtures if isinstance(fixtures, list) else []
    with ThreadPoolExecutor(max_workers=3) as pool:
        understat_future = pool.submit(collect_understat)
        api_football_future = pool.submit(collect_api_football, bootstrap)
        weather_future = pool.submit(collect_weather, bootstrap, official_fixtures, previous=previous_weather)
        understat = understat_future.result()
        api_football = api_football_future.result()
        weather = weather_future.result()
    summaries = {
        "understat": _source_summary(understat),
        "api_football": _source_summary(api_football),
        "weather_context": _source_summary(weather),
    }
    statuses = [str(row.get("status") or "UNAVAILABLE") for row in summaries.values()]
    active_count = sum(status == "ACTIVE" for status in statuses)
    degraded_count = sum(status == "DEGRADED" for status in statuses)
    unavailable_count = sum(status in {"UNAVAILABLE", "DISABLED"} for status in statuses)
    plan_restricted_count = sum(str(row.get("availability_class") or "") == "PLAN_RESTRICTED" for row in summaries.values())
    overall = "ACTIVE" if active_count else ("DEGRADED" if degraded_count else "UNAVAILABLE")
    return {
        "schema_version": 4,
        "model": cfg.get("model_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "season": season,
        "health": {
            "active_sources": active_count,
            "degraded_sources": degraded_count,
            "unavailable_sources": unavailable_count,
            "plan_restricted_sources": plan_restricted_count,
            "weather_context": weather.get("weather_context_status"),
            "weather_research_state": ((weather.get("research") or {}).get("state") if isinstance(weather.get("research"), dict) else None),
            "sources": summaries,
        },
        "sources": {
            "understat": understat,
            "api_football": api_football,
            "weather_context": weather,
        },
        "governance": {
            "official_fpl_remains_native_authority": True,
            "fpl_core_insights_remains_primary_epl_advanced_stats": True,
            "challenger_failure_is_fail_neutral": True,
            "optional_source_plan_restriction_is_not_engine_failure": True,
            "missing_enrichment_is_unavailable_not_zero": True,
            "network_fetch_owner": "ingestion",
            "weather_is_shadow_advisory_only": True,
            "weather_has_zero_production_decision_authority": True,
            "weather_quantitative_modifier_consumption": False,
        },
    }
