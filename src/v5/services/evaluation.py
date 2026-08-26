from __future__ import annotations

from typing import Any

from src.v5.evaluation.core import challenger_scorecard, evaluate
from src.v5.evaluation.evidence_guard import evaluate as evaluate_evidence_guard
from src.v5.evaluation.shadow_parity import compare as compare_shadow

BASE_CAPABILITIES = [
    "prediction_evaluation",
    "calibration_store",
    "challenger_scorecard",
    "shadow_parity",
    "learning_loop",
]


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {"status": "ACTIVE", "capabilities": list(BASE_CAPABILITIES), "operations": ["build", "shadow_compare"]}
    if operation == "shadow_compare":
        return compare_shadow(payload.get("v3") or {}, payload.get("v5") or {})
    if operation != "build":
        raise KeyError(f"unsupported evaluation operation: {operation}")
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    bootstrap = payload.get("bootstrap") if isinstance(payload.get("bootstrap"), dict) else {}
    event_live = payload.get("event_live") if isinstance(payload.get("event_live"), dict) else None
    ledger = payload.get("ledger") if isinstance(payload.get("ledger"), dict) else None
    observations = payload.get("observations") if isinstance(payload.get("observations"), dict) else None
    result = evaluate(prediction, context, bootstrap, event_live, ledger)
    scorecard = challenger_scorecard(prediction, observations, result["accuracy"])
    evidence_guard = evaluate_evidence_guard(prediction, context)
    capabilities = set(BASE_CAPABILITIES)
    capabilities.update(str(x) for x in evidence_guard.get("capabilities") or [])
    return {
        **result,
        "challenger_scorecard": scorecard,
        "evidence_guard": evidence_guard,
        "capabilities": sorted(capabilities),
    }
