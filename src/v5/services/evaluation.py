from __future__ import annotations

from typing import Any

from src.v5.evaluation.core import challenger_scorecard, evaluate


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {"status": "ACTIVE", "capabilities": ["prediction_evaluation", "calibration_store", "challenger_scorecard"]}
    if operation != "build":
        raise KeyError(f"unsupported evaluation operation: {operation}")
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    bootstrap = payload.get("bootstrap") if isinstance(payload.get("bootstrap"), dict) else {}
    event_live = payload.get("event_live") if isinstance(payload.get("event_live"), dict) else None
    ledger = payload.get("ledger") if isinstance(payload.get("ledger"), dict) else None
    observations = payload.get("observations") if isinstance(payload.get("observations"), dict) else None
    result = evaluate(prediction, context, bootstrap, event_live, ledger)
    return {**result, "challenger_scorecard": challenger_scorecard(prediction, observations, result["accuracy"])}
