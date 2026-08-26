from __future__ import annotations

from typing import Any

from src.v5.governance.core import build_health, gate0_preflight


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {"status": "ACTIVE", "capabilities": ["gate0", "framework_health", "enhancement_layers", "final_governance"]}
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    if operation == "gate0_preflight":
        return gate0_preflight(truth)
    if operation != "audit":
        raise KeyError(f"unsupported governance operation: {operation}")
    return build_health(
        truth,
        payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {},
        payload.get("price") if isinstance(payload.get("price"), dict) else {},
        payload.get("decision") if isinstance(payload.get("decision"), dict) else {},
        payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {},
    )
