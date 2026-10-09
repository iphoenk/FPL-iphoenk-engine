"""Canonical S08/S18/S19 captain report contract validation."""
from __future__ import annotations
from typing import Any, Mapping

_DECISION_KEYS = {"final_captain", "winner", "decision", "selected_captain"}

def _element(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("element_id") or value.get("id") or value.get("player_id")
    return value

def _pair(section: Mapping[str, Any]) -> tuple[Any, Any]:
    content = section.get("content") or {}
    captain = content.get("captain")
    vice = content.get("vice_captain")
    if isinstance(content.get("final_judgement"), Mapping):
        final = content["final_judgement"]
        captain = final.get("final_captain", captain)
        vice = final.get("vice", vice)
    board = content.get("action_board") or {}
    if isinstance(board, Mapping) and isinstance(board.get("captain_decision"), Mapping):
        decision = board["captain_decision"]
        captain = decision.get("captain", captain)
        vice = decision.get("vice_captain", vice)
    return _element(captain), _element(vice)

def validate_captain_report_contracts(sections: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    s15b = sections.get("S15B") or {}
    s15b_content = s15b.get("content") or {}
    forbidden = sorted(key for key in s15b_content if str(key).lower() in _DECISION_KEYS)
    if forbidden:
        errors.append("S15B_DECISION_LEAK")
    s15b_complete = str(s15b.get("state") or "").upper() == "COMPLETE"
    pairs = {sid: _pair(sections.get(sid) or {}) for sid in ("S08", "S18", "S19")}
    available = [pair for pair in pairs.values() if pair != (None, None)]
    if s15b_complete and len(available) == 3:
        if len(set(available)) != 1:
            errors.append("CANONICAL_CVC_MISMATCH")
        if available[0][0] == available[0][1]:
            errors.append("CAPTAIN_EQUALS_VICE")
    degraded = (not s15b_complete) or bool(errors)
    return {"valid": not errors, "errors": errors,
            "degradation_state": "DEGRADED" if degraded else "COMPLETE",
            "canonical_pair": available[0] if available and len(set(available)) == 1 else None,
            "s15b_evidence_only": not bool(forbidden), "independent_winner": False}
