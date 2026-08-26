from __future__ import annotations

from typing import Any

from src.v5.governance.core import build_health
from src.v5.governance.gate0 import audit as gate0_audit, postflight as gate0_postflight, preflight as gate0_preflight


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "capabilities": ["gate0", "framework_health", "enhancement_layers", "final_governance"],
            "gate0_model": "v5_gate0_full_16_v1",
        }
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    if operation == "gate0_preflight":
        return gate0_preflight(truth)
    if operation == "gate0_postflight":
        return gate0_postflight(truth, decision)
    if operation == "gate0_audit":
        return gate0_audit(truth, decision)
    if operation != "audit":
        raise KeyError(f"unsupported governance operation: {operation}")
    return build_health(
        truth,
        payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {},
        payload.get("price") if isinstance(payload.get("price"), dict) else {},
        decision,
        payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {},
    )
