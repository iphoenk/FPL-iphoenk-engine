from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5.authenticated_official import collect_runtime
from src.v5.event_context import build_event_context
from src.v5.identity import build_index, resolve_many
from src.v5.live_scoring import personalized_live_score
from src.v5.official_auth import expected_team_id
from src.v5.persistence import persistence_metadata, read_artifact, write_artifact, write_snapshot
from src.v5.prediction_bridge import build_predictions
from src.v5.price_service import build_price_snapshot
from src.v5.public_api import fetch_many
from src.v5.request_plan import request_specs
from src.v5.service_client import invoke, invoke_parallel
from src.v5.team_service import build_team_state
from src.v5.config_cache import load_json_config


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _context_dict(context) -> dict[str, Any]:
    return {
        "current_gw": context.current_gw,
        "next_gw": context.next_gw,
        "last_finished_gw": context.last_finished_gw,
        "planning_gw": context.planning_gw,
        "submitted_gw": context.submitted_gw,
        "scoring_gw": context.scoring_gw,
        "deadline_time": context.deadline_time,
        "is_live_event": context.is_live_event,
        "phase": context.phase.value,
    }


def _locked_squad() -> dict:
    cfg = load_json_config("config/v5_squad_registry.json")
    return load_json_config(str(cfg["locked_squad_config"]))


def ingestion_adapter(operation: str, payload: dict[str, Any]) -> Any:
    team_id = int(payload.get("team_id") or expected_team_id())
    if operation == "collect_base":
        specs = request_specs("base_requests", {"team_id": team_id})
        data, health = fetch_many(specs)
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
    if operation == "collect_authenticated":
        return collect_runtime(payload.get("owned_ids") or ())
    raise KeyError(f"unsupported ingestion operation: {operation}")


def truth_adapter(operation: str, payload: dict[str, Any]) -> Any:
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise ValueError("truth service requires bootstrap")
    if operation == "context":
        return _context_dict(build_event_context(bootstrap, now=_dt(payload.get("now"))))
    if operation == "resolve":
        index = build_index(bootstrap)
        return list(resolve_many(payload.get("element_ids") or (), index))
    if operation != "assemble":
        raise KeyError(f"unsupported truth operation: {operation}")

    context = build_event_context(bootstrap, now=_dt(payload.get("now")))
    identity = build_index(bootstrap)
    auth_runtime = payload.get("auth_runtime") if isinstance(payload.get("auth_runtime"), dict) else {}
    dynamic = payload.get("dynamic") if isinstance(payload.get("dynamic"), dict) else {}
    base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
    team = build_team_state(
        phase=context.phase,
        bootstrap=bootstrap,
        identity=identity,
        locked_squad=payload.get("locked_squad") if isinstance(payload.get("locked_squad"), dict) else _locked_squad(),
        authenticated_my_team=auth_runtime.get("my_team") if isinstance(auth_runtime.get("my_team"), dict) else None,
        submitted_picks=dynamic.get("submitted_picks") if isinstance(dynamic.get("submitted_picks"), dict) else None,
        transfers=base.get("entry_transfers") if isinstance(base.get("entry_transfers"), list) else [],
        entry=base.get("entry") if isinstance(base.get("entry"), dict) else None,
    )
    live = personalized_live_score(
        picks=dynamic.get("submitted_picks") if isinstance(dynamic.get("submitted_picks"), dict) else None,
        event_live=dynamic.get("event_live") if isinstance(dynamic.get("event_live"), dict) else None,
        identity=identity,
        scoring_gw=context.scoring_gw,
        is_live_event=context.is_live_event,
    )
    return {"context": _context_dict(context), "team": team, "live": live}


def price_adapter(operation: str, payload: dict[str, Any]) -> Any:
    if operation != "build":
        raise KeyError(f"unsupported price operation: {operation}")
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise ValueError("price service requires bootstrap")
    return build_price_snapshot(
        bootstrap,
        previous_state=payload.get("previous_state") if isinstance(payload.get("previous_state"), dict) else {},
        owned_ids=payload.get("owned_ids") or (),
        now=_dt(payload.get("now")),
    )


def prediction_adapter(operation: str, payload: dict[str, Any]) -> Any:
    if operation != "build":
        raise KeyError(f"unsupported prediction operation: {operation}")
    bootstrap = payload.get("bootstrap")
    fixtures = payload.get("fixtures")
    if not isinstance(bootstrap, dict) or not isinstance(fixtures, list):
        raise ValueError("prediction service requires bootstrap and fixtures")
    return build_predictions(
        bootstrap,
        fixtures,
        str(payload.get("generated_at") or datetime.now(timezone.utc).isoformat()),
        stats_gw=int(payload["stats_gw"]) if payload.get("stats_gw") is not None else None,
    )


