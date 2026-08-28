from __future__ import annotations

import json
from typing import Any

from src.utils import DATA, atomic_json, read_json

COMPARATOR = DATA / "owned_challenger_comparator.json"
USER = DATA / "user_report.json"
BRIEF = DATA / "decision_brief.json"
DEEP = DATA / "deep_review_payload.json"


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    out = row.get("player_out") or {}
    incoming = row.get("player_in") or {}
    return {
        "player_out": {"element": out.get("element"), "name": out.get("name"), "position": out.get("position"), "price": out.get("price")},
        "player_in": {"element": incoming.get("element"), "name": incoming.get("name"), "position": incoming.get("position"), "price": incoming.get("price")},
        "challenger_type": row.get("challenger_type"),
        "performance_signal": row.get("performance_signal"),
        "raw_gain_2gw": row.get("raw_gain_2gw"),
        "raw_gain_3gw": row.get("raw_gain_3gw"),
        "raw_gain_5gw": row.get("raw_gain_5gw"),
        "net_transfer_value": row.get("net_transfer_value"),
        "affordability": row.get("affordability"),
        "confidence": row.get("confidence"),
        "decision": row.get("decision"),
        "decision_reasons": list(row.get("decision_reasons") or [])[:3],
        "decision_risks": list(row.get("decision_risks") or [])[:3],
        "reversal_triggers": list(row.get("reversal_triggers") or [])[:4],
        "advisory_only": True,
    }


def _section(payload: dict[str, Any], *, deep: bool) -> dict[str, Any]:
    top = list(payload.get("top_comparisons") or [])
    emerging = list(payload.get("emerging_challengers") or [])
    section = {
        "contract": payload.get("contract"),
        "capability_status": payload.get("capability_status"),
        "planning_gw": payload.get("planning_gw"),
        "challenger_counts": payload.get("challenger_counts"),
        "top_comparisons": [_compact(row) for row in top[:12 if deep else 5]],
        "emerging_challengers": emerging[:8 if deep else 4],
        "full_artifact": "data/owned_challenger_comparator.json",
        "advisory_only": True,
        "canonical_decisions_unchanged": True,
    }
    if deep:
        section["common_output_semantics"] = payload.get("common_output_semantics")
        section["governance"] = payload.get("governance")
    return section


def run() -> dict[str, Any]:
    comparator = read_json(COMPARATOR, {})
    if comparator.get("contract") != "OWNED_CHALLENGER_COMPARATOR_V1":
        raise RuntimeError("owned challenger comparator artifact missing or invalid for report overlay")
    if comparator.get("capability_status") != "ADVISORY_ONLY":
        raise RuntimeError("initial comparator capability must remain ADVISORY_ONLY")

    user = read_json(USER, {})
    brief = read_json(BRIEF, {})
    deep = read_json(DEEP, {})
    if not user or not brief or not deep:
        raise RuntimeError("report comparator overlay requires materialized report payloads")

    user["owned_vs_challenger"] = _section(comparator, deep=False)
    brief["owned_vs_challenger"] = _section(comparator, deep=False)
    deep["owned_vs_challenger"] = _section(comparator, deep=True)
    atomic_json(USER, user)
    atomic_json(BRIEF, brief)
    atomic_json(DEEP, deep)
    return {
        "status": "PASS",
        "contract": comparator.get("contract"),
        "capability_status": comparator.get("capability_status"),
        "top_comparisons": len((user.get("owned_vs_challenger") or {}).get("top_comparisons") or []),
        "canonical_decisions_unchanged": True,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
