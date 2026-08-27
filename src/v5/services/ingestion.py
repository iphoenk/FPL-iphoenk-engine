from __future__ import annotations

from typing import Any

from src.v5.authenticated_official import collect_runtime
from src.v5.official_auth import expected_team_id
from src.v5.official_history import finished_gameweeks, reconcile_historical_submissions
from src.v5.public_api import FetchSpec, fetch_many
from src.v5.request_plan import request_specs
from src.v5.sources.fusion import collect as collect_source_fusion


def _historical_submitted(team_id: int, *, max_gws: int = 5, proxy_gws: list[int] | None = None) -> dict[str, Any]:
    history_data, history_health = fetch_many(
        {"entry_history_reconciliation": FetchSpec(route="entry_history", params={"team_id": team_id})}
    )
    entry_history = history_data.get("entry_history_reconciliation")
    entry_history = entry_history if isinstance(entry_history, dict) else {}
    wanted = finished_gameweeks(entry_history)[-max(1, int(max_gws)) :]
    specs = {
        f"historical_picks_gw_{gw}": FetchSpec(route="entry_picks", params={"team_id": team_id, "event": gw})
        for gw in wanted
    }
    if specs:
        picks_data, picks_health = fetch_many(specs)
    else:
        picks_data, picks_health = {}, {}
    source_health = {**history_health, **picks_health}
    picks_by_gw = {gw: picks_data.get(f"historical_picks_gw_{gw}") for gw in wanted}
    return reconcile_historical_submissions(
        team_id=team_id,
        entry_history=entry_history,
        picks_by_gw=picks_by_gw,
        source_health=source_health,
        max_historical_gameweeks=max_gws,
        retrospective_proxy_gameweeks=proxy_gws or [1],
    )


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
        if bool(payload.get("official_history_reconciliation", True)):
            historical = _historical_submitted(
                team_id,
                max_gws=int(payload.get("max_historical_gameweeks") or 5),
                proxy_gws=payload.get("retrospective_proxy_gameweeks") if isinstance(payload.get("retrospective_proxy_gameweeks"), list) else [1],
            )
        else:
            historical = {
                "schema_version": 1,
                "contract": "official_historical_submission_v1",
                "status": "DISABLED",
                "coverage": {"requested": 0, "available": 0, "complete": False},
                "gameweeks": {},
                "governance": {"retrospective_proxy_is_decision_neutral": True},
            }
        data["historical_entry"] = historical
        health["historical_entry"] = {
            "status": historical.get("status"),
            "coverage": historical.get("coverage"),
            "decision_neutral": True,
        }
        return {"payloads": data, "health": health}
    if operation == "collect_historical_submitted":
        return _historical_submitted(
            team_id,
            max_gws=int(payload.get("max_historical_gameweeks") or 5),
            proxy_gws=payload.get("retrospective_proxy_gameweeks") if isinstance(payload.get("retrospective_proxy_gameweeks"), list) else [1],
        )
    if operation == "collect_authenticated":
        return collect_runtime(payload.get("owned_ids") or ())
    if operation == "collect_enrichment":
        bootstrap = payload.get("bootstrap")
        if not isinstance(bootstrap, dict):
            raise ValueError("collect_enrichment requires bootstrap")
        return collect_source_fusion(bootstrap)
    raise KeyError(f"unsupported ingestion operation: {operation}")
