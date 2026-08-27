from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

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


def _empty_source(source_id: str, status: str, season: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    payload_key = "players" if source_id == "understat" else "fixtures"
    result: dict[str, Any] = {
        "source": source_id,
        "status": status,
        "availability_class": status,
        payload_key: [],
        "season": season,
        "governance": {
            "fail_neutral": True,
            "enablement_authority": "config/sources/registry.json",
        },
    }
    if reason:
        result["reason"] = reason
    return result


def _safe_collect(source_id: str, collector: Callable[[], dict[str, Any]], season: dict[str, Any]) -> dict[str, Any]:
    try:
        result = collector()
        if not isinstance(result, dict):
            return _empty_source(source_id, "UNAVAILABLE", season, reason="collector_returned_non_object")
        return result
    except Exception as exc:
        return _empty_source(
            source_id,
            "UNAVAILABLE",
            season,
            reason=f"collector_exception:{type(exc).__name__}:{exc}",
        )


def _canonical_worker_limit(cfg: dict[str, Any]) -> int:
    registry_path = str(cfg.get("source_registry") or "").strip()
    if not registry_path:
        return 1
    registry = load_json_config(registry_path)
    policy = registry.get("policy") if isinstance(registry.get("policy"), dict) else {}
    return max(1, int(policy.get("max_workers") or 1))


def _aggregate_status(summaries: dict[str, dict[str, Any]], enabled_sources: list[str]) -> str:
    rows = [summaries[source_id] for source_id in enabled_sources if source_id in summaries]
    if any(str(row.get("status") or "") == "ACTIVE" for row in rows):
        return "ACTIVE"
    if any(str(row.get("status") or "") == "DEGRADED" for row in rows):
        return "DEGRADED"
    if rows and all(
        str(row.get("status") or "") == "UNAVAILABLE" and row.get("fail_neutral") is True
        for row in rows
    ):
        return "DEGRADED"
    return "UNAVAILABLE"


def collect(bootstrap: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    season = season_authority()
    source_cfgs = {
        "understat": cfg.get("understat") if isinstance(cfg.get("understat"), dict) else {},
        "api_football": cfg.get("api_football") if isinstance(cfg.get("api_football"), dict) else {},
    }

    results: dict[str, dict[str, Any]] = {}
    jobs: dict[str, Callable[[], dict[str, Any]]] = {}
    if bool(source_cfgs["understat"].get("enabled")):
        jobs["understat"] = collect_understat
    else:
        results["understat"] = _empty_source("understat", "DISABLED", season)

    if bool(source_cfgs["api_football"].get("enabled")):
        jobs["api_football"] = lambda: collect_api_football(bootstrap)
    else:
        results["api_football"] = _empty_source("api_football", "DISABLED", season)

    configured_workers = _canonical_worker_limit(cfg)
    workers_used = min(configured_workers, len(jobs)) if jobs else 0
    if workers_used == 1:
        source_id, collector = next(iter(jobs.items()))
        results[source_id] = _safe_collect(source_id, collector, season)
    elif workers_used > 1:
        with ThreadPoolExecutor(max_workers=workers_used) as pool:
            futures = {
                source_id: pool.submit(_safe_collect, source_id, collector, season)
                for source_id, collector in jobs.items()
            }
            for source_id, future in futures.items():
                results[source_id] = future.result()

    understat = results["understat"]
    api_football = results["api_football"]
    summaries = {
        "understat": _source_summary(understat),
        "api_football": _source_summary(api_football),
    }
    statuses = [str(row.get("status") or "UNAVAILABLE") for row in summaries.values()]
    active_count = sum(status == "ACTIVE" for status in statuses)
    degraded_count = sum(status == "DEGRADED" for status in statuses)
    unavailable_count = sum(status in {"UNAVAILABLE", "DISABLED"} for status in statuses)
    plan_restricted_count = sum(str(row.get("availability_class") or "") == "PLAN_RESTRICTED" for row in summaries.values())
    enabled_sources = sorted(jobs)
    fail_neutral_unavailable_count = sum(
        str(summaries[source_id].get("status") or "") == "UNAVAILABLE"
        and summaries[source_id].get("fail_neutral") is True
        for source_id in enabled_sources
    )
    overall = _aggregate_status(summaries, enabled_sources)
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
            "fail_neutral_unavailable_sources": fail_neutral_unavailable_count,
            "enabled_sources": enabled_sources,
            "disabled_sources": sorted(source_id for source_id, row in source_cfgs.items() if not bool(row.get("enabled"))),
            "configured_max_workers": configured_workers,
            "workers_used": workers_used,
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
            "aggregate_degraded_when_only_enabled_sources_are_fail_neutral_unavailable": True,
            "provider_unavailable_status_is_not_rewritten": True,
            "missing_enrichment_is_unavailable_not_zero": True,
            "network_fetch_owner": "ingestion",
            "source_enablement_authority": "config/sources/registry.json",
            "source_runtime_configuration_authority": "config/sources/registry.json",
            "disabled_sources_are_not_executed": True,
        },
    }
