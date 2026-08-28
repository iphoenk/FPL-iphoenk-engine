from __future__ import annotations

from typing import Any

from src.v5.authenticated_official import collect_runtime
from src.v5.config_cache import load_json_config
from src.v5.official_auth import expected_team_id
from src.v5.official_history import finished_gameweeks, reconcile_historical_submissions
from src.v5.public_api import FetchSpec, fetch_many
from src.v5.request_plan import request_specs
from src.v5.sources.fusion import collect as collect_source_fusion

RUNNER_CONFIG = "config/v5_runner_registry.json"


def _historical_cfg() -> dict[str, Any]:
    raw = load_json_config(RUNNER_CONFIG).get("historical_submitted")
    return raw if isinstance(raw, dict) else {}


def _historical_submitted(team_id: int, *, max_gws: int, proxy_gws: list[int]) -> dict[str, Any]:
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
        retrospective_proxy_gameweeks=proxy_gws,
    )


def _disabled_history() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract": "official_historical_submission_v1",
        "status": "DISABLED",
        "coverage": {"requested": 0, "available": 0, "complete": False},
        "gameweeks": {},
        "governance": {
            "historical_state_never_overrides_current_pre_deadline_authority": True,
            "retrospective_proxy_is_decision_neutral": True,
        },
    }


def _settlement_actuals(gameweeks: list[int]) -> dict[str, Any]:
    unique = sorted({int(gw) for gw in gameweeks if int(gw) > 0})
    maximum = max(1, int(_historical_cfg().get("max_historical_gameweeks") or 5))
    bounded = unique[-maximum:]
    specs = {
        f"settlement_event_live_gw_{gw}": FetchSpec(route="event_live", params={"event": gw})
        for gw in bounded
    }
    if specs:
        data, health = fetch_many(specs)
    else:
        data, health = {}, {}
    by_gw: dict[str, Any] = {}
    unavailable: list[int] = []
    for gw in bounded:
        key = f"settlement_event_live_gw_{gw}"
        value = data.get(key)
        if isinstance(value, dict) and isinstance(value.get("elements"), list):
            by_gw[str(gw)] = value
        else:
            unavailable.append(gw)
    return {
        "schema_version": 1,
        "contract": "official_event_live_settlement_actuals_v1",
        "authority": "OFFICIAL_FPL_EVENT_LIVE_POST_GW",
        "requested_gameweeks": bounded,
        "available_gameweeks": sorted(int(gw) for gw in by_gw),
        "unavailable_gameweeks": unavailable,
        "event_live_by_gw": by_gw,
        "health": health,
        "governance": {
            "caller_supplies_only_frozen_unsettled_finished_gameweeks": True,
            "collection_is_bounded_by_historical_window": True,
            "evaluation_service_does_not_fetch_network": True,
            "missing_actual_is_unavailable_not_zero": True,
        },
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
        hcfg = _historical_cfg()
        enabled = bool(hcfg.get("enabled", True))
        max_gws = max(1, int(hcfg.get("max_historical_gameweeks") or 5))
        proxy_gws = [int(value) for value in (hcfg.get("retrospective_proxy_gameweeks") or [1]) if int(value) > 0]
        historical = _historical_submitted(team_id, max_gws=max_gws, proxy_gws=proxy_gws) if enabled else _disabled_history()
        data["historical_entry"] = historical
        health["historical_entry"] = {
            "status": historical.get("status"),
            "coverage": historical.get("coverage"),
            "decision_neutral": True,
        }
        return {"payloads": data, "health": health}
    if operation == "collect_settlement_actuals":
        raw = payload.get("gameweeks")
        gameweeks = [int(value) for value in raw] if isinstance(raw, list) else []
        return _settlement_actuals(gameweeks)
    if operation == "collect_historical_submitted":
        hcfg = _historical_cfg()
        max_gws = max(1, int(payload.get("max_historical_gameweeks") or hcfg.get("max_historical_gameweeks") or 5))
        raw_proxy = payload.get("retrospective_proxy_gameweeks")
        raw_proxy = raw_proxy if isinstance(raw_proxy, list) else hcfg.get("retrospective_proxy_gameweeks") or [1]
        proxy_gws = [int(value) for value in raw_proxy if int(value) > 0]
        return _historical_submitted(team_id, max_gws=max_gws, proxy_gws=proxy_gws)
    if operation == "collect_authenticated":
        return collect_runtime(payload.get("owned_ids") or ())
    if operation == "collect_enrichment":
        bootstrap = payload.get("bootstrap")
        if not isinstance(bootstrap, dict):
            raise ValueError("collect_enrichment requires bootstrap")
        return collect_source_fusion(bootstrap)
    raise KeyError(f"unsupported ingestion operation: {operation}")
