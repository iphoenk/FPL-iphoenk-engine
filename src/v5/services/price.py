from __future__ import annotations

from typing import Any

from src.v5.price_service import build_price_snapshot
from src.v5.services.common import parse_datetime

STATIC_CAPABILITIES = ["price_intelligence"]


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "capabilities": list(STATIC_CAPABILITIES),
            "conditional_capabilities": {
                "transfer_momentum": "advertised only when Official transfer-count/current-price linkage evidence is AVAILABLE"
            },
        }
    if operation != "build":
        raise KeyError(f"unsupported price operation: {operation}")
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise ValueError("price service requires bootstrap")
    result = build_price_snapshot(
        bootstrap,
        previous_state=payload.get("previous_state") if isinstance(payload.get("previous_state"), dict) else {},
        owned_ids=payload.get("owned_ids") or (),
        now=parse_datetime(payload.get("now")),
    )
    capabilities = list(STATIC_CAPABILITIES)
    momentum = result.get("transfer_momentum") if isinstance(result.get("transfer_momentum"), dict) else {}
    if momentum.get("evidence_state") == "AVAILABLE":
        capabilities.append("transfer_momentum")
    return {**result, "capabilities": capabilities}
