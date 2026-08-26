from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any

from src.v5 import V5_VERSION
from src.v5.config_cache import load_json_config
from src.v5.official_auth import expected_team_id
from src.v5.service_client import invoke_envelope, invoke_parallel_envelopes
from src.v5.service_registry import registry as service_registry

ORCHESTRATOR_CONFIG = "config/v5_orchestrator_registry.json"
RUNNER_CONFIG = "config/v5_runner_registry.json"


def _cfg() -> dict[str, Any]:
    return load_json_config(ORCHESTRATOR_CONFIG)


def _route(name: str) -> tuple[str, str]:
    raw = _cfg()["routing"].get(name)
    if not isinstance(raw, dict):
        raise KeyError(f"unknown V5 orchestrator route: {name}")
    return str(raw["service"]), str(raw["operation"])


def _call(name: str, payload: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    service, operation = _route(name)
    return invoke_envelope(service, operation, payload, correlation_id=correlation_id)


def _metric(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "service_id": envelope.get("service_id"),
        "operation": envelope.get("operation"),
        "service_compute_ms": envelope.get("elapsed_ms"),
        "round_trip_ms": envelope.get("round_trip_ms"),
        "transport_overhead_ms": envelope.get("transport_overhead_ms"),
    }


def _parallel_metrics(envelopes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {name: _metric(envelope) for name, envelope in envelopes.items()}


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation != "run":
        raise KeyError(f"unsupported orchestrator operation: {operation}")

    runner_cfg = load_json_config(RUNNER_CONFIG)
    mode = str(payload.get("mode") or runner_cfg["default_mode"])
    if mode not in {str(x) for x in runner_cfg["modes"]}:
        raise ValueError(f"unsupported V5 runner mode: {mode}")
    correlation_id = str(payload.get("correlation_id") or uuid.uuid4().hex)
    team_id = int(payload.get("team_id") or expected_team_id())
    persist = bool(payload.get("persist", True))
    wall_started = perf_counter()
    performance: dict[str, Any] = {}

    base_env = _call("base_collection", {"team_id": team_id}, correlation_id)
    performance["base_collection"] = _metric(base_env)
    base_result = base_env["data"]
    base = base_result["payloads"]
    bootstrap = base.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise RuntimeError("V5 microservice FAIL CLOSED: bootstrap unavailable")

    context_env = _call("event_context", {"bootstrap": bootstrap}, correlation_id)
    performance["event_context"] = _metric(context_env)
    context = context_env["data"]

    dynamic_service, dynamic_operation = _route("dynamic_collection")
    auth_service, auth_operation = _route("authenticated_collection")
    runtime_envs = invoke_parallel_envelopes(
        {
            "dynamic_collection": (
                dynamic_service,
                dynamic_operation,
                {
                    "team_id": team_id,
                    "submitted_gw": context.get("submitted_gw"),
                    "scoring_gw": context.get("scoring_gw"),
                    "planning_gw": context.get("planning_gw"),
                },
            ),
            "authenticated_collection": (auth_service, auth_operation, {}),
        },
        correlation_id=correlation_id,
    )
    performance["runtime_overlay"] = _parallel_metrics(runtime_envs)
    dynamic_result = runtime_envs["dynamic_collection"]["data"]
    auth_runtime = runtime_envs["authenticated_collection"]["data"]

    truth_env = _call(
        "truth_assembly",
        {
            "bootstrap": bootstrap,
            "base": base,
            "dynamic": dynamic_result["payloads"],
            "auth_runtime": auth_runtime,
        },
        correlation_id,
    )
    performance["truth_assembly"] = _metric(truth_env)
    truth = truth_env["data"]
    owned_ids = (truth.get("team") or {}).get("owned_ids") or []

    previous_env = _call(
        "price_state_read",
        {"name": "price_trajectory", "default": {}},
        correlation_id,
    )
    performance["price_state_read"] = _metric(previous_env)

    price_service, price_operation = _route("price_build")
    prediction_service, prediction_operation = _route("prediction_build")
    intelligence_envs = invoke_parallel_envelopes(
        {
            "price": (
                price_service,
                price_operation,
                {
                    "bootstrap": bootstrap,
                    "previous_state": previous_env["data"] or {},
                    "owned_ids": owned_ids,
                },
            ),
            "prediction": (
                prediction_service,
                prediction_operation,
                {
                    "bootstrap": bootstrap,
                    "fixtures": base.get("fixtures") or [],
                    "stats_gw": context.get("current_gw") or context.get("last_finished_gw"),
                },
            ),
        },
        correlation_id=correlation_id,
    )
    performance["intelligence"] = _parallel_metrics(intelligence_envs)
    price_bundle = intelligence_envs["price"]["data"]
    prediction = intelligence_envs["prediction"]["data"]

    decision_env = _call(
        "decision_build",
        {"truth": truth, "price": price_bundle, "prediction": prediction},
        correlation_id,
    )
    performance["decision"] = _metric(decision_env)
    decision = decision_env["data"]

    limits = runner_cfg["summary_limits"]
    price_rows = price_bundle.get("prices") if isinstance(price_bundle.get("prices"), dict) else {}
    alerts = price_bundle.get("alerts") if isinstance(price_bundle.get("alerts"), dict) else {}
    auth_summary = auth_runtime.get("summary") if isinstance(auth_runtime.get("summary"), dict) else {}
    snapshot = {
        "schema_version": int(runner_cfg["snapshot"]["schema_version"]),
        "engine_version": V5_VERSION,
        "runtime_architecture": service_registry()["architecture"],
        "runner_status": runner_cfg["status"],
        "mode": mode,
        "correlation_id": correlation_id,
        "team_id": team_id,
        "phase": truth.get("context"),
        "squad_authority": (truth.get("team") or {}).get("authority"),
        "team_summary": truth.get("team"),
        "live_summary": truth.get("live"),
        "price_summary": {
            "confirmed_changes": price_rows.get("confirmed_changes", []),
            "top_rise_risk": price_rows.get("top_rise_risk", [])[: int(limits["price_rise_risk"])],
            "top_fall_risk": price_rows.get("top_fall_risk", [])[: int(limits["price_fall_risk"])],
            "alerts": alerts.get("alerts", [])[: int(limits["price_alerts"])],
        },
        "prediction_summary": {
            "model_version": prediction.get("model_version"),
            "player_count": len(prediction.get("players", []) or []),
            "network_contract": prediction.get("network_contract", {}),
        },
        "decision_summary": decision,
        "endpoint_health": {
            "base": base_result.get("health", {}),
            "dynamic": dynamic_result.get("health", {}),
        },
        "authenticated_official": {
            "state": auth_summary.get("state"),
            "verified_entry": auth_summary.get("verified_entry"),
            "endpoint_health": auth_summary.get("endpoint_health", {}),
            "raw_authenticated_payload_persisted": False,
        },
        "governance": {
            "production_promotion_allowed": bool(runner_cfg["snapshot"].get("production_promotion_allowed", False)),
            "microservices_required": True,
            "raw_authenticated_payload_persisted": False,
        },
    }

    if persist:
        artifact_service, artifact_operation = _route("artifact_write")
        artifact_map = _cfg()["artifact_mapping"]
        artifact_envs = invoke_parallel_envelopes(
            {
                "prices": (
                    artifact_service,
                    artifact_operation,
                    {"name": str(artifact_map["prices"]), "data": price_bundle.get("prices", {})},
                ),
                "price_trajectory": (
                    artifact_service,
                    artifact_operation,
                    {"name": str(artifact_map["price_trajectory"]), "data": price_bundle.get("trajectory_state", {})},
                ),
                "price_alerts": (
                    artifact_service,
                    artifact_operation,
                    {"name": str(artifact_map["price_alerts"]), "data": price_bundle.get("alerts", {})},
                ),
                "predictions": (
                    artifact_service,
                    artifact_operation,
                    {"name": str(artifact_map["predictions"]), "data": prediction},
                ),
            },
            correlation_id=correlation_id,
        )
        performance["artifact_persistence"] = _parallel_metrics(artifact_envs)
        gw = context.get("submitted_gw") or context.get("planning_gw")
        snapshot_env = _call(
            "snapshot_write",
            {"snapshot": snapshot, "gw": gw},
            correlation_id,
        )
        performance["snapshot_write"] = _metric(snapshot_env)
        snapshot["files"] = snapshot_env["data"]

    performance["orchestrator_wall_ms"] = round((perf_counter() - wall_started) * 1000.0, 3)
    snapshot["service_performance"] = performance
    return snapshot
