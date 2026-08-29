from __future__ import annotations

from typing import Any

from src.v5.authenticated_official import collect_runtime
from src.v5.official_auth import expected_team_id
from src.v5.public_api import FetchSpec, fetch_many
from src.v5.request_plan import request_specs
from src.v5.sources.fusion import collect as collect_source_fusion


def _event_live_history(gameweeks: Any) -> dict[str, Any]:
    requested = sorted({int(value) for value in (gameweeks or []) if int(value) > 0})
    if not requested:
        return {"payloads": {}, "health": {}, "requested_gameweeks": []}
    specs = {
        f"gw_{gw}": FetchSpec(route="event_live", params={"event": gw})
        for gw in requested
    }
    data, health = fetch_many(specs)
    return {
        "payloads": {str(gw): data.get(f"gw_{gw}") for gw in requested},
        "health": {str(gw): health.get(f"gw_{gw}") or {} for gw in requested},
        "requested_gameweeks": requested,
    }


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
    if operation == "collect_event_live_history":
        return _event_live_history(payload.get("gameweeks"))
    if operation == "collect_authenticated":
        return collect_runtime(payload.get("owned_ids") or ())
    if operation == "collect_enrichment":
        bootstrap = payload.get("bootstrap")
        if not isinstance(bootstrap, dict):
            raise ValueError("collect_enrichment requires bootstrap")
        return collect_source_fusion(bootstrap)
    raise KeyError(f"unsupported ingestion operation: {operation}")
