"""Leakage-safe, shadow-only out-of-sample P(start)/xMins calibration audit.

Inputs are frozen *pre-match predictions* and independently settled outcomes.
This evaluator never trains a second model or modifies V12_PLAYER_MINUTES.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping


def _instant(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("TIMESTAMP_REQUIRES_TIMEZONE")
    return dt.astimezone(timezone.utc)


def _prob(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("INVALID_PROBABILITY")
    p = float(value)
    if not isfinite(p) or not 0 <= p <= 1:
        raise ValueError("INVALID_PROBABILITY")
    return p


def _minutes(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("INVALID_MINUTES")
    m = float(value)
    if not isfinite(m) or not 0 <= m <= 130:
        raise ValueError("INVALID_MINUTES")
    return m


def audit_oos_calibration(
    predictions: list[Mapping[str, Any]],
    outcomes: list[Mapping[str, Any]],
    *,
    minimum_sample: int = 50,
) -> dict[str, Any]:
    """Fail closed on missing temporal proof, leakage, duplicates, or unmatched rows.

    Prediction fields: element, match_id, prediction_as_of, kickoff,
    p_start, xmins, baseline_p_start, baseline_xmins, model_owner.
    Outcome fields: element, match_id, settled_at, starter, minutes.
    """
    if minimum_sample < 1:
        raise ValueError("MINIMUM_SAMPLE_INVALID")
    outcome_map = {}
    for row in outcomes:
        key = (row.get("element"), str(row.get("match_id") or ""))
        if type(key[0]) is not int or key[0] <= 0 or not key[1] or key in outcome_map:
            raise ValueError("OUTCOME_IDENTITY_INVALID_OR_DUPLICATE")
        outcome_map[key] = row
    seen = set()
    scored = []
    rejected: dict[str, int] = {}
    for row in predictions:
        key = (row.get("element"), str(row.get("match_id") or ""))
        if type(key[0]) is not int or key[0] <= 0 or not key[1] or key in seen:
            raise ValueError("PREDICTION_IDENTITY_INVALID_OR_DUPLICATE")
        seen.add(key)
        try:
            if row.get("model_owner") != "V12_PLAYER_MINUTES":
                raise ValueError("MODEL_OWNER_UNVERIFIED")
            outcome = outcome_map.get(key)
            if outcome is None:
                raise ValueError("NO_SETTLED_OUTCOME")
            as_of = _instant(row["prediction_as_of"])
            kickoff = _instant(row["kickoff"])
            settled = _instant(outcome["settled_at"])
            if not as_of < kickoff < settled:
                raise ValueError("TEMPORAL_LEAKAGE_OR_UNSETTLED")
            starter = outcome.get("starter")
            if type(starter) is not bool:
                raise ValueError("STARTER_NOT_VERIFIED")
            y = int(starter)
            minutes = _minutes(outcome["minutes"])
            p, bp = _prob(row["p_start"]), _prob(row["baseline_p_start"])
            xm, bx = _minutes(row["xmins"]), _minutes(row["baseline_xmins"])
            scored.append((p, bp, xm, bx, y, minutes))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) and str(exc) else "INVALID_OR_MISSING_EVIDENCE"
            rejected[reason] = rejected.get(reason, 0) + 1
    n = len(scored)
    if n:
        brier = sum((p-y)**2 for p,_,_,_,y,_ in scored)/n
        base_brier = sum((p-y)**2 for _,p,_,_,y,_ in scored)/n
        mae = sum(abs(x-m) for _,_,x,_,_,m in scored)/n
        base_mae = sum(abs(x-m) for _,_,_,x,_,m in scored)/n
    else:
        brier = base_brier = mae = base_mae = None
    better = n >= minimum_sample and brier < base_brier and mae < base_mae
    return {
        "contract": "V12_STAGEC_TEMPORAL_OOS_V1",
        "mode": "SHADOW_ONLY",
        "model_owner": "V12_PLAYER_MINUTES",
        "scored_sample": n,
        "minimum_sample": minimum_sample,
        "rejected_by_reason": rejected,
        "starter_brier": brier,
        "baseline_starter_brier": base_brier,
        "xmins_mae": mae,
        "baseline_xmins_mae": base_mae,
        "beats_baseline_both": bool(better),
        "verdict": "PASS_SHADOW" if better and not rejected else "INSUFFICIENT_OR_FAIL",
        "production_activation_allowed": False,
        "numeric_parameters_mutated": False,
    }
