from __future__ import annotations

from typing import Any

from .http_client import AcquisitionClient, utc_now

def _previous_request_hashes(previous: dict[str, Any] | None) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if not previous:
        return hashes
    for request_id, row in (previous.get("data") or {}).items():
        digest = row.get("sha256")
        if digest:
            hashes[str(request_id)] = str(digest)
    return hashes

def _merge_last_good(request_cfgs: list[dict[str, Any]], attempts: list[dict[str, Any]], previous: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    previous_data = dict((previous or {}).get("data") or {})
    by_attempt = {str(row["request_id"]): row for row in attempts}
    merged: dict[str, dict[str, Any]] = {}
    for request_cfg in request_cfgs:
        request_id = str(request_cfg["id"])
        attempt = by_attempt.get(request_id) or {}
        if attempt.get("status") == "AVAILABLE":
            row = dict(attempt)
            row["data_origin"] = "CURRENT_CYCLE"
            merged[request_id] = row
        elif request_id in previous_data:
            row = dict(previous_data[request_id])
            row["data_origin"] = "LAST_GOOD_CACHE"
            row["latest_attempt_status"] = attempt.get("status")
            row["latest_attempt_checked_at"] = attempt.get("checked_at")
            merged[request_id] = row
    return merged

def _source_health(source: dict[str, Any], attempts: list[dict[str, Any]], merged_data: dict[str, dict[str, Any]]) -> tuple[str, str, str]:
    expected = len(source.get("requests") or [])
    available_now = sum(row.get("status") == "AVAILABLE" for row in attempts)
    usable = len(merged_data)
    config_required = bool(attempts) and all(row.get("status") == "CONFIG_REQUIRED" for row in attempts)
    if expected and available_now == expected:
        return "GREEN", "AVAILABLE", "LIVE_CHANGED" if any(row.get("content_changed") for row in attempts) else "LIVE_UNCHANGED"
    if config_required:
        return "AMBER", "CONFIG_REQUIRED", "CONFIG_REQUIRED"
    if usable == expected and expected:
        return "AMBER", "PARTIAL", "STALE_CACHE"
    if usable > 0:
        return "AMBER", "PARTIAL", "PARTIAL_CACHE"
    if source.get("critical"):
        return "RED", "UNAVAILABLE", "MISSING"
    return "AMBER", "UNAVAILABLE", "MISSING"

def collect_http(source: dict[str, Any], client: AcquisitionClient, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    request_cfgs = list(source.get("requests") or [])
    previous_hashes = _previous_request_hashes(previous)
    attempts = [client.fetch(source, request_cfg, previous_hash=previous_hashes.get(str(request_cfg["id"]))) for request_cfg in request_cfgs]
    data = _merge_last_good(request_cfgs, attempts, previous)
    health, availability, effective_state = _source_health(source, attempts, data)
    return {"schema_version": 2, "source_id": source["id"], "source_name": source["name"], "category": source["category"], "adapter": source["adapter"], "critical": bool(source.get("critical")), "independence_group": source.get("independence_group"), "checked_at": utc_now(), "health": health, "availability": availability, "effective_state": effective_state, "changed": any(row.get("content_changed") is True for row in attempts if row.get("status") == "AVAILABLE"), "attempts": attempts, "data": data, "coverage": {"expected_requests": len(request_cfgs), "available_this_cycle": sum(row.get("status") == "AVAILABLE" for row in attempts), "usable_requests": len(data)}, "governance": {"data_only": True, "decision_authority": "NONE", "prediction_authority": "NONE", "optimizer_authority": "NONE", "auth_bypass_used": False, "values_not_invented": True, "last_good_cache_is_explicit": True}}

def collect_official(source: dict[str, Any], client: AcquisitionClient, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = collect_http(source, client, previous)
    data = payload.get("data") or {}
    payload["official"] = {"bootstrap": (data.get("bootstrap") or {}).get("json"), "fixtures": (data.get("fixtures") or {}).get("json"), "event_status": (data.get("event_status") or {}).get("json")}
    return payload

def collect_price_predictor(source: dict[str, Any], official_payload: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    bootstrap = ((official_payload.get("official") or {}).get("bootstrap") or {})
    elements = list(bootstrap.get("elements") or [])
    fields = [str(field) for field in source.get("fields") or []]
    rows = [{key: player.get(key) for key in fields if key in player} for player in elements]
    required = {"price_change_percent", "price_change_projections"}
    covered = sum(required.issubset(row.keys()) for row in rows)
    if rows and covered == len(rows):
        health, availability, effective_state = "GREEN", "AVAILABLE", "LIVE_DERIVED"
    elif rows:
        health, availability, effective_state = "AMBER", "PARTIAL", "PARTIAL_DERIVED"
    elif previous and (previous.get("data") or {}).get("players"):
        health, availability, effective_state = "AMBER", "UNAVAILABLE", "STALE_CACHE"
        rows = list((previous.get("data") or {}).get("players") or [])
        covered = int((previous.get("coverage") or {}).get("covered_player_count") or 0)
    else:
        health, availability, effective_state = "RED", "UNAVAILABLE", "MISSING"
    return {"schema_version": 2, "source_id": source["id"], "source_name": source["name"], "category": source["category"], "adapter": source["adapter"], "critical": bool(source.get("critical")), "independence_group": source.get("independence_group"), "checked_at": utc_now(), "health": health, "availability": availability, "effective_state": effective_state, "changed": None, "derived_from": source.get("derived_from"), "fields": fields, "data": {"players": rows}, "coverage": {"player_count": len(rows), "covered_player_count": covered, "coverage_ratio": round(covered / len(rows), 6) if rows else 0.0}, "governance": {"data_only": True, "decision_authority": "NONE", "prediction_authority": "NONE", "optimizer_authority": "NONE", "source": "OFFICIAL_FPL", "ui_scraping": False, "auth_bypass_used": False, "values_not_invented": True}}

def collect_source(source: dict[str, Any], client: AcquisitionClient, *, previous: dict[str, Any] | None = None, official_payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
