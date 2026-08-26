from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.sources.api_football import collect as collect_api_football
from src.v5.sources.season import season_authority
from src.v5.sources.understat import collect as collect_understat

CONFIG = "config/intelligence/source_fusion.json"


def _source_summary(source: dict[str, Any]) -> dict[str, Any]:
    observability = source.get("observability") if isinstance(source.get("observability"), dict) else {}
    governance = source.get("governance") if isinstance(source.get("governance"), dict) else {}
    return {
        "status": source.get("status"),
        "availability_class": source.get("availability_class"),
        "reason": source.get("reason"),
        "fetch_mode": source.get("fetch_mode"),
        "player_count": source.get("player_count", len(source.get("players") or [])),
        "fixture_count": len(source.get("fixtures") or []),
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


def collect(bootstrap: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    season = season_authority()
    with ThreadPoolExecutor(max_workers=2) as pool:
        understat_future = pool.submit(collect_understat)
        api_football_future = pool.submit(collect_api_football, bootstrap)
        understat = understat_future.result()
        api_football = api_football_future.result()
    summaries = {
        "understat": _source_summary(understat),
        "api_football": _source_summary(api_football),
    }
    statuses = [str(row.get("status") or "UNAVAILABLE") for row in summaries.values()]
    active_count = sum(status == "ACTIVE" for status in statuses)
    degraded_count = sum(status == "DEGRADED" for status in statuses)
    unavailable_count = sum(status in {"UNAVAILABLE", "DISABLED"} for status in statuses)
    plan_restricted_count = sum(str(row.get("availability_class") or "") == "PLAN_RESTRICTED" for row in summaries.values())
    overall = "ACTIVE" if active_count else ("DEGRADED" if degraded_count else "UNAVAILABLE")
    return {
        "schema_version": 3,
        "model": cfg.get("model_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "season": season,
        "health": {
            "active_sources": active_count,
            "degraded_sources": degraded_count,
            "unavailable_sources": unavailable_count,
            "plan_restricted_sources": plan_restricted_count,
            "sources": summaries,
        },
        "sources": {
            "understat": understat,
            "api_football": api_football,
        },
        "governance": {
            "official_fpl_remains_native_authority": True,
            "fpl_core_insights_remains_primary_epl_advanced_stats": True,
            "challenger_failure_is_fail_neutral": True,
            "optional_source_plan_restriction_is_not_engine_failure": True,
            "missing_enrichment_is_unavailable_not_zero": True,
            "network_fetch_owner": "ingestion",
        },
    }
