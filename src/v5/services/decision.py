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
    if not isinstance(data.get("capabilities"), list):
        raise RuntimeError("invalid V5 decision registry capabilities")
    return data


def _active_local_capabilities(packages: dict[str, Any], lineup: dict[str, Any]) -> list[str]:
    configured = {str(value) for value in _cfg().get("capabilities") or []}
    active: set[str] = set()
    if packages.get("status") == "READY" and bool(packages.get("gate0_prevalidated")):
        active.update(
            configured
            & {
                "direct_challenger",
                "structural_fit",
                "governed_optimizer",
                "sell_cost_affordability",
                "package_churn_penalty",
                "package_structural",
                "multi_horizon",
                "decision_recheck",
            }
        )
    if lineup.get("status") == "READY":
        active.update(
            configured
            & {
                "lineup_governance",
                "captaincy",
                "bench_utility",
                "decision_recheck",
            }
        )
        active.update({"lineup_robustness", "captain_dnp_guard"})
    return sorted(active)


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "bridge_only": False,
            "production_recommendation": False,
            "model": _cfg().get("model_id"),
            "capabilities": list(_cfg().get("capabilities") or []),
        }
    if operation != "build":
        raise KeyError(f"unsupported decision operation: {operation}")

    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
    rules = truth.get("rules") if isinstance(truth.get("rules"), dict) else {}
    team = truth.get("team") if isinstance(truth.get("team"), dict) else {}
    if not rules or not team or not prediction:
        raise ValueError("decision service requires truth rules/team and prediction payload")

    packages = build_packages(prediction, team, rules)
    lineup = optimize_lineup(team, prediction, rules)
    local_capabilities = _active_local_capabilities(packages, lineup)
    dss = evaluate_dss(
        truth,
        price,
        prediction,
        local_capabilities=local_capabilities,
    )

    if packages.get("status") == "READY" and lineup.get("status") == "READY":
        trace = build_trace(
            truth=truth,
            prediction=prediction,
            price=price,
            packages=packages,
            lineup=lineup,
            dss=dss,
        )
        status = "READY"
    else:
        trace = {
            "decision_type": "BLOCKED",
            "action": "BLOCK decision output until package and lineup authorities are READY",
            "confidence": "LOW",
            "evidence": [],
            "constraints_checked": [],
            "production_recommendation": None,
        }
        status = "BLOCKED"

    return {
        "status": status,
        "model": _cfg().get("model_id"),
        "package_model": packages.get("model"),
        "ruleset_id": rules.get("ruleset_id"),
        "gate0_prevalidated": bool(packages.get("gate0_prevalidated", False)),
        "package_count": packages.get("package_count", 0),
        "hold": packages.get("hold"),
        "packages": packages.get("packages", []),
        "candidate_pool": packages.get("candidate_pool", {}),
        "lineup": lineup,
        "dss": dss,
        "decision_trace": trace,
        "capabilities": local_capabilities,
        "price_context": {
            "alert_count": len(((price.get("alerts") or {}).get("alerts") or [])),
        },
        "governance": {
            **(packages.get("governance") or {}),
            "lineup_authority": lineup.get("authority"),
            "dss_evaluation_model": dss.get("evaluation_model"),
            "decision_trace_required": True,
            "production_recommendation_enabled": bool((_cfg().get("trace") or {}).get("production_recommendation_enabled", False)),
        },
        "production_recommendation": None,
    }
