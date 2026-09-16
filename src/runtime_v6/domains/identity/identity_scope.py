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


def _canonical_row(*, entity_label: str, canonical_count: int) -> dict[str, Any]:
    return {
        "strategy": f"OFFICIAL_CANONICAL_{entity_label.upper()}_IDENTITY",
        "deterministic_bridge": True,
        "identity_health": "GREEN" if canonical_count > 0 else "RED",
        "mapped_status": "EXACT" if canonical_count > 0 else "UNMAPPED",
        f"mapped_{entity_label}_count": canonical_count,
        f"canonical_{entity_label}_count": canonical_count,
        "coverage_ratio": 1.0 if canonical_count > 0 else 0.0,
        f"unmapped_{entity_label}_count": 0 if canonical_count > 0 else canonical_count,
        "join_allowed": canonical_count > 0,
        "applicable": True,
        "canonical_source": True,
    }


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
    """Evaluate deterministic identity only for entity scopes a source actually exposes.

    The canonical Official FPL source is represented as exact identity for its own
    PLAYER/TEAM/FIXTURE entities. External sources remain RED/AMBER until a verified
    deterministic bridge exists. Non-applicable scopes are never converted into a
    false failure and no name/fuzzy inference is introduced here.
    """
    out = deepcopy(identity_map)
    canonical_source = str(out.get("canonical_authority") or "official_fpl")
    player_coverage = dict(out.get("coverage") or {})
    bridges = dict(out.get("entity_bridges") or {})
    team_bridge = dict(bridges.get("team") or {})
    fixture_bridge = dict(bridges.get("fixture") or {})
    team_coverage = dict(team_bridge.get("coverage") or {})
    fixture_coverage = dict(fixture_bridge.get("coverage") or {})

    canonical_player_count = int(out.get("canonical_player_count") or 0)
    canonical_team_count = int(team_bridge.get("canonical_team_count") or 0)
    canonical_fixture_count = int(fixture_bridge.get("canonical_fixture_count") or 0)

    per_source: dict[str, dict[str, Any]] = {}
    source_ids = sorted(
        set(source_scopes)
        | set(player_coverage)
        | set(team_coverage)
        | set(fixture_coverage)
        | {canonical_source}
    )
    for source_id in source_ids:
        scopes = set(source_scopes.get(source_id) or [])
        if source_id == canonical_source:
            player = (
                _canonical_row(entity_label="player", canonical_count=canonical_player_count)
                if "PLAYER" in scopes
                else _not_applicable(player_coverage.get(source_id))
            )
            team = (
                _canonical_row(entity_label="team", canonical_count=canonical_team_count)
                if "TEAM" in scopes
                else _not_applicable(team_coverage.get(source_id))
            )
            fixture = (
                _canonical_row(entity_label="fixture", canonical_count=canonical_fixture_count)
                if "FIXTURE" in scopes
                else _not_applicable(fixture_coverage.get(source_id))
            )
        else:
            player = (
                _mark_applicable(player_coverage.get(source_id))
                if "PLAYER" in scopes
                else _not_applicable(player_coverage.get(source_id))
            )
            team = (
                _mark_applicable(team_coverage.get(source_id))
                if "TEAM" in scopes
                else _not_applicable(team_coverage.get(source_id))
            )
            fixture = (
                _mark_applicable(fixture_coverage.get(source_id))
                if "FIXTURE" in scopes
                else _not_applicable(fixture_coverage.get(source_id))
            )
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
    external_rows = [
        row["player"]
        for source_id, row in per_source.items()
        if source_id != canonical_source
    ]
    out["identity_health"] = _aggregate(external_rows)
    out["bridge_identity_health"] = _aggregate(
        [
            entity
            for source_id, row in per_source.items()
            if source_id != canonical_source
            for entity in (row["player"], row["team"], row["fixture"])
        ]
    )
    out.setdefault("governance", {})["identity_health_is_entity_scope_aware"] = True
    out["governance"]["non_applicable_entity_scopes_are_not_red"] = True
    out["governance"]["canonical_source_identity_is_exact_by_definition"] = True
    out["governance"]["canonical_source_is_excluded_from_external_bridge_health"] = True
    return out
