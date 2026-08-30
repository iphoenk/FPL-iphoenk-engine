from __future__ import annotations

from typing import Any

from src.v5.authenticated_official import collect_runtime
from src.v5.official_auth import expected_team_id
from src.v5.public_api import FetchSpec, fetch_many
from src.v5.request_plan import request_specs
from src.v5.sources.fusion import collect as collect_source_fusion


def handle(operation: str, payload: dict[str, Any]) -> Any:
    team_id = int(payload.get("team_id") or expected_team_id())
    if operation == "collect_base":
        data, health = fetch_many(request_specs("base_requests", {"team_id": team_id}))
        return {"payloads": data, "health": health}
    if operation == "collect_dynamic":
        tokens = {
            "team_id": team_id,
            "submitted_gw": payload.get("submitted_gw"),
            "scoring_gw": payload.get("scoring_gw"),
            "planning_gw": payload.get("planning_gw"),
        }
        data, health = fetch_many(request_specs("dynamic_requests", tokens))
        return {"payloads": data, "health": health}
    if operation == "collect_settlement_live":
        requested: set[int] = set()
        for raw in payload.get("gameweeks") or []:
            try:
                gw = int(raw)
            except (TypeError, ValueError):
                continue
            if gw > 0:
                requested.add(gw)
        gameweeks = sorted(requested)
        specs = {
            f"event_live_gw_{gw}": FetchSpec(route="event_live", params={"event": gw})
            for gw in gameweeks
        }
        data, health = fetch_many(specs) if specs else ({}, {})
        by_gw: dict[str, Any] = {}
        health_by_gw: dict[str, Any] = {}
        for gw in gameweeks:
            key = f"event_live_gw_{gw}"
            row = data.get(key)
            if isinstance(row, dict):
                by_gw[str(gw)] = row
            meta = health.get(key)
            health_by_gw[str(gw)] = meta if isinstance(meta, dict) else {"status": "UNAVAILABLE"}
        return {
            "contract": "V5_HISTORICAL_SETTLEMENT_EVENT_LIVE_V1",
            "requested_gameweeks": gameweeks,
            "request_count": len(gameweeks),
            "payloads_by_gw": by_gw,
            "fetched_gameweeks": sorted(int(key) for key in by_gw),
            "health_by_gw": health_by_gw,
            "governance": {
                "official_event_live_only": True,
                "deduplicate_gameweeks": True,
                "missing_payload_is_unavailable_not_zero": True,
                "network_owner": "ingestion",
                "settlement_owner": "evaluation",
            },
        }
    if operation == "collect_authenticated":
        return collect_runtime(payload.get("owned_ids") or ())
    if operation == "collect_enrichment":
        bootstrap = payload.get("bootstrap")
        if not isinstance(bootstrap, dict):
            raise ValueError("collect_enrichment requires bootstrap")
        fixtures = payload.get("fixtures")
        fixture_health: dict[str, Any] = {}
        if not isinstance(fixtures, list):
            fixture_payloads, fixture_health = fetch_many({"weather_fixtures": FetchSpec(route="fixtures")})
            fixtures = fixture_payloads.get("weather_fixtures") if isinstance(fixture_payloads.get("weather_fixtures"), list) else []
        result = collect_source_fusion(bootstrap, fixtures)
        result["weather_fixture_acquisition"] = {
            "status": "REUSED_CALLER_FIXTURES" if isinstance(payload.get("fixtures"), list) else "FETCHED_BY_INGESTION",
            "fixture_count": len(fixtures),
            "health": fixture_health,
            "governance": {"network_owner": "ingestion", "weather_shadow_only": True},
        }
        return result
    raise KeyError(f"unsupported ingestion operation: {operation}")
