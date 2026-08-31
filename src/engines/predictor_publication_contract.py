from __future__ import annotations

from typing import Any

UNAVAILABLE_STATES = {"FIELD_MISSING", "SCHEMA_CHANGED", "UNAVAILABLE"}
SUPPORTED_SIGNAL_CYCLES = {"NEXT_UPDATE", "PLUS_1_UPDATE", "PLUS_2_UPDATE"}


def _is_predictor_observation(row: dict[str, Any]) -> bool:
    return (
        str(row.get("source") or "").upper() == "OFFICIAL_FPL"
        and "evidence_state" in row
        and ("current_progress_percent" in row or "predicted_change_cycle" in row)
    )


def predictor_signal_state(row: dict[str, Any]) -> str:
    evidence = str(row.get("evidence_state") or "UNAVAILABLE").upper()
    if evidence in UNAVAILABLE_STATES:
        return "UNAVAILABLE"

    cycle = str(row.get("predicted_change_cycle") or "NONE").upper()
    if cycle == "NONE":
        return "NO_SIGNAL"
    if cycle not in SUPPORTED_SIGNAL_CYCLES:
        return "UNAVAILABLE"
    if not row.get("predicted_change_at"):
        return "UNAVAILABLE"
    return "SIGNAL"


def decorate_predictor_observation(row: dict[str, Any]) -> dict[str, Any]:
    if not _is_predictor_observation(row):
        return row
    out = dict(row)
    freshness_state = str(row.get("evidence_state") or "UNAVAILABLE").upper()
    signal_state = predictor_signal_state(row)
    predicted_at = row.get("predicted_change_at")
    out.update({
        "model_signal_state": signal_state,
        "freshness_state": freshness_state,
        "age_seconds": row.get("freshness_seconds"),
        "progress": row.get("current_progress_percent"),
        "trajectory": row.get("trajectory"),
        "direction": row.get("direction"),
        "eta": predicted_at if signal_state == "SIGNAL" else None,
        "eta_supported": bool(signal_state == "SIGNAL"),
        "current_claim_allowed": freshness_state not in {"STALE", "UNAVAILABLE", "FIELD_MISSING", "SCHEMA_CHANGED"},
    })
    return out


def decorate_predictor_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [decorate_predictor_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    decorated = {key: decorate_predictor_payload(item) for key, item in value.items()}
    return decorate_predictor_observation(decorated)
