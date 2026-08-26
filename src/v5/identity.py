from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.rules import ELEMENT_TYPE_TO_POSITION
from src.v5.config_cache import load_json_config

REGISTRY_CONFIG = "config/v5_identity_registry.json"


@dataclass(frozen=True)
class ElementIndex:
    players: dict[int, dict[str, Any]]
    teams: dict[int, dict[str, Any]]


def _cfg() -> dict[str, Any]:
    data = load_json_config(REGISTRY_CONFIG)
    if not isinstance(data.get("fail_closed"), dict):
        raise RuntimeError("invalid V5 identity registry")
    return data


def build_index(bootstrap: dict) -> ElementIndex:
    players = {
        int(row["id"]): row
        for row in bootstrap.get("elements", [])
        if isinstance(row, dict) and row.get("id") is not None
    }
    teams = {
        int(row["id"]): row
        for row in bootstrap.get("teams", [])
        if isinstance(row, dict) and row.get("id") is not None
    }
    return ElementIndex(players=players, teams=teams)


def resolve_element(element_id: int, index: ElementIndex) -> dict[str, Any] | None:
    eid = int(element_id)
    player = index.players.get(eid)
    policy = _cfg()["fail_closed"]
    if player is None:
        if policy.get("missing_element", True):
            raise RuntimeError(f"Official element missing from identity index: {eid}")
        return None
    element_type = int(player.get("element_type") or 0)
    position = ELEMENT_TYPE_TO_POSITION.get(element_type)
    if position is None and policy.get("unknown_position", True):
        raise RuntimeError(f"unknown element type for {eid}: {element_type}")
    team_id = int(player.get("team") or 0)
    team = index.teams.get(team_id)
    if team is None and policy.get("missing_team", True):
        raise RuntimeError(f"Official team missing from identity index: {team_id}")
    return {
        "element": eid,
        "name": player.get("web_name"),
        "team_id": team_id,
        "team": team.get("name") if team else None,
        "team_short_name": team.get("short_name") if team else None,
        "element_type": element_type,
        "position": position,
        "now_cost": player.get("now_cost"),
        "ownership": player.get("selected_by_percent"),
        "status": player.get("status"),
    }


def resolve_many(element_ids: Iterable[int], index: ElementIndex) -> tuple[dict[str, Any], ...]:
    return tuple(resolved for eid in element_ids if (resolved := resolve_element(int(eid), index)) is not None)
