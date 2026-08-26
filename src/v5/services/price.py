from __future__ import annotations

from typing import Any

from src.v5.price_service import build_price_snapshot
from src.v5.services.common import parse_datetime


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation != "build":
        raise KeyError(f"unsupported price operation: {operation}")
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise ValueError("price service requires bootstrap")
    return build_price_snapshot(
        bootstrap,
        previous_state=payload.get("previous_state") if isinstance(payload.get("previous_state"), dict) else {},
        owned_ids=payload.get("owned_ids") or (),
        now=parse_datetime(payload.get("now")),
    )
