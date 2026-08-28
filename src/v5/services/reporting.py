from __future__ import annotations

from typing import Any

from src.v5.reporting import build_report


def _comparison_summary(comparator: dict[str, Any]) -> dict[str, Any]:
    comparisons = [row for row in comparator.get("comparisons") or [] if isinstance(row, dict)]
    comparisons.sort(key=lambda row: float(row.get("raw_gain_5gw") or -999.0), reverse=True)
    top = []
    for row in comparisons[:5]:
        top.append(
            {
                "player_out": row.get("player_out"),
                "player_in": row.get("player_in"),
                "challenger_type": row.get("challenger_type"),
                "raw_gain_2gw": row.get("raw_gain_2gw"),
                "raw_gain_3gw": row.get("raw_gain_3gw"),
                "raw_gain_5gw": row.get("raw_gain_5gw"),
                "net_transfer_value": row.get("net_transfer_value"),
                "confidence": row.get("confidence"),
                "decision": row.get("decision"),
                "decision_reasons": row.get("decision_reasons"),
                "decision_risks": row.get("decision_risks"),
                "reversal_triggers": row.get("reversal_triggers"),
            }
        )
    return {
        "status": comparator.get("status"),
        "operating_status": comparator.get("operating_status"),
        "planning_gw": comparator.get("planning_gw"),
        "comparison_count": comparator.get("comparison_count", 0),
        "governed_watchlist_challengers": comparator.get("governed_watchlist_challengers", 0),
        "emerging_full_comparison_eligible": comparator.get("emerging_full_comparison_eligible", 0),
        "decision_counts": comparator.get("decision_counts", {}),
        "top_comparisons": top,
        "advisory_only": True,
    }


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "model": "v5_decision_first_report_v1",
            "operations": ["build"],
            "capabilities": ["challenger_comparator_reporting"],
        }
    if operation == "build":
        merged = dict(payload)
        decision = dict(payload.get("decision") or {})
        watchlist = payload.get("watchlist") if isinstance(payload.get("watchlist"), dict) else None
        comparator = (
            payload.get("challenger_comparator")
            if isinstance(payload.get("challenger_comparator"), dict)
            else decision.get("challenger_comparator")
        )
        if watchlist is not None:
            decision["watchlist"] = watchlist
        if isinstance(comparator, dict):
            decision["challenger_comparator"] = comparator
        merged["decision"] = decision
        result = build_report(merged)
        if isinstance(comparator, dict):
            result.setdefault("user_report", {})["challenger_comparator"] = _comparison_summary(comparator)
            result.setdefault("technical_appendix", {})["challenger_comparator"] = comparator
        return result
    raise KeyError(f"unsupported reporting operation: {operation}")
