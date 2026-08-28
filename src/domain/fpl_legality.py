from __future__ import annotations

from typing import Any

from src.rules import LINEUP_RULES, RULESET_ID, SQUAD_RULES


def formation_from_rows(rows: list[dict[str, Any]]) -> str | None:
    counts = {
        position: sum(1 for player in rows if player.get("position") == position)
        for position in ("DEF", "MID", "FWD")
    }
    formation = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
    return formation if formation in set(LINEUP_RULES.get("legal_formations") or []) else None


def legal_starting_xi(rows: list[dict[str, Any]]) -> bool:
    if len(rows) != int(LINEUP_RULES.get("starting_xi_size") or 0):
        return False
    if sum(1 for player in rows if player.get("position") == "GK") != int(
        LINEUP_RULES.get("starting_goalkeepers") or 0
    ):
        return False
    element_ids = [int(player.get("element") or -1) for player in rows]
    if len(element_ids) != len(set(element_ids)):
        return False
    return formation_from_rows(rows) is not None


def squad_violations(players: list[dict[str, Any]]) -> list[str]:
    violations: list[str] = []
    expected = {key: int(value) for key, value in (SQUAD_RULES.get("position_counts") or {}).items()}
    if len(players) != int(SQUAD_RULES.get("squad_size") or 0):
        violations.append("squad_size")

    counts = {key: 0 for key in expected}
    clubs: dict[int, int] = {}
    seen: set[int] = set()
    duplicate = False
    unknown_position = False
    for player in players:
        element = int(player.get("element") or -1)
        if element in seen:
            duplicate = True
        seen.add(element)
        position = str(player.get("position") or "")
        if position not in counts:
            unknown_position = True
        else:
            counts[position] += 1
        team_id = int(player.get("team_id") or -1)
        clubs[team_id] = clubs.get(team_id, 0) + 1

    if duplicate:
        violations.append("duplicate_element")
    if unknown_position:
        violations.append("unknown_position")
    if counts != expected:
        violations.append("position_counts")
    if max(clubs.values(), default=0) > int(SQUAD_RULES.get("max_players_per_club") or 0):
        violations.append("max_players_per_club")
    return violations


def legal_squad(players: list[dict[str, Any]]) -> bool:
    return not squad_violations(players)


def legality_contract() -> dict[str, Any]:
    return {
        "ruleset_id": RULESET_ID,
        "squad_size": int(SQUAD_RULES.get("squad_size") or 0),
        "position_counts": dict(SQUAD_RULES.get("position_counts") or {}),
        "max_players_per_club": int(SQUAD_RULES.get("max_players_per_club") or 0),
        "starting_xi_size": int(LINEUP_RULES.get("starting_xi_size") or 0),
        "legal_formations": list(LINEUP_RULES.get("legal_formations") or []),
    }
