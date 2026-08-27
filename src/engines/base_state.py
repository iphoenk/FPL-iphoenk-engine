from __future__ import annotations

from typing import Any

from src.rules import ELEMENT_TYPE_TO_POSITION
from src.utils import parse_dt, utcnow

ENTRY_FIELDS = [
    "summary_overall_points",
    "summary_overall_rank",
    "summary_event_points",
    "summary_event_rank",
    "current_event",
    "last_deadline_bank",
    "last_deadline_value",
    "last_deadline_total_transfers",
]

LIVE_STAT_FIELDS = [
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "saves",
    "bonus",
    "bps",
    "total_points",
    "defensive_contribution",
]


def detect_phase(bootstrap: dict[str, Any]) -> dict[str, Any]:
    events = list(bootstrap.get("events") or [])
    current = next((event for event in events if event.get("is_current")), None)
    nxt = next((event for event in events if event.get("is_next")), None)
    finished = [event for event in events if event.get("finished")]
    last = max(finished, key=lambda event: int(event["id"])) if finished else None
    planning = None
    if current:
        deadline = parse_dt(current.get("deadline_time"))
        planning = current if deadline and deadline > utcnow() else (nxt or current)
    else:
        planning = nxt
    return {
        "current_gw": current["id"] if current else None,
        "next_gw": nxt["id"] if nxt else None,
        "last_finished_gw": last["id"] if last else None,
        "planning_gw": planning["id"] if planning else None,
        "submitted_gw": (current or last or {}).get("id"),
        "scoring_gw": current["id"] if current else None,
        "deadline_time": planning.get("deadline_time") if planning else None,
        "is_live_event": bool(current and not current.get("finished")),
    }


def bootstrap_maps(bootstrap: dict[str, Any]):
    teams = {int(team["id"]): team["name"] for team in bootstrap.get("teams") or []}
    positions = dict(ELEMENT_TYPE_TO_POSITION)
    by_id = {int(player["id"]): player for player in bootstrap.get("elements") or []}
    return teams, positions, by_id


def resolve_locked_player(row: dict[str, Any], by_id: dict[int, dict[str, Any]], teams: dict[int, str], positions: dict[int, str]):
    element = row.get("element")
    if element is None:
        raise RuntimeError(f"FAIL CLOSED: locked player {row.get('name')} has no canonical element ID")
    player = by_id.get(int(element))
    if not player:
        raise RuntimeError(f"FAIL CLOSED: locked element {element} ({row.get('name')}) not found in bootstrap")

    actual_position = positions.get(player.get("element_type"))
    expected_position = row.get("position")
    if expected_position and actual_position != expected_position:
        raise RuntimeError(
            f"FAIL CLOSED: element {element} position mismatch: expected {expected_position}, got {actual_position}"
        )

    expected_web_name = row.get("expected_web_name")
    if expected_web_name and player.get("web_name") != expected_web_name:
        raise RuntimeError(
            f"FAIL CLOSED: element {element} name mismatch: expected {expected_web_name}, got {player.get('web_name')}"
        )

    expected_team = row.get("expected_team")
    actual_team = teams.get(player.get("team"))
    if expected_team and actual_team != expected_team:
        raise RuntimeError(
            f"FAIL CLOSED: element {element} team mismatch: expected {expected_team}, got {actual_team}"
        )
    return player


def expanded_live(element_live: dict[str, Any]) -> dict[str, Any]:
    stats = element_live.get("stats") or {}
    out = {key: stats.get(key) for key in LIVE_STAT_FIELDS if key in stats}
    out["explain"] = element_live.get("explain")
    return out


def native_entry_summary(entry: dict[str, Any] | None, fetched_at: str | None = None) -> dict[str, Any]:
    payload = entry or {}
    out = {key: payload.get(key) for key in ["id", *ENTRY_FIELDS]}
    out["fetched_at"] = fetched_at
    return out
