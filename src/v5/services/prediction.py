from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5.prediction_bridge import build_predictions
from src.v5.prediction_view import compact_prediction_view


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation not in {"build", "build_full"}:
        raise KeyError(f"unsupported prediction operation: {operation}")
    bootstrap = payload.get("bootstrap")
    fixtures = payload.get("fixtures")
    if not isinstance(bootstrap, dict) or not isinstance(fixtures, list):
        raise ValueError("prediction service requires bootstrap and fixtures")
    predictions = build_predictions(
        bootstrap,
        fixtures,
        str(payload.get("generated_at") or datetime.now(timezone.utc).isoformat()),
        stats_gw=int(payload["stats_gw"]) if payload.get("stats_gw") is not None else None,
    )
    if operation == "build_full":
        return predictions
    return compact_prediction_view(predictions)
