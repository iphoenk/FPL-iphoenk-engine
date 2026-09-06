from __future__ import annotations

from copy import deepcopy
from typing import Any

ALLOWED_ENTITY_SCOPES = {
    "PLAYER",
    "TEAM",
    "FIXTURE",
    "EVENT",
    "COMPETITION",
    "FEED",
}


def source_entity_scopes(sources: list[dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    """Return validated explicit identity scopes keyed by source id.

    Undeclared scopes intentionally become an empty tuple. V6 must not invent an
    identity obligation for a source merely because it was successfully fetched.
    """
    out: dict[str, tuple[str, ...]] = {}
    for source in sources:
        source_id = str(source["id"])
        scopes = tuple(str(value).upper() for value in source.get("entity_scopes") or [])
        unknown = sorted(set(scopes) - ALLOWED_ENTITY_SCOPES)
        if unknown:
            raise ValueError(f"unsupported entity scopes for {source_id}: {unknown!r}")
        if len(set(scopes)) != len(scopes):
            raise ValueError(f"duplicate entity scopes for {source_id}")
        out[source_id] = scopes
    return out


def _aggregate(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "NOT_APPLICABLE"
    states = {str(row.get("identity_health") or "RED") for row in rows}
    if "RED" in states:
        return "RED"
    if "AMBER" in states:
        return "AMBER"
    return "GREEN"


def apply_entity_scopes(
    identity_map: dict[str, Any],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Remove semantically irrelevant identity failures from the identity artifact.

    The deterministic bridge builder remains responsible for producing mappings.
    This projection only decides which entity families a source is actually required
    to map. No source-native identifier is created or guessed here.
    """
    out = deepcopy(identity_map)
    scopes_by_source = source_entity_scopes(sources)

    def relevant(scope: str) -> set[str]:
        return {
            source_id
            for source_id, scopes in scopes_by_source.items()
            if source_id != "official_fpl" and scope in scopes
        }

    player_sources = relevant("PLAYER")
    team_sources = relevant("TEAM")
    fixture_sources = relevant("FIXTURE")

    player_coverage = {
        source_id: row
        for source_id, row in dict(out.get("coverage") or {}).items()
        if source_id in player_sources
    }
    out["coverage"] = player_coverage

    for mapping in (out.get("mappings") or {}).values():
        if not isinstance(mapping, dict):
            continue
        mapping["unresolved"] = {
            source_id: status
            for source_id, status in dict(mapping.get("unresolved") or {}).items()
            if source_id in player_sources
        }
        mapping["links"] = {
            source_id: link
            for source_id, link in dict(mapping.get("links") or {}).items()
            if source_id in player_sources
        }

    bridges = dict(out.get("entity_bridges") or {})
    player_bridge = dict(bridges.get("player") or {})
    team_bridge = dict(bridges.get("team") or {})
    fixture_bridge = dict(bridges.get("fixture") or {})

    player_bridge["coverage"] = player_coverage
    team_bridge["coverage"] = {
        source_id: row
        for source_id, row in dict(team_bridge.get("coverage") or {}).items()
        if source_id in team_sources
    }
    fixture_bridge["coverage"] = {
        source_id: row
        for source_id, row in dict(fixture_bridge.get("coverage") or {}).items()
        if source_id in fixture_sources
    }

    scope_health = {
        "PLAYER": _aggregate(list(player_bridge.get("coverage", {}).values())),
        "TEAM": _aggregate(list(team_bridge.get("coverage", {}).values())),
        "FIXTURE": _aggregate(list(fixture_bridge.get("coverage", {}).values())),
    }
    player_bridge["identity_health"] = scope_health["PLAYER"]
    team_bridge["identity_health"] = scope_health["TEAM"]
    fixture_bridge["identity_health"] = scope_health["FIXTURE"]
    bridges["player"] = player_bridge
    bridges["team"] = team_bridge
    bridges["fixture"] = fixture_bridge

    out["entity_bridges"] = bridges
    out["identity_health"] = scope_health["PLAYER"]
    out["scope_health"] = scope_health
    out["source_entity_scopes"] = {
        source_id: list(scopes) for source_id, scopes in scopes_by_source.items()
    }
    out["governance"] = {
        **dict(out.get("governance") or {}),
        "identity_health_is_entity_scope_aware": True,
        "undeclared_entity_scope_is_not_applicable": True,
        "entity_scope_projection_does_not_create_mappings": True,
    }

    scoped_states = [state for state in scope_health.values() if state != "NOT_APPLICABLE"]
    if not scoped_states:
        out["bridge_identity_health"] = "NOT_APPLICABLE"
    elif "RED" in scoped_states:
        out["bridge_identity_health"] = "AMBER"
    elif "AMBER" in scoped_states:
        out["bridge_identity_health"] = "AMBER"
    else:
        out["bridge_identity_health"] = "GREEN"
    return out
