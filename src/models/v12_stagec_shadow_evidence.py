"""Stage C shadow-only evidence admission for coach, formation, role and availability.

Never infer observed tactical evidence from an Official FPL position. This gate
only classifies provenance; it does not alter numeric P(start) or xMins.
"""
from __future__ import annotations

from typing import Any, Mapping

FIELDS = ("coach", "formation", "role", "availability")
VALID_SOURCES = frozenset({"OFFICIAL_FPL", "V6_OBSERVED_MATCH", "CERTIFIED_PROVIDER_BRIDGE"})


def audit_stagec_context(
    official_player_ids: list[int],
    observations: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Audit bounded observed evidence without promoting missing data to facts."""
    ids = set(official_player_ids)
    if not ids or len(ids) != len(official_player_ids) or any(
        type(value) is not int or value <= 0 for value in official_player_ids
    ):
        raise ValueError("OFFICIAL_UNIVERSE_INVALID")
    admitted: dict[tuple[int, str, str], dict[str, Any]] = {}
    rejected: dict[str, int] = {}
    conflicted: set[tuple[int, str, str]] = set()
    for row in observations:
        player_id = row.get("element")
        field = row.get("field")
        source = row.get("source")
        match_id = str(row.get("match_id") or "").strip()
        value = row.get("value")
        reason = None
        if type(player_id) is not int or player_id not in ids:
            reason = "UNMAPPED_PLAYER"
        elif field not in FIELDS:
            reason = "UNKNOWN_FIELD"
        elif source not in VALID_SOURCES:
            reason = "UNTRUSTED_SOURCE"
        elif not match_id or value is None or not str(value).strip():
            reason = "MISSING_MATCH_OR_VALUE"
        elif field in {"coach", "formation", "role"} and source == "OFFICIAL_FPL":
            reason = "FPL_POSITION_NOT_TACTICAL_PROOF"
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        key = (player_id, field, match_id)
        normalized = {"element": player_id, "field": field, "match_id": match_id,
                      "source": source, "value": str(value).strip()}
        if key in conflicted:
            rejected["CONFLICTING_OBSERVATION"] = rejected.get("CONFLICTING_OBSERVATION", 0) + 1
            continue
        if key in admitted and admitted[key]["value"] != normalized["value"]:
            rejected["CONFLICTING_OBSERVATION"] = rejected.get("CONFLICTING_OBSERVATION", 0) + 1
            del admitted[key]
            conflicted.add(key)
            continue
        admitted[key] = normalized
    by_field = {field: len({r["element"] for r in admitted.values() if r["field"] == field}) for field in FIELDS}
    return {
        "contract": "V12_STAGEC_SHADOW_EVIDENCE_V1",
        "authority": "SHADOW_ONLY",
        "numeric_model_effect": "NONE",
        "official_universe_count": len(ids),
        "observed_players_by_field": by_field,
        "admitted_observations": len(admitted),
        "rejected_observations_by_reason": rejected,
        "calibration_state": "PENDING_OUT_OF_SAMPLE",
        "production_activation_allowed": False,
    }
