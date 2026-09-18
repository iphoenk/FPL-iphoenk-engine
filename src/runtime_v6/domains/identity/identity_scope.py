from __future__ import annotations

from copy import deepcopy
from typing import Any

from .entity_scope import resolve_entity_scope_applicability

_IDENTITY_STATES = {"GREEN", "AMBER", "RED", "NOT_APPLICABLE"}


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
    base.setdefault("deterministic_bridge", False)
    base.setdefault("join_allowed", False)
    base.setdefault("strategy", "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE")
    if str(base.get("identity_health") or "") not in {"GREEN", "AMBER", "RED"}:
        base["identity_health"] = "RED"
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
    states = {
        state if state in _IDENTITY_STATES else "RED"
        for row in applicable
        for state in [str(row.get("identity_health") or "RED")]
    }
    if "RED" in states:
        return "RED"
    if "AMBER" in states:
        return "AMBER"
    return "GREEN"


def _resolved_row(
    *,
    source_id: str,
    entity_type: str,
    source_scopes: dict[str, list[str]],
    row: dict[str, Any] | None,
    canonical_source: str,
    canonical_count: int,
) -> dict[str, Any]:
    applicability = resolve_entity_scope_applicability(source_id, entity_type, source_scopes)
    if not applicability["applicable"]:
        return _not_applicable(row)
    if source_id == canonical_source:
        return _canonical_row(
            entity_label=entity_type.lower(),
            canonical_count=canonical_count,
        )
    return _mark_applicable(row)


def apply_entity_scope_identity_semantics(
    identity_map: dict[str, Any],
    source_scopes: dict[str, list[str]],
) -> dict[str, Any]:
    """Apply one scope authority to all deterministic identity representations."""
    out = deepcopy(identity_map)
    canonical_source = str(out.get("canonical_authority") or "official_fpl")
    player_coverage = dict(out.get("coverage") or {})
    bridges = dict(out.get("entity_bridges") or {})
    player_bridge = dict(bridges.get("player") or {})
    team_bridge = dict(bridges.get("team") or {})
    fixture_bridge = dict(bridges.get("fixture") or {})
    player_bridge_coverage = dict(player_bridge.get("coverage") or {})
    team_coverage = dict(team_bridge.get("coverage") or {})
    fixture_coverage = dict(fixture_bridge.get("coverage") or {})

    canonical_player_count = int(
        out.get("canonical_player_count")
        or player_bridge.get("canonical_player_count")
        or 0
    )
    canonical_team_count = int(team_bridge.get("canonical_team_count") or 0)
    canonical_fixture_count = int(fixture_bridge.get("canonical_fixture_count") or 0)

    per_source: dict[str, dict[str, Any]] = {}
    source_ids = sorted(
        set(source_scopes)
        | set(player_coverage)
        | set(player_bridge_coverage)
        | set(team_coverage)
        | set(fixture_coverage)
        | {canonical_source}
    )
    for source_id in source_ids:
        scopes = resolve_entity_scope_applicability(
            source_id, "PLAYER", source_scopes
        )["entity_scopes"]
        player_seed = player_coverage.get(source_id) or player_bridge_coverage.get(source_id)
        player = _resolved_row(
            source_id=source_id,
            entity_type="PLAYER",
            source_scopes=source_scopes,
            row=player_seed,
            canonical_source=canonical_source,
            canonical_count=canonical_player_count,
        )
        team = _resolved_row(
            source_id=source_id,
            entity_type="TEAM",
            source_scopes=source_scopes,
            row=team_coverage.get(source_id),
            canonical_source=canonical_source,
            canonical_count=canonical_team_count,
        )
        fixture = _resolved_row(
            source_id=source_id,
            entity_type="FIXTURE",
            source_scopes=source_scopes,
            row=fixture_coverage.get(source_id),
            canonical_source=canonical_source,
            canonical_count=canonical_fixture_count,
        )

        player_coverage[source_id] = player
        player_bridge_coverage[source_id] = dict(player)
        team_coverage[source_id] = team
        fixture_coverage[source_id] = fixture
        per_source[source_id] = {
            "entity_scopes": scopes,
            "player": player,
            "team": team,
            "fixture": fixture,
            "identity_health": _aggregate([player, team, fixture]),
        }

    external_player_rows = [
        row["player"]
        for source_id, row in per_source.items()
        if source_id != canonical_source
    ]
    external_entity_rows = [
        entity
        for source_id, row in per_source.items()
        if source_id != canonical_source
        for entity in (row["player"], row["team"], row["fixture"])
    ]

    player_bridge["coverage"] = player_bridge_coverage
    player_bridge["identity_health"] = _aggregate(external_player_rows)
    player_bridge["canonical_player_count"] = canonical_player_count
    team_bridge["coverage"] = team_coverage
    fixture_bridge["coverage"] = fixture_coverage
    bridges["player"] = player_bridge
    bridges["team"] = team_bridge
    bridges["fixture"] = fixture_bridge

    out["coverage"] = player_coverage
    out["entity_bridges"] = bridges
    out["source_entity_identity"] = per_source
    out["identity_health"] = _aggregate(external_player_rows)
    out["bridge_identity_health"] = _aggregate(external_entity_rows)
    out.setdefault("governance", {})["identity_health_is_entity_scope_aware"] = True
    out["governance"]["entity_scopes_are_applicability_authority"] = True
    out["governance"]["non_applicable_entity_scopes_are_not_red"] = True
    out["governance"]["canonical_source_identity_is_exact_by_definition"] = True
    out["governance"]["canonical_source_is_excluded_from_external_bridge_health"] = True
    out["governance"]["player_bridge_semantics_match_source_player_coverage"] = True
    return out


def source_identity_observability(
    identity_map: dict[str, Any],
    source_id: str,
    source_scopes: dict[str, list[str]],
) -> dict[str, Any]:
    """Return report-facing identity states from the canonical source-level truth.

    PLAYER identity remains the backward-compatible identity_health dimension.
    identity_join_health is the aggregate across every applicable join entity.
    """
    source_key = str(source_id)
    row = dict((identity_map.get("source_entity_identity") or {}).get(source_key) or {})
    if not row:
        scoped = apply_entity_scope_identity_semantics(
            identity_map,
            {source_key: list(source_scopes.get(source_key) or [])},
        )
        row = dict((scoped.get("source_entity_identity") or {}).get(source_key) or {})

    by_scope: dict[str, str] = {}
    for entity_type, key in (
        ("PLAYER", "player"),
        ("TEAM", "team"),
        ("FIXTURE", "fixture"),
    ):
        applicability = resolve_entity_scope_applicability(
            source_key, entity_type, source_scopes
        )
        entity_row = dict(row.get(key) or {})
        if not applicability["applicable"]:
            continue
        state = str(entity_row.get("identity_health") or "RED")
        by_scope[entity_type] = state if state in {"GREEN", "AMBER", "RED"} else "RED"

    player_applicability = resolve_entity_scope_applicability(
        source_key, "PLAYER", source_scopes
    )
    if player_applicability["applicable"]:
        player_state = str((row.get("player") or {}).get("identity_health") or "RED")
        if player_state not in {"GREEN", "AMBER", "RED"}:
            player_state = "RED"
    else:
        player_state = "NOT_APPLICABLE"

    join_state = str(row.get("identity_health") or "NOT_APPLICABLE")
    if join_state not in _IDENTITY_STATES:
        join_state = "RED" if by_scope else "NOT_APPLICABLE"

    return {
        "identity_health": player_state,
        "identity_join_health": join_state,
        "identity_by_scope": by_scope,
    }