def decision_adapter(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE_ALPHA_BRIDGE",
            "note": "V5 service boundary is active; full DSS/optimizer service migration remains in progress.",
        }
    if operation != "summarize":
        raise KeyError(f"unsupported decision operation: {operation}")
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
    return {
        "status": "BRIDGE_ONLY_NO_PRODUCTION_RECOMMENDATION",
        "team_authority": (truth.get("team") or {}).get("authority"),
        "prediction_model": prediction.get("model_version"),
        "prediction_player_count": len(prediction.get("players", []) or []),
        "price_alert_count": len((price.get("alerts") or {}).get("alerts", []) or []),
        "production_recommendation": None,
    }


def snapshot_adapter(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "metadata":
        return persistence_metadata()
    if operation == "read":
        return read_artifact(str(payload["name"]), payload.get("default"))
    if operation == "write":
        path = write_artifact(str(payload["name"]), payload.get("data"))
        return {"path": str(path)}
    if operation == "snapshot":
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot service requires snapshot object")
        return write_snapshot(snapshot, gw=int(payload["gw"]) if payload.get("gw") is not None else None)
    raise KeyError(f"unsupported snapshot operation: {operation}")


def orchestrator_adapter(operation: str, payload: dict[str, Any]) -> Any:
    if operation != "run":
        raise KeyError(f"unsupported orchestrator operation: {operation}")
    correlation = str(payload.get("correlation_id") or "") or None
    team_id = int(payload.get("team_id") or expected_team_id())
    base_result = invoke("ingestion", "collect_base", {"team_id": team_id}, correlation_id=correlation)
    base = base_result["payloads"]
    bootstrap = base.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise RuntimeError("V5 microservice FAIL CLOSED: bootstrap unavailable")
    context = invoke("truth", "context", {"bootstrap": bootstrap}, correlation_id=correlation)
    parallel = invoke_parallel(
        {
            "dynamic": (
                "ingestion",
                "collect_dynamic",
                {
                    "team_id": team_id,
                    "submitted_gw": context.get("submitted_gw"),
                    "scoring_gw": context.get("scoring_gw"),
                    "planning_gw": context.get("planning_gw"),
                },
            ),
            "auth": ("ingestion", "collect_authenticated", {}),
        },
        correlation_id=correlation,
    )
    dynamic_result = parallel["dynamic"]
    auth_runtime = parallel["auth"]
    truth = invoke(
        "truth",
        "assemble",
        {
            "bootstrap": bootstrap,
            "base": base,
            "dynamic": dynamic_result["payloads"],
            "auth_runtime": auth_runtime,
        },
        correlation_id=correlation,
    )
    owned_ids = (truth.get("team") or {}).get("owned_ids") or []
    previous_price_state = invoke(
        "snapshot", "read", {"name": "price_trajectory", "default": {}}, correlation_id=correlation
    )
    intelligence = invoke_parallel(
        {
            "price": (
                "price",
                "build",
                {"bootstrap": bootstrap, "previous_state": previous_price_state, "owned_ids": owned_ids},
            ),
            "prediction": (
                "prediction",
                "build",
                {
                    "bootstrap": bootstrap,
                    "fixtures": base.get("fixtures") or [],
                    "stats_gw": context.get("current_gw") or context.get("last_finished_gw"),
                },
            ),
        },
        correlation_id=correlation,
    )
    decision = invoke(
        "decision",
        "summarize",
        {"truth": truth, "price": intelligence["price"], "prediction": intelligence["prediction"]},
        correlation_id=correlation,
    )
    snapshot = {
        "engine_version": "5.0.0-alpha.1",
        "runtime_architecture": "microservices",
        "team_id": team_id,
        "phase": truth.get("context"),
        "team_summary": truth.get("team"),
        "live_summary": truth.get("live"),
        "price_summary": intelligence["price"],
        "prediction_summary": {
            "model_version": intelligence["prediction"].get("model_version"),
            "player_count": len(intelligence["prediction"].get("players", []) or []),
        },
        "decision_summary": decision,
        "service_health": {"ingestion": base_result.get("health", {}), "dynamic": dynamic_result.get("health", {})},
    }
    if payload.get("persist", True):
        gw = context.get("submitted_gw") or context.get("planning_gw")
        snapshot["files"] = invoke(
            "snapshot", "snapshot", {"snapshot": snapshot, "gw": gw}, correlation_id=correlation
        )
    return snapshot
