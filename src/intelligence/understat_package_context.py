from __future__ import annotations

from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _prediction_map(predictions: dict) -> dict[int, dict]:
    return {
        int(row.get("element") or 0): row
        for row in predictions.get("players") or []
        if int(row.get("element") or 0) > 0
    }


def _xmins(pred: dict) -> dict:
    starts, minutes, dnp = [], [], []
    for fixture in (pred.get("fixtures") or [])[:5]:
        row = fixture.get("xmins") or {}
        if row.get("start_probability") is not None:
            starts.append(_f(row.get("start_probability")))
        if row.get("expected_minutes") is not None:
            minutes.append(_f(row.get("expected_minutes")))
        if row.get("dnp_probability") is not None:
            dnp.append(_f(row.get("dnp_probability")))
    return {
        "average_start_probability_5": round(sum(starts) / len(starts), 4) if starts else None,
        "average_expected_minutes_5": round(sum(minutes) / len(minutes), 2) if minutes else None,
        "average_dnp_probability_5": round(sum(dnp) / len(dnp), 4) if dnp else None,
        "authority": "V4_PREDICTION",
    }


def _matchup(understat: dict, element: int) -> dict:
    row = ((understat.get("tactical_matchups") or {}).get(str(int(element))) or {})
    return {
        "state": row.get("state") or "INSUFFICIENT_EVIDENCE",
        "confidence": row.get("confidence"),
        "freshness": row.get("freshness") or (understat.get("source") or {}).get("freshness"),
        "dimensions": row.get("dimensions") or {},
        "supporting_signals": row.get("supporting_signals") or [],
        "conflicting_signals": row.get("conflicting_signals") or [],
        "uncertainty": row.get("uncertainty") or {},
    }


def _element_context(element: int, predictions: dict[int, dict], understat: dict) -> dict:
    return {
        "element": int(element),
        "xmins": _xmins(predictions.get(int(element)) or {}),
        "understat_tactical": _matchup(understat, int(element)),
    }


def augment_package_tactical_context(challenger: dict, *, predictions: dict, understat: dict) -> dict:
    """Attach tactical/xMins evidence without changing package decisions.

    Canonical package arithmetic, hit cost and action states are computed before
    this function runs. This function is deliberately annotation-only so an
    Understat signal can never authorize a transfer or hit.
    """
    pmap = _prediction_map(predictions)
    packages = challenger.get("multi_transfer_packages") or []
    annotated = 0
    for package in packages:
        decision_before = package.get("decision")
        outgoing_ids = [int(row.get("element") or 0) for row in package.get("out") or [] if int(row.get("element") or 0) > 0]
        incoming_ids = [int(row.get("element") or 0) for row in package.get("in") or [] if int(row.get("element") or 0) > 0]
        package["understat_tactical_context"] = {
            "outgoing": [_element_context(element, pmap, understat) for element in outgoing_ids],
            "incoming": [_element_context(element, pmap, understat) for element in incoming_ids],
            "source_health": (understat.get("health") or {}).get("status") or "UNAVAILABLE",
            "freshness": (understat.get("source") or {}).get("freshness"),
            "multi_horizon_projection_authority": "CANONICAL_V4_PACKAGE_OPTIMIZER",
            "tactical_evidence_role": "CONTEXT_AND_EXPLANATION_ONLY",
            "tactical_alone_authorizes_transfer": False,
            "tactical_alone_authorizes_hit": False,
            "price_alone_authorizes_transfer": False,
        }
        package["understat_decision_invariant"] = {
            "decision_before_annotation": decision_before,
            "decision_after_annotation": package.get("decision"),
            "unchanged": package.get("decision") == decision_before,
        }
        annotated += 1
    challenger["understat_package_intelligence"] = {
        "contract": "UNDERSTAT_PACKAGE_CONTEXT_V1",
        "packages_annotated": annotated,
        "full_package_set_count": len(packages),
        "decision_authority": False,
        "hit_authority": False,
        "xpts_mutation": False,
        "xmins_mutation": False,
        "missing_understat_is_neutral": True,
    }
    return challenger
