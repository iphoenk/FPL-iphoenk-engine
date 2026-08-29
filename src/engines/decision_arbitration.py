from __future__ import annotations

from typing import Any


def _norm_chip(value: Any) -> str:
    text = str(value or "NONE").strip().upper()
    return "NONE" if text in {"", "NONE", "NULL", "NO_CHIP"} else text


def arbitrate_decisions(
    user_report: dict[str, Any],
    lineup: dict[str, Any],
    comparator: dict[str, Any],
) -> dict[str, Any]:
    contradictions: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    user_formation = ((user_report.get("starting_xi") or {}).get("facts") or {}).get("formation")
    lineup_formation = lineup.get("formation")
    checks["formation_match"] = user_formation is None or user_formation == lineup_formation
    if not checks["formation_match"]:
        contradictions.append({"field": "formation", "top_level": user_formation, "governed": lineup_formation})

    cap_section = user_report.get("captaincy") or {}
    cap_model = cap_section.get("model") or {}
    user_cap = ((cap_model.get("captain") or {}).get("name") or (cap_section.get("facts") or {}).get("model_candidate"))
    user_vice = ((cap_model.get("vice") or {}).get("name") or (cap_section.get("facts") or {}).get("vice_candidate"))
    lineup_cap = (lineup.get("captain") or {}).get("name")
    lineup_vice = (lineup.get("vice_captain") or {}).get("name")
    checks["captain_match"] = user_cap is None or user_cap == lineup_cap
    checks["vice_match"] = user_vice is None or user_vice == lineup_vice
    if not checks["captain_match"]:
        contradictions.append({"field": "captain", "top_level": user_cap, "governed": lineup_cap})
    if not checks["vice_match"]:
        contradictions.append({"field": "vice_captain", "top_level": user_vice, "governed": lineup_vice})

    user_chip = _norm_chip((((user_report.get("chip") or {}).get("facts") or {}).get("active_chip")))
    governed_chip = _norm_chip((lineup.get("chip_context") or {}).get("active_chip"))
    checks["chip_match"] = user_chip == governed_chip
    if not checks["chip_match"]:
        contradictions.append({"field": "active_chip", "top_level": user_chip, "governed": governed_chip})

    top_comparisons = list(comparator.get("top_comparisons") or [])
    incomplete = []
    actionable = []
    for index, row in enumerate(top_comparisons):
        actionability = row.get("actionability") or {}
        if not actionability.get("level") or not actionability.get("reason"):
            incomplete.append(index)
        if actionability.get("level") == "ACTIONABLE_CHANGE":
            actionable.append(row)
    checks["lower_recommendations_have_actionability_and_reason"] = not incomplete
    if incomplete:
        contradictions.append({"field": "lower_recommendation_contract", "missing_indices": incomplete[:10]})

    decision = user_report.get("decision") or {}
    squad_decision = str(decision.get("squad") or "").upper()
    overall = str(decision.get("overall") or "").upper()
    actionable_vs_hold = bool(actionable and squad_decision == "HOLD")
    checks["no_actionable_change_hidden_under_hold"] = not actionable_vs_hold
    if actionable_vs_hold:
        contradictions.append({
            "field": "transfer_actionability",
            "top_level": squad_decision,
            "governed": "ACTIONABLE_CHANGE",
            "count": len(actionable),
        })

    explicit_divergence = overall == "REVIEW_DIVERGENCE"
    status = "CONSISTENT" if not contradictions else ("REVIEW_DIVERGENCE" if explicit_divergence else "INCONSISTENT")
    return {
        "status": status,
        "contradiction_count": len(contradictions),
        "contradictions": contradictions,
        "checks": checks,
        "actionable_change_count": len(actionable),
        "explicit_review_divergence": explicit_divergence,
        "governance": {
            "single_arbitration_layer": True,
            "top_level_and_lower_level_must_agree": True,
            "review_divergence_must_be_explicit": True,
            "lower_recommendations_require_actionability_and_reason": True,
        },
    }


def assert_decision_consistency(result: dict[str, Any]) -> None:
    if result.get("status") == "INCONSISTENT":
        fields = [str(row.get("field")) for row in result.get("contradictions") or []]
        raise RuntimeError(f"decision arbitration found contradictory output: {fields}")
