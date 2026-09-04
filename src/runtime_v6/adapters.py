from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .http_client import AcquisitionClient, utc_now

_SUCCESS_STATUSES = {"AVAILABLE", "NOT_MODIFIED"}


def _previous_data(previous: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return dict((previous or {}).get("data") or {})


def _merge_last_good(
    request_cfgs: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    previous: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    previous_data = _previous_data(previous)
    by_attempt = {str(row["request_id"]): row for row in attempts}
    merged: dict[str, dict[str, Any]] = {}

    for request_cfg in request_cfgs:
        request_id = str(request_cfg["id"])
        attempt = by_attempt.get(request_id) or {}
        status = attempt.get("status")

        if status == "AVAILABLE":
            row = dict(attempt)
            row["data_origin"] = "CURRENT_CYCLE"
            merged[request_id] = row
        elif status == "NOT_MODIFIED" and request_id in previous_data:
            row = dict(previous_data[request_id])
            row["data_origin"] = "REVALIDATED_CACHE"
            row["latest_attempt_status"] = status
            row["latest_attempt_checked_at"] = attempt.get("checked_at")
            row["revalidated_at"] = attempt.get("checked_at")
            row["etag"] = attempt.get("etag") or row.get("etag")
            row["last_modified"] = attempt.get("last_modified") or row.get("last_modified")
            merged[request_id] = row
        elif request_id in previous_data:
            row = dict(previous_data[request_id])
            row["data_origin"] = "LAST_GOOD_CACHE"
            row["latest_attempt_status"] = status
            row["latest_attempt_checked_at"] = attempt.get("checked_at")
            merged[request_id] = row

    return merged


def _source_health(
    source: dict[str, Any],
    attempts: list[dict[str, Any]],
    merged_data: dict[str, dict[str, Any]],
) -> tuple[str, str, str]:
    expected = len(source.get("requests") or [])
    succeeded_now = sum(row.get("status") in _SUCCESS_STATUSES for row in attempts)
    usable = len(merged_data)
    config_required = bool(attempts) and all(row.get("status") == "CONFIG_REQUIRED" for row in attempts)
    degraded_success = any(
        row.get("status") in _SUCCESS_STATUSES and row.get("health") != "GREEN"
        for row in attempts
    )

    if expected and succeeded_now == expected and not degraded_success:
        changed = any(row.get("content_changed") is True for row in attempts if row.get("status") == "AVAILABLE")
        return "GREEN", "AVAILABLE", "LIVE_CHANGED" if changed else "LIVE_UNCHANGED"
    if expected and succeeded_now == expected and degraded_success:
        return "AMBER", "PARTIAL", "LIVE_PARTIAL"
    if config_required:
        return "AMBER", "CONFIG_REQUIRED", "CONFIG_REQUIRED"
    if usable == expected and expected:
        return "AMBER", "PARTIAL", "STALE_CACHE"
    if usable > 0:
        return "AMBER", "PARTIAL", "PARTIAL_CACHE"
    if source.get("critical"):
        return "RED", "UNAVAILABLE", "MISSING"
    return "AMBER", "UNAVAILABLE", "MISSING"


def _failed_attempt(source: dict[str, Any], request_cfg: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {
        "request_id": request_cfg["id"],
        "status": "UNAVAILABLE",
        "health": "RED" if source.get("critical") else "AMBER",
        "url": str(request_cfg["url"]),
        "checked_at": utc_now(),
        "error": type(exc).__name__,
        "content_changed": None,
    }


def collect_http(
    source: dict[str, Any],
    client: AcquisitionClient,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    request_cfgs = list(source.get("requests") or [])
    previous_data = _previous_data(previous)

    if request_cfgs:
        request_workers = min(len(request_cfgs), max(1, client.request_workers))
        attempts_by_id: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=request_workers) as pool:
            futures = {
                pool.submit(
                    client.fetch,
                    source,
                    request_cfg,
                    previous=previous_data.get(str(request_cfg["id"])),
                ): request_cfg
                for request_cfg in request_cfgs
            }
            for future in as_completed(futures):
                request_cfg = futures[future]
                request_id = str(request_cfg["id"])
                try:
                    attempts_by_id[request_id] = future.result()
                except Exception as exc:
                    attempts_by_id[request_id] = _failed_attempt(source, request_cfg, exc)
        attempts = [attempts_by_id[str(request_cfg["id"])] for request_cfg in request_cfgs]
    else:
        attempts = []

    data = _merge_last_good(request_cfgs, attempts, previous)
    health, availability, effective_state = _source_health(source, attempts, data)
    elapsed = round((time.perf_counter() - started) * 1000.0, 3)

    return {
        "schema_version": 3,
        "source_id": source["id"],
        "source_name": source["name"],
        "category": source["category"],
        "adapter": source["adapter"],
        "critical": bool(source.get("critical")),
        "independence_group": source.get("independence_group"),
        "checked_at": utc_now(),
        "duration_ms": elapsed,
        "health": health,
        "availability": availability,
        "effective_state": effective_state,
        "changed": any(
            row.get("content_changed") is True
            for row in attempts
            if row.get("status") == "AVAILABLE"
        ),
        "attempts": attempts,
        "data": data,
        "coverage": {
            "expected_requests": len(request_cfgs),
            "successful_checks_this_cycle": sum(row.get("status") in _SUCCESS_STATUSES for row in attempts),
            "downloaded_this_cycle": sum(row.get("status") == "AVAILABLE" for row in attempts),
            "revalidated_not_modified": sum(row.get("status") == "NOT_MODIFIED" for row in attempts),
            "usable_requests": len(data),
            "degraded_successes": sum(
                row.get("status") in _SUCCESS_STATUSES and row.get("health") != "GREEN"
                for row in attempts
            ),
            "truncated_attempts": sum(row.get("truncated") is True for row in attempts),
        },
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "auth_bypass_used": False,
            "values_not_invented": True,
            "last_good_cache_is_explicit": True,
            "conditional_revalidation": client.conditional_revalidation,
            "request_failures_are_isolated": True,
        },
    }


def collect_official(
    source: dict[str, Any],
    client: AcquisitionClient,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = collect_http(source, client, previous)
    data = payload.get("data") or {}
    payload["official"] = {
        "bootstrap": (data.get("bootstrap") or {}).get("json"),
        "fixtures": (data.get("fixtures") or {}).get("json"),
        "event_status": (data.get("event_status") or {}).get("json"),
    }
    return payload


def collect_price_predictor(
    source: dict[str, Any],
    official_payload: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    bootstrap = ((official_payload.get("official") or {}).get("bootstrap") or {})
    elements = list(bootstrap.get("elements") or [])
    fields = [str(field) for field in source.get("fields") or []]
    rows = [{key: player.get(key) for key in fields if key in player} for player in elements]
    required = {"price_change_percent", "price_change_projections"}
    covered = sum(required.issubset(row.keys()) for row in rows)
    official_live = official_payload.get("health") == "GREEN"

    if rows and covered == len(rows) and official_live:
        health, availability, effective_state = "GREEN", "AVAILABLE", "LIVE_DERIVED"
    elif rows and covered == len(rows):
        health, availability, effective_state = "AMBER", "PARTIAL", "CACHED_DERIVED"
    elif rows:
        health, availability, effective_state = "AMBER", "PARTIAL", "PARTIAL_DERIVED"
    elif previous and (previous.get("data") or {}).get("players"):
        health, availability, effective_state = "AMBER", "UNAVAILABLE", "STALE_CACHE"
        rows = list((previous.get("data") or {}).get("players") or [])
        covered = int((previous.get("coverage") or {}).get("covered_player_count") or 0)
    else:
        health, availability, effective_state = "RED", "UNAVAILABLE", "MISSING"

    return {
        "schema_version": 3,
        "source_id": source["id"],
        "source_name": source["name"],
        "category": source["category"],
        "adapter": source["adapter"],
        "critical": bool(source.get("critical")),
        "independence_group": source.get("independence_group"),
        "checked_at": utc_now(),
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "health": health,
        "availability": availability,
        "effective_state": effective_state,
        "changed": None,
        "derived_from": source.get("derived_from"),
        "upstream_health": official_payload.get("health"),
        "upstream_effective_state": official_payload.get("effective_state"),
        "fields": fields,
        "data": {"players": rows},
        "coverage": {
            "player_count": len(rows),
            "covered_player_count": covered,
            "coverage_ratio": round(covered / len(rows), 6) if rows else 0.0,
        },
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "source": "OFFICIAL_FPL",
            "ui_scraping": False,
            "auth_bypass_used": False,
            "values_not_invented": True,
            "inherits_upstream_freshness": True,
        },
    }


def collect_source(
    source: dict[str, Any],
    client: AcquisitionClient,
    *,
    previous: dict[str, Any] | None = None,
    official_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adapter = source["adapter"]
    if adapter == "official_fpl":
        return collect_official(source, client, previous)
    if adapter == "official_price_predictor":
        if official_payload is None:
            raise ValueError("official price predictor requires official FPL payload")
        return collect_price_predictor(source, official_payload, previous)
    if adapter == "http":
        return collect_http(source, client, previous)
    raise ValueError(f"unsupported V6 adapter: {adapter}")
