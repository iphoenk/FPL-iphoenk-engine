from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any

from src.v5 import V5_VERSION
from src.v5.config_cache import load_json_config
from src.v5.degraded_mode import fallback_for
from src.v5.official_auth import expected_team_id
from src.v5.service_client import invoke_envelope, invoke_parallel_envelopes, invoke_parallel_outcomes
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
        "transport_attempts": envelope.get("transport_attempts"),
        "transport_retry_policy": envelope.get("transport_retry_policy"),
        "transport_circuit": envelope.get("transport_circuit"),
    }


def _degraded_metric(outcome: dict[str, Any], degraded_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "service_id": outcome.get("service_id"),
        "operation": outcome.get("operation"),
        "status": "DEGRADED",
        "fallback_behavior": degraded_context.get("behavior"),
        "blocks_unqualified_go": degraded_context.get("blocks_unqualified_go"),
        "error_type": outcome.get("error_type"),
        "error": outcome.get("error"),
    }


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation != "run":
        raise KeyError(f"unsupported orchestrator operation: {operation}")
    runner_cfg = load_json_config(RUNNER_CONFIG)
    mode = str(payload.get("mode") or runner_cfg["default_mode"])
    if mode not in {str(value) for value in runner_cfg["modes"]}:
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
    context = context_env["data"]
    performance["event_context"] = _metric(context_env)

    dynamic_service, dynamic_operation = _route("dynamic_collection")
    auth_service, auth_operation = _route("authenticated_collection")
    runtime = invoke_parallel_envelopes(
        {
            "dynamic": (
                dynamic_service,
                dynamic_operation,
                {
                    "team_id": team_id,
                    "submitted_gw": context.get("submitted_gw"),
                    "scoring_gw": context.get("scoring_gw"),
                    "planning_gw": context.get("planning_gw"),
                },
            ),
            "auth": (auth_service, auth_operation, {}),
        },
        correlation_id=correlation_id,
    )
    performance["runtime_overlay"] = {key: _metric(value) for key, value in runtime.items()}
    dynamic_result, auth_runtime = runtime["dynamic"]["data"], runtime["auth"]["data"]

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
    truth = truth_env["data"]
    performance["truth_assembly"] = _metric(truth_env)
    if not isinstance(truth.get("rules"), dict):
        raise RuntimeError("V5 microservice FAIL CLOSED: truth rules unavailable")

    read_service, read_operation = _route("artifact_read")
    states = invoke_parallel_envelopes(
        {
            "price_trajectory": (read_service, read_operation, {"name": "price_trajectory", "default": {}}),
            "prediction_ledger": (
                read_service,
                read_operation,
                {"name": "prediction_ledger", "default": {"schema_version": 1, "records": {}}},
            ),
            "challenger_observations": (
                read_service,
                read_operation,
                {"name": "challenger_observations", "default": {"schema_version": 1, "observations": []}},
            ),
        },
        correlation_id=correlation_id,
    )
    performance["state_hydration"] = {key: _metric(value) for key, value in states.items()}

    price_service, price_operation = _route("price_build")
    prediction_service, prediction_operation = _route("prediction_build")
    prediction_horizon = int(runner_cfg["prediction_horizon_gws"])
    intelligence_outcomes = invoke_parallel_outcomes(
        {
            "price": (
                price_service,
                price_operation,
                {
                    "bootstrap": bootstrap,
                    "previous_state": states["price_trajectory"]["data"] or {},
                    "owned_ids": (truth.get("team") or {}).get("owned_ids") or [],
                },
            ),
            "prediction": (
                prediction_service,
                prediction_operation,
                {
                    "bootstrap": bootstrap,
                    "fixtures": base.get("fixtures") or [],
                    "rules": truth["rules"],
                    "planning_gw": context.get("planning_gw"),
                    "horizon": prediction_horizon,
                },
            ),
        },
        correlation_id=correlation_id,
    )

    prediction_outcome = intelligence_outcomes["prediction"]
    if not prediction_outcome.get("ok"):
        fallback_for(prediction_service, prediction_operation, prediction_outcome)
        raise RuntimeError("unreachable: critical prediction fallback must fail closed")
    prediction_env = prediction_outcome["envelope"]
    prediction = prediction_env["data"]

    price_outcome = intelligence_outcomes["price"]
    if price_outcome.get("ok"):
        price_env = price_outcome["envelope"]
        price_bundle = price_env["data"]
        price_metric = _metric(price_env)
    else:
        price_bundle = fallback_for(price_service, price_operation, price_outcome)
        price_metric = _degraded_metric(price_outcome, price_bundle["degraded_context"])

    performance["intelligence"] = {
        "price": price_metric,
        "prediction": _metric(prediction_env),
    }

    evaluation_service, evaluation_operation = _route("evaluation_build")
    prepare_service, prepare_operation = _route("decision_prepare")
    preflight_service, preflight_operation = _route("gate0_preflight")
    analysis = invoke_parallel_envelopes(
        {
            "evaluation": (
                evaluation_service,
                evaluation_operation,
                {
                    "prediction": prediction,
                    "context": context,
                    "bootstrap": bootstrap,
                    "event_live": (dynamic_result.get("payloads") or {}).get("event_live"),
                    "ledger": states["prediction_ledger"]["data"],
                    "observations": states["challenger_observations"]["data"],
                },
            ),
            "decision_prepare": (
                prepare_service,
                prepare_operation,
                {"truth": truth, "price": price_bundle, "prediction": prediction},
            ),
            "gate0_preflight": (
                preflight_service,
                preflight_operation,
                {"truth": truth},
            ),
        },
        correlation_id=correlation_id,
    )
    performance["analysis_preflight"] = {key: _metric(value) for key, value in analysis.items()}
    evaluation = analysis["evaluation"]["data"]
    prepared = analysis["decision_prepare"]["data"]
    gate0_preflight = analysis["gate0_preflight"]["data"]

    finalize_env = _call(
        "decision_finalize",
        {
            "truth": truth,
            "price": price_bundle,
            "prediction": prediction,
            "evaluation": evaluation,
            "prepared": prepared,
            "gate0_preflight": gate0_preflight,
        },
        correlation_id,
    )
    decision = finalize_env["data"]
    performance["decision_finalize"] = _metric(finalize_env)

    governance_env = _call(
        "governance_audit",
        {
            "truth": truth,
            "price": price_bundle,
            "prediction": prediction,
            "evaluation": evaluation,
            "decision": decision,
        },
        correlation_id,
    )
    framework = governance_env["data"]
    performance["governance"] = _metric(governance_env)
    if framework.get("recommendation_allowed") is False:
        decision["production_recommendation"] = None
        decision["final_state"] = "BLOCKED"
    elif framework.get("go_allowed") is False:
        decision["final_state"] = "HOLD_WAIT_REVIEW_ONLY"
    else:
        decision["final_state"] = "GO_ELIGIBLE_NOT_AUTO_SUBMITTED"

    limits = runner_cfg["summary_limits"]
    price_rows = price_bundle.get("prices") if isinstance(price_bundle.get("prices"), dict) else {}
    alerts = price_bundle.get("alerts") if isinstance(price_bundle.get("alerts"), dict) else {}
    auth_summary = auth_runtime.get("summary") if isinstance(auth_runtime.get("summary"), dict) else {}
    accuracy = evaluation.get("accuracy") if isinstance(evaluation.get("accuracy"), dict) else {}
    scorecard = evaluation.get("challenger_scorecard") if isinstance(evaluation.get("challenger_scorecard"), dict) else {}
    degraded_contexts = framework.get("degraded_contexts") if isinstance(framework.get("degraded_contexts"), list) else []
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
            "status": price_bundle.get("status", "READY"),
            "confirmed_changes": price_rows.get("confirmed_changes", []),
            "top_rise_risk": price_rows.get("top_rise_risk", [])[: int(limits["price_rise_risk"])],
            "top_fall_risk": price_rows.get("top_fall_risk", [])[: int(limits["price_fall_risk"])],
            "alerts": alerts.get("alerts", [])[: int(limits["price_alerts"])],
            "degraded_context": price_bundle.get("degraded_context"),
        },
        "prediction_summary": {
            "model_version": prediction.get("model_version"),
            "player_count": len(prediction.get("players") or []),
            "planning_gw": prediction.get("planning_gw"),
            "horizon_gws": prediction.get("horizon_gws"),
            "ruleset_id": prediction.get("ruleset_id"),
        },
        "evaluation_summary": {
            "status": (accuracy.get("overall") or {}).get("status"),
            "sample_size": (accuracy.get("overall") or {}).get("sample_size", 0),
            "confidence": accuracy.get("confidence"),
            "challenger_status": scorecard.get("status"),
        },
        "decision_summary": {
            **decision,
            "packages": (decision.get("packages") or [])[: int(limits["packages"])],
        },
        "framework_health": framework,
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
            "recommendation_allowed": framework.get("recommendation_allowed"),
            "go_allowed": framework.get("go_allowed"),
            "gate0_preflight_pass": gate0_preflight.get("pass"),
            "degraded_contexts": degraded_contexts,
            "degraded_blocks_unqualified_go": framework.get("degraded_blocks_unqualified_go"),
            "microservices_required": True,
            "raw_authenticated_payload_persisted": False,
        },
    }

    if persist:
        write_service, write_operation = _route("artifact_write")
        artifact_mapping = _cfg()["artifact_mapping"]
        artifact_payloads = {
            "predictions": prediction,
            "team_strength": prediction.get("team_strength", {}),
            "prediction_ledger": evaluation.get("ledger", {}),
            "prediction_accuracy": accuracy,
            "challenger_scorecard": scorecard,
            "package_optimizer": decision,
            "framework_health": framework,
        }
        if not isinstance(price_bundle.get("degraded_context"), dict):
            artifact_payloads.update(
                {
                    "prices": price_bundle.get("prices", {}),
                    "price_trajectory": price_bundle.get("trajectory_state", {}),
                    "price_alerts": price_bundle.get("alerts", {}),
                }
            )
        else:
            performance["price_persistence"] = {
                "status": "SKIPPED_DEGRADED",
                "reason": "preserve last known healthy price artifacts",
            }

        writes = invoke_parallel_envelopes(
            {
                name: (
                    write_service,
                    write_operation,
                    {"name": str(artifact_mapping[name]), "data": data},
                )
                for name, data in artifact_payloads.items()
            },
            correlation_id=correlation_id,
        )
        performance["artifact_persistence"] = {key: _metric(value) for key, value in writes.items()}
        gw = context.get("submitted_gw") or context.get("planning_gw")
        snapshot_env = _call("snapshot_write", {"snapshot": snapshot, "gw": gw}, correlation_id)
        performance["snapshot_write"] = _metric(snapshot_env)
        snapshot["files"] = snapshot_env["data"]

    performance["orchestrator_wall_ms"] = round((perf_counter() - wall_started) * 1000.0, 3)
    snapshot["service_performance"] = performance
    return snapshot
