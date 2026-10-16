"""Fail-closed admission ledger for historical predeadline P(start) folds.

A verified training input is not proof of the historical model or frozen forecast.
Never infer missing witnesses from timestamps, retrospectively downloaded data,
or a previous fold's successful source readback.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Any

REQUIRED = ("source_integrity", "prior_training_rows_asof",
            "model_parameters_asof", "prediction_frozen_asof")
FOLDS = (2, 3, 4, 5, 6)


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def assess_fold(gw: int, evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    if gw not in FOLDS:
        raise ValueError("UNSUPPORTED_TARGET_GW")
    e = evidence if isinstance(evidence, Mapping) else {}
    deadline = _time(e.get("official_deadline"))
    cutoff = _time(e.get("last_original_source_at"))
    predeadline = deadline is not None and cutoff is not None and cutoff < deadline
    checks = {key: e.get(key) == "PASS" for key in REQUIRED}
    leakage = e.get("leakage") == "ZERO" and predeadline
    missing = [key for key, passed in checks.items() if not passed]
    if not predeadline:
        missing.append("independent_original_predeadline_timestamp")
    if not leakage:
        missing.append("zero_leakage")
    return {
        "target_gw": gw,
        "source_integrity": "PASS" if checks["source_integrity"] else "NOT_ESTABLISHED",
        "prior_training_rows_asof": "PASS" if checks["prior_training_rows_asof"] and predeadline else "NOT_ESTABLISHED",
        "model_parameters_asof": "PASS" if checks["model_parameters_asof"] and predeadline else "NOT_ESTABLISHED",
        "prediction_frozen_asof": "PASS" if checks["prediction_frozen_asof"] and predeadline else "NOT_ESTABLISHED",
        "temporal_integrity": "PASS" if predeadline else "NOT_ESTABLISHED",
        "leakage": "ZERO" if leakage else "NOT_ESTABLISHED",
        "admission": "PASS" if all(checks.values()) and leakage else "NOT_ESTABLISHED",
        "missing_witnesses": sorted(set(missing)),
    }


def build_ledger(evidence_by_gw: Mapping[int, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    inputs = evidence_by_gw or {}
    folds = [assess_fold(gw, inputs.get(gw)) for gw in FOLDS]
    return {
        "contract": "V12_HISTORICAL_ASOF_FOLD_LEDGER_V1",
        "folds": folds,
        "historical_asof": "PASS" if all(f["admission"] == "PASS" for f in folds) else "NOT_ESTABLISHED",
        "no_retrospective_promotion": True,
    }
