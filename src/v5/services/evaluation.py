from __future__ import annotations

from typing import Any

from src.v5.evaluation.core import challenger_scorecard, evaluate
from src.v5.evaluation.decision_validation import capture as capture_decision_validation
from src.v5.evaluation.evidence_guard import evaluate as evaluate_evidence_guard
from src.v5.evaluation.external_consensus import normalize as normalize_external_consensus
from src.v5.evaluation.owned_challenger_comparator import compare as compare_owned_challenger
from src.v5.evaluation.owned_challenger_context import enrich_with_decision_context
from src.v5.evaluation.prediction_settlement import build_settlement_artifact
from src.v5.evaluation.shadow_parity import compare as compare_shadow

BASE_CAPABILITIES = [
    "prediction_evaluation",
    "calibration_store",
    "challenger_scorecard",
    "owned_challenger_comparator",
    "external_consensus",
    "decision_validation_snapshot",
    "shadow_parity",
    "learning_loop",
    "temporal_backtest",
    "prediction_settlement",
]


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "capabilities": list(BASE_CAPABILITIES),
            "operations": ["build", "compare_owned_challenger", "normalize_external_consensus", "capture_decision_validation", "shadow_compare"],
        }
    if operation == "shadow_compare":
        return compare_shadow(payload.get("v3") or {}, payload.get("v5") or {})
    if operation == "normalize_external_consensus":
        return normalize_external_consensus(
            payload.get("observations") if isinstance(payload.get("observations"), dict) else {},
            payload.get("native_snapshot") if isinstance(payload.get("native_snapshot"), dict) else {},
        )
    if operation == "capture_decision_validation":
        return capture_decision_validation(
            payload.get("context") if isinstance(payload.get("context"), dict) else {},
            payload.get("decision") if isinstance(payload.get("decision"), dict) else {},
            payload.get("team") if isinstance(payload.get("team"), dict) else {},
            payload.get("comparator") if isinstance(payload.get("comparator"), dict) else {},
            previous=payload.get("previous") if isinstance(payload.get("previous"), dict) else None,
        )
    if operation == "compare_owned_challenger":
        prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
        truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
        team = truth.get("team") if isinstance(truth.get("team"), dict) else {}
        watchlist = payload.get("watchlist") if isinstance(payload.get("watchlist"), dict) else {}
        if not prediction or not team or not watchlist:
            raise ValueError("owned challenger comparator requires prediction, truth team and governed watchlist")
        base = compare_owned_challenger(
            prediction=prediction,
            team=team,
            watchlist=watchlist,
            context=truth.get("context") if isinstance(truth.get("context"), dict) else {},
            emerging_candidates=payload.get("emerging_candidates") if isinstance(payload.get("emerging_candidates"), list) else None,
            workload_context=payload.get("workload_context") if isinstance(payload.get("workload_context"), dict) else None,
            transfer_state=payload.get("transfer_state") if isinstance(payload.get("transfer_state"), dict) else None,
            external_consensus=payload.get("external_consensus") if isinstance(payload.get("external_consensus"), dict) else None,
        )
        return enrich_with_decision_context(
            base,
            payload.get("decision_context") if isinstance(payload.get("decision_context"), dict) else None,
        )
    if operation != "build":
        raise KeyError(f"unsupported evaluation operation: {operation}")
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    bootstrap = payload.get("bootstrap") if isinstance(payload.get("bootstrap"), dict) else {}
    event_live = payload.get("event_live") if isinstance(payload.get("event_live"), dict) else None
    ledger = payload.get("ledger") if isinstance(payload.get("ledger"), dict) else None
    observations = payload.get("observations") if isinstance(payload.get("observations"), dict) else None
    result = evaluate(prediction, context, bootstrap, event_live, ledger)
    scorecard = challenger_scorecard(prediction, observations, result["accuracy"])
    evidence_guard = evaluate_evidence_guard(prediction, context, truth)
    settlement = build_settlement_artifact(result["ledger"], result["accuracy"])
    capabilities = set(BASE_CAPABILITIES)
    capabilities.update(str(x) for x in evidence_guard.get("capabilities") or [])
    return {
        **result,
        "challenger_scorecard": scorecard,
        "evidence_guard": evidence_guard,
        "prediction_settlement": settlement,
        "capabilities": sorted(capabilities),
    }
