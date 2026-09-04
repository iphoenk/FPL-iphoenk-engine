from __future__ import annotations

from typing import Any

from .http_client import utc_now
from .identity import external_ids_for_player


def _official_bootstrap(official_snapshot: dict[str, Any]) -> dict[str, Any]:
    return ((official_snapshot.get("official") or {}).get("bootstrap") or {})


def build_canonical_players(
    official_snapshot: dict[str, Any],
    source_ids: list[str],
    identity_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bootstrap = _official_bootstrap(official_snapshot)
    identity = identity_map or {}
    rows = []
    for player in bootstrap.get("elements") or []:
        element_id = player.get("id")
        if element_id is None:
            continue
        external_ids, identity_links = external_ids_for_player(identity, int(element_id), source_ids)
        rows.append(
            {
                "canonical_player_id": f"fpl:{element_id}",
                "official_fpl_element_id": element_id,
                "official_code": player.get("code"),
                "web_name": player.get("web_name"),
                "first_name": player.get("first_name"),
                "second_name": player.get("second_name"),
                "team_id": player.get("team"),
                "element_type": player.get("element_type"),
                "status": player.get("status"),
                "external_ids": external_ids,
                "identity_links": identity_links,
                "identity_authority": "official_fpl",
            }
        )
    return {
        "schema_version": 2,
        "generated_at": utc_now(),
        "authority": "official_fpl",
        "canonical_key": "official_fpl_element_id",
        "player_count": len(rows),
        "identity_map_path": "data/v6/evidence/player_identity_map.json",
        "players": rows,
    }


def build_canonical_teams(official_snapshot: dict[str, Any]) -> dict[str, Any]:
    bootstrap = _official_bootstrap(official_snapshot)
    rows = []
    for team in bootstrap.get("teams") or []:
        team_id = team.get("id")
        if team_id is None:
            continue
        rows.append(
            {
                "canonical_team_id": f"fpl-team:{team_id}",
                "official_fpl_team_id": team_id,
                "code": team.get("code"),
                "name": team.get("name"),
                "short_name": team.get("short_name"),
                "identity_authority": "official_fpl",
            }
        )
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "authority": "official_fpl",
        "team_count": len(rows),
        "teams": rows,
    }


def build_canonical_fixtures(official_snapshot: dict[str, Any]) -> dict[str, Any]:
    fixtures = (official_snapshot.get("official") or {}).get("fixtures") or []
    rows = []
    for fixture in fixtures:
        fixture_id = fixture.get("id")
        if fixture_id is None:
            continue
        rows.append(
            {
                "canonical_fixture_id": f"fpl-fixture:{fixture_id}",
                "official_fpl_fixture_id": fixture_id,
                "event": fixture.get("event"),
                "kickoff_time": fixture.get("kickoff_time"),
                "team_h": fixture.get("team_h"),
                "team_a": fixture.get("team_a"),
                "finished": fixture.get("finished"),
                "started": fixture.get("started"),
                "identity_authority": "official_fpl",
            }
        )
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "authority": "official_fpl",
        "fixture_count": len(rows),
        "fixtures": rows,
    }


def build_lineage_catalog(config: dict[str, Any]) -> dict[str, Any]:
    sources = []
    groups: dict[str, list[str]] = {}
    for source in config.get("sources") or []:
        group = str(source.get("independence_group") or source["id"])
        groups.setdefault(group, []).append(source["id"])
        sources.append(
            {
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
                "independence_group": group,
                "derived_from": source.get("derived_from"),
                "notes": source.get("notes"),
            }
        )
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "rule": "Sources sharing an independence_group must not be counted as independent confirmations.",
        "groups": groups,
        "sources": sources,
    }


def build_evidence_index(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for source_id, payload in results.items():
        rows.append(
            {
                "source_id": source_id,
                "health": payload.get("health"),
                "availability": payload.get("availability"),
                "effective_state": payload.get("effective_state"),
                "changed": payload.get("changed"),
                "checked_at": payload.get("checked_at"),
                "path": f"data/v6/current/{source_id}.json",
                "independence_group": payload.get("independence_group"),
            }
        )
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "source_count": len(rows),
        "sources": rows,
    }
