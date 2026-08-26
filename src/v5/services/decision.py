from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.decision.decision_trace import build_trace
from src.v5.decision.dss_evaluator import evaluate_dss
from src.v5.decision.lineup_optimizer import optimize_lineup
from src.v5.decision.package_optimizer import build_packages

CONFIG = "config/v5_decision_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if not isinstance(data.get("capabilities"), list) or not isinstance(data.get("capability_activation"), dict):
        raise RuntimeError("invalid V5 decision registry capabilities")
    return data


def _inputs(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
    rules = truth.get("rules") if isinstance(truth.get("rules"), dict) else {}
    team = truth.get("team") if isinstance(truth.get("team"), dict) else {}
    if not rules or not team or not prediction:
        raise ValueError("decision service requires truth rules/team and prediction payload")
    return truth, prediction, price, rules, team


def _active_local_capabilities(packages: dict[str, Any], lineup: dict[str, Any]) -> list[str]:
    cfg = _cfg()
    configured = {str(value) for value in cfg["capabilities"]}
    activation = cfg["capability_activation"]
    active: set[str] = set()
    if packages.get("status") == "READY" and bool(packages.get("local_legality_prevalidated")):
        active.update(configured & {str(value) for value in activation.get("package_ready") or []})
    if lineup.get("status") == "READY":
        active.update(configured & {str(value) for value in activation.get("lineup_ready") or []})
    return sorted(active)


def _prepare(payload: dict[str, Any]) -> dict[str, Any]:
    truth, prediction, price, rules, team = _inputs(payload)
    packages = build_packages(prediction, team, rules)
    lineup = optimize_lineup(team, prediction, rules)
    capabilities = _active_local_capabilities(packages, lineup)
    return {
        "status": "READY" if packages.get("status") == "READY" and lineup.get("status") == "READY" else "BLOCKED",
        "model": _cfg().get("model_id"),
        "ruleset_id": rules.get("ruleset_id"),
        "packages": packages,
        "lineup": lineup,
        "capabilities": capabilities,
        "price_context": {"alert_count": len(((price.get("alerts") or {}).get("alerts") or []))},
    }


def _blocked_trace(reason: str, gate0_preflight: dict[str, Any]) -> dict[str, Any]:
    items = gate0_preflight.get("items") if isinstance(gate0_preflight.get("items"), list) else []
    return {
        "decision_type": "BLOCKED",
        "action": reason,
        "confidence": "LOW",
        "evidence": [
            {
                "source": "governance-service",
                "field": "gate0_preflight",
                "authority": "governance-service",
                "freshness": None,
                "provenance": {
                    "model": gate0_preflight.get("model"),
                    "pass": gate0_preflight.get("pass"),
                },
            }
        ] if gate0_preflight else [],
        "constraints_checked": [str(item.get("id")) for item in items if item.get("id")],
        "production_recommendation": None,
    }


def _finalize(payload: dict[str, Any], prepared: dict[str, Any] | None = None) -> dict[str, Any]:
    truth, prediction, price, rules, _ = _inputs(payload)
    prepared = prepared if isinstance(prepared, dict) else _prepare(payload)
    packages = prepared.get("packages") if isinstance(prepared.get("packages"), dict) else {}
    lineup = prepared.get("lineup") if isinstance(prepared.get("lineup"), dict) else {}
    local_capabilities = prepared.get("capabilities") if isinstance(prepared.get("capabilities"), list) else []
    evaluation = payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {}
    evaluation_capabilities = evaluation.get("capabilities") if isinstance(evaluation.get("capabilities"), list) else []
    gate0_preflight = payload.get("gate0_preflight") if isinstance(payload.get("gate0_preflight"), dict) else {}
    dss = evaluate_dss(
        truth,
        price,
        prediction,
        local_capabilities=local_capabilities,
        external_capability_sources={"evaluation": evaluation_capabilities},
    )

    local_ready = packages.get("status") == "READY" and lineup.get("status") == "READY"
    preflight_ready = bool(gate0_preflight.get("pass"))
    if local_ready:
        trace = build_trace(
            truth=truth,
            prediction=prediction,
            price=price,
            packages=packages,
            lineup=lineup,
            dss=dss,
            gate0_preflight=gate0_preflight,
        )
        status = "READY" if preflight_ready else "BLOCKED"
    else:
        trace = _blocked_trace(
            "BLOCK decision output until package and lineup authorities are READY",
            gate0_preflight,
        )
        status = "BLOCKED"

    return {
        "status": status,
        "model": _cfg().get("model_id"),
        "package_model": packages.get("model"),
        "ruleset_id": rules.get("ruleset_id"),
        "gate0_preflight_pass": preflight_ready,
        "local_legality_prevalidated": bool(packages.get("local_legality_prevalidated", False)),
        "package_count": packages.get("package_count", 0),
        "hold": packages.get("hold"),
        "packages": packages.get("packages", []),
        "candidate_pool": packages.get("candidate_pool", {}),
        "lineup": lineup,
        "dss": dss,
        "decision_trace": trace,
        "capabilities": local_capabilities,
        "price_context": prepared.get("price_context", {}),
        "governance": {
            **(packages.get("governance") or {}),
            "lineup_authority": lineup.get("authority"),
            "dss_evaluation_model": dss.get("evaluation_model"),
            "evaluation_capabilities_consumed": sorted(str(x) for x in evaluation_capabilities),
            "gate0_preflight_model": gate0_preflight.get("model"),
            "decision_trace_required": True,
            "production_recommendation_enabled": bool((_cfg().get("trace") or {}).get("production_recommendation_enabled", False)),
        },
        "production_recommendation": None,
    }


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "bridge_only": False,
            "production_recommendation": False,
            "model": _cfg().get("model_id"),
            "capabilities": list(_cfg().get("capabilities") or []),
            "operations": ["prepare", "finalize", "build"],
        }
    if operation == "prepare":
        return _prepare(payload)
    if operation == "finalize":
        return _finalize(payload, payload.get("prepared") if isinstance(payload.get("prepared"), dict) else None)
    if operation == "build":
        prepared = _prepare(payload)
        return _finalize(payload, prepared)
    raise KeyError(f"unsupported decision operation: {operation}")
