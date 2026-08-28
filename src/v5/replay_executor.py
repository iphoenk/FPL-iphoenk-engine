from __future__ import annotations

from typing import Any, Callable

from src.v5.artifact_contracts import validate_payload
from src.v5.decision.decision_trace import bind_execution_fingerprint
from src.v5.execution_plane import current_runtime_fingerprint
from src.v5.release_integrity import build_replay_fingerprint, verify_replay_outputs
from src.v5.replay_capture import snapshot_fingerprint_summary

REPLAY_EXECUTION_CONTRACT = "V5_REPLAY_EXECUTION_V1"
ALLOWED_ROUTES = (
    "price_build",
    "prediction_build",
    "evaluation_build",
    "decision_prepare",
    "gate0_preflight",
    "decision_finalize",
    "governance_audit",
)
InvokeRoute = Callable[[str, dict[str, Any], str], dict[str, Any]]


def _envelope_data(envelope: dict[str, Any], route: str) -> dict[str, Any]:
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError(f"V5 replay route {route} returned non-object data")
    return data


def replay_integrity(
    bundle: dict[str, Any],
    *,
    current_runtime_fingerprint_value: str | None = None,
) -> dict[str, Any]:
    validate_payload("replay_bundle", bundle)
    inputs = bundle.get("inputs") if isinstance(bundle.get("inputs"), dict) else {}
    recorded = bundle.get("fingerprint") if isinstance(bundle.get("fingerprint"), dict) else {}
    recorded_runtime = str(recorded.get("runtime_release_fingerprint") or "")
    recorded_replay = str(recorded.get("replay_fingerprint") or "")
    if not recorded_runtime or not recorded_replay:
        raise RuntimeError("V5 replay bundle missing recorded runtime/replay fingerprint")

    recomputed = build_replay_fingerprint(
        inputs,
        runtime_release_fingerprint=recorded_runtime,
    )
    artifact_match = str(recomputed.get("replay_fingerprint")) == recorded_replay
    runtime_now = str(current_runtime_fingerprint_value or current_runtime_fingerprint())
    runtime_match = runtime_now == recorded_runtime
    return {
        "artifact_integrity": "MATCH" if artifact_match else "MISMATCH",
        "artifact_integrity_match": artifact_match,
        "recorded_replay_fingerprint": recorded_replay,
        "recomputed_replay_fingerprint": recomputed.get("replay_fingerprint"),
        "recorded_runtime_release_fingerprint": recorded_runtime,
        "current_runtime_release_fingerprint": runtime_now,
        "runtime_match": runtime_match,
        "eligible": artifact_match and runtime_match,
    }


