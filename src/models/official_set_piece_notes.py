from __future__ import annotations

"""Normalize Official FPL team set-piece notes as advisory evidence only."""

from typing import Any


SOURCE = "OFFICIAL_FPL_SET_PIECE_NOTES"
_PLACEHOLDER_MESSAGES = {
    "check back for additional notes soon",
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def team_set_piece_note_evidence(
    payload: dict[str, Any] | None,
    team_id: int | None,
) -> dict[str, Any]:
    data = dict(payload or {})
    try:
        wanted = int(team_id) if team_id is not None else None
    except (TypeError, ValueError):
        wanted = None
    team = next(
        (
            dict(row)
            for row in data.get("teams") or []
            if wanted is not None and int(row.get("id") or -1) == wanted
        ),
        None,
    )
    if team is None:
        return {
            "source": SOURCE,
            "team_id": wanted,
            "last_updated": data.get("last_updated"),
            "status": "UNAVAILABLE",
            "notes": [],
            "actionable": False,
            "advisory_only": True,
            "direct_xmins_mutation": False,
            "direct_xpts_mutation": False,
            "direct_start_probability_mutation": False,
        }

    notes = []
    actionable = False
    for raw in team.get("notes") or []:
        if not isinstance(raw, dict):
            continue
        message = _clean(raw.get("info_message"))
        if not message:
            continue
        placeholder = message.casefold() in _PLACEHOLDER_MESSAGES
        actionable = actionable or not placeholder
        notes.append(
            {
                "info_message": message,
                "source_link": _clean(raw.get("source_link")) or None,
                "external_link": bool(raw.get("external_link")),
                "placeholder": placeholder,
            }
        )

    if actionable:
        status = "ACTIONABLE_EVIDENCE"
    elif notes:
        status = "PLACEHOLDER_ONLY"
    else:
        status = "EMPTY"

    return {
        "source": SOURCE,
        "team_id": wanted,
        "last_updated": data.get("last_updated"),
        "status": status,
        "notes": notes,
        "actionable": actionable,
        "advisory_only": True,
        "direct_xmins_mutation": False,
        "direct_xpts_mutation": False,
        "direct_start_probability_mutation": False,
    }


def normalize_official_set_piece_notes(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    teams = {}
    for row in data.get("teams") or []:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        evidence = team_set_piece_note_evidence(data, int(row["id"]))
        teams[str(row["id"])] = evidence
    actionable = sum(row["actionable"] for row in teams.values())
    return {
        "source": SOURCE,
        "last_updated": data.get("last_updated"),
        "teams": teams,
        "team_count": len(teams),
        "actionable_team_count": actionable,
        "evidence_only": True,
        "direct_model_override_forbidden": True,
    }
