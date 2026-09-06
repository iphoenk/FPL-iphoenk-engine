from __future__ import annotations

from copy import deepcopy
from typing import Any


def _not_applicable(row: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(row or {})
    base.update(
        {
            "applicable": False,
            "identity_health": "NOT_APPLICABLE",
            "deterministic_bridge": False,
            "join_allowed": False,
            "strategy": "NOT_APPLICABLE_FOR_ENTITY_SCOPE",
        }
    )
    return base


def _mark_applicable(row: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(row or {})
    base["applicable"] = True
    return base


def _aggregate(rows: list[dict[str, Any]]) -> str:
    applicable = [row for row in rows if row.get("applicable") is True]
    if not applicable:
        return "NOT_APPLICABLE"
    states = {str(row.get("identity_health") or "RED") for row in applicable}
    if "RED" in states:
        return "RED"
    if "AMBER" in states:
        return "AMBER"
    return "GREEN"


def apply_entity_scope_identity_semantics(
    identity_map: dict[str, Any],
    source_scopes: dict[str, list[str]],
) -> dict[str, Any]:
    """Re-label identity coverage only where an entity scope is applicable.

    This does not invent mappings. It only prevents a fixture/feed-only source from
    being reported as a failed PLAYER identity bridge, while retaining RED/AMBER
    for genuinely required but unresolved scopes.
    """
    out = deepcopy(identity_map)
    player_coverage = dict(out.get("coverage") or {})
    bridges = dict(out.get("entity_bridges") or {})
    team_bridge = dict(bridges.get("team") or {})
    fixture_bridge = dict(bridges.get("fixture") or {})
    team_coverage = dict(team_bridge.get("coverage") or {})
    fixture_coverage = dict(fixture_bridge.get("coverage") or {})

    per_source: dict[str, dict[str, Any]] = {}
    source_ids = sorted(set(source_scopes) | set(player_coverage) | set(team_coverage) | set(fixture_coverage))
    for source_id in source_ids:
        scopes = set(source_scopes.get(source_id) or [])
        player = _mark_applicable(player_coverage.get(source_id)) if "PLAYER" in scopes else _not_applicable(player_coverage.get(source_id))
        team = _mark_applicable(team_coverage.get(source_id)) if "TEAM" in scopes else _not_applicable(team_coverage.get(source_id))
        fixture = _mark_applicable(fixture_coverage.get(source_id)) if "FIXTURE" in scopes else _not_applicable(fixture_coverage.get(source_id))
        player_coverage[source_id] = player
        team_coverage[source_id] = team
        fixture_coverage[source_id] = fixture
        per_source[source_id] = {
            "entity_scopes": sorted(scopes),
            "player": player,
            "team": team,
            "fixture": fixture,
            "identity_health": _aggregate([player, team, fixture]),
        }

    team_bridge["coverage"] = team_coverage
    fixture_bridge["coverage"] = fixture_coverage
    bridges["team"] = team_bridge
    bridges["fixture"] = fixture_bridge
    out["coverage"] = player_coverage
    out["entity_bridges"] = bridges
    out["source_entity_identity"] = per_source
    out["identity_health"] = _aggregate([row["player"] for row in per_source.values()])
    out["bridge_identity_health"] = _aggregate(
        [
            entity
            for row in per_source.values()
            for entity in (row["player"], row["team"], row["fixture"])
        ]
    )
    out.setdefault("governance", {})["identity_health_is_entity_scope_aware"] = True
    out["governance"]["non_applicable_entity_scopes_are_not_red"] = True
    return out