def execute_replay(
    bundle: dict[str, Any],
    *,
    invoke_route: InvokeRoute,
    correlation_id: str,
    current_runtime_fingerprint_value: str | None = None,
) -> dict[str, Any]:
    integrity = replay_integrity(
        bundle,
        current_runtime_fingerprint_value=current_runtime_fingerprint_value,
    )
    if not integrity["artifact_integrity_match"]:
        return {
            "contract": REPLAY_EXECUTION_CONTRACT,
            "status": "BLOCKED_ARTIFACT_INTEGRITY_MISMATCH",
            "match": False,
            "integrity": integrity,
            "route_trace": [],
            "governance": {
                "refetched_current_sources": False,
                "network_refresh_allowed": False,
                "model_services_invoked": False,
            },
        }
    if not integrity["runtime_match"]:
        return {
            "contract": REPLAY_EXECUTION_CONTRACT,
            "status": "BLOCKED_RUNTIME_FINGERPRINT_MISMATCH",
            "match": False,
            "integrity": integrity,
            "route_trace": [],
            "governance": {
                "refetched_current_sources": False,
                "network_refresh_allowed": False,
                "model_services_invoked": False,
            },
        }

    inputs = bundle["inputs"]
    bootstrap = inputs.get("bootstrap") if isinstance(inputs.get("bootstrap"), dict) else {}
    fixtures = inputs.get("fixtures") if isinstance(inputs.get("fixtures"), list) else []
    truth = inputs.get("truth") if isinstance(inputs.get("truth"), dict) else {}
    context = truth.get("context") if isinstance(truth.get("context"), dict) else {}
    source_fusion = inputs.get("source_fusion") if isinstance(inputs.get("source_fusion"), dict) else {}
    states = inputs.get("state_hydration") if isinstance(inputs.get("state_hydration"), dict) else {}
    runner_policy = inputs.get("runner_policy") if isinstance(inputs.get("runner_policy"), dict) else {}
    owned_ids = (truth.get("team") or {}).get("owned_ids") or []
    route_trace: list[str] = []

    def call(name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_ROUTES:
            raise RuntimeError(f"V5 replay route forbidden: {name}")
        route_trace.append(name)
        return _envelope_data(invoke_route(name, payload, correlation_id), name)

    price = call(
        "price_build",
        {
            "bootstrap": bootstrap,
            "previous_state": states.get("price_trajectory") or {},
            "owned_ids": owned_ids,
        },
    )
    prediction = call(
        "prediction_build",
        {
            "bootstrap": bootstrap,
            "fixtures": fixtures,
            "rules": truth.get("rules") or {},
            "planning_gw": context.get("planning_gw"),
            "horizon": int(runner_policy.get("prediction_horizon_gws") or 15),
            "owned_ids": owned_ids,
            "historical_prior": states.get("historical_prior") or {},
            "allow_historical_prior_refresh": False,
            "source_fusion": source_fusion,
        },
    )
    evaluation = call(
        "evaluation_build",
        {
            "prediction": prediction,
            "context": context,
            "bootstrap": bootstrap,
            "event_live": inputs.get("event_live"),
            "ledger": states.get("prediction_ledger") or {},
            "observations": states.get("challenger_observations") or {},
        },
    )
    prepared = call(
        "decision_prepare",
        {"truth": truth, "price": price, "prediction": prediction},
    )
    preflight = call("gate0_preflight", {"truth": truth})
    decision = call(
        "decision_finalize",
        {
            "truth": truth,
            "price": price,
            "prediction": prediction,
            "evaluation": evaluation,
            "prepared": prepared,
            "gate0_preflight": preflight,
        },
    )
    trace = decision.get("decision_trace") if isinstance(decision.get("decision_trace"), dict) else None
    if trace is not None:
        decision["decision_trace"] = bind_execution_fingerprint(trace, snapshot_fingerprint_summary(bundle))

    framework = call(
        "governance_audit",
        {
            "truth": truth,
            "price": price,
            "prediction": prediction,
            "evaluation": evaluation,
            "decision": decision,
        },
    )
    if framework.get("recommendation_allowed") is False:
        decision["production_recommendation"] = None
        decision["final_state"] = "BLOCKED"
    elif framework.get("go_allowed") is False:
        decision["final_state"] = "HOLD_WAIT_REVIEW_ONLY"
    else:
        decision["final_state"] = "GO_ELIGIBLE_NOT_AUTO_SUBMITTED"

    outputs = {
        "price": price,
        "prediction": prediction,
        "evaluation": evaluation,
        "decision": decision,
        "framework": framework,
    }
    expected = bundle.get("expected_output_hashes") if isinstance(bundle.get("expected_output_hashes"), dict) else {}
    verification = verify_replay_outputs(expected, outputs)
    return {
        "contract": REPLAY_EXECUTION_CONTRACT,
        "status": "MATCH" if verification.get("match") else "MISMATCH",
        "match": bool(verification.get("match")),
        "integrity": integrity,
        "verification": verification,
        "route_trace": route_trace,
        "decision": decision,
        "framework": framework,
        "governance": {
            "refetched_current_sources": False,
            "network_refresh_allowed": False,
            "historical_prior_network_refresh": False,
            "model_services_invoked": True,
            "allowed_routes": list(ALLOWED_ROUTES),
            "promotion_authority": False,
        },
    }
