from __future__ import annotations
from typing import Any
from src.v5.evaluation.temporal_backtest import validate_frozen_ledger

def build_settlement_artifact(ledger: dict[str, Any], accuracy: dict[str, Any]) -> dict[str, Any]:
    records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    settled = sorted(int(k) for k,v in records.items() if isinstance(v,dict) and v.get("status") == "SETTLED")
    return {
        "schema_version": 1,
        "model": "v5_prediction_settlement_v1",
        "settled_gameweeks": settled,
        "sample_size": int(((accuracy.get("overall") or {}).get("sample_size")) or 0),
        "temporal_guard": validate_frozen_ledger(ledger),
        "baseline_comparison": accuracy.get("baseline_comparison"),
        "eligible_for_accuracy_claim": bool(settled) and int(((accuracy.get("overall") or {}).get("sample_size")) or 0) > 0,
    }
