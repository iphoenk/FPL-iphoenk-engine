from __future__ import annotations

from typing import Any

from src.v5.decision.package_optimizer import build_packages


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {"status": "ACTIVE", "bridge_only": False, "production_recommendation": False}
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
    return {
        "status": packages.get("status"),
        "model": packages.get("model"),
        "ruleset_id": packages.get("ruleset_id"),
        "gate0_prevalidated": packages.get("gate0_prevalidated", False),
        "package_count": packages.get("package_count", 0),
        "hold": packages.get("hold"),
        "packages": packages.get("packages", []),
        "candidate_pool": packages.get("candidate_pool", {}),
        "price_context": {"alert_count": len(((price.get("alerts") or {}).get("alerts") or []))},
        "governance": packages.get("governance", {}),
        "production_recommendation": None,
    }
