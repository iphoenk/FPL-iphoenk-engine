from __future__ import annotations

import csv
import io
from typing import Any

from .http_client import utc_now

IDENTITY_EXACT = "EXACT"
IDENTITY_VERIFIED_MANUAL = "VERIFIED_MANUAL"
IDENTITY_UNMAPPED = "UNMAPPED"
IDENTITY_AMBIGUOUS = "AMBIGUOUS"
IDENTITY_ORPHANED = "ORPHANED"
IDENTITY_STALE = "STALE"
CANONICAL_JOINABLE_STATUSES = {IDENTITY_EXACT, IDENTITY_VERIFIED_MANUAL}


def _official_bootstrap(official_snapshot: dict[str, Any]) -> dict[str, Any]:
    return dict((official_snapshot.get("official") or {}).get("bootstrap") or {})


def _official_elements(official_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_official_bootstrap(official_snapshot).get("elements") or [])


def _official_teams(official_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_official_bootstrap(official_snapshot).get("teams") or [])


def _official_fixtures(official_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return list((official_snapshot.get("official") or {}).get("fixtures") or [])


def _csv_rows(payload: dict[str, Any], request_id: str) -> list[dict[str, str]]:
    body = (((payload.get("data") or {}).get(request_id) or {}).get("body"))
    if not isinstance(body, str) or not body.strip():
        return []
    try:
        return list(csv.DictReader(io.StringIO(body)))
    except (csv.Error, TypeError):
        return []


def _exact_link(
    *,
    source_id: str,
    external_id: Any,
    method: str,
    evidence_request_id: str | None,
    provider_code: Any = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    link = {
        "source_id": source_id,
        "source_native_id": external_id,
        "external_id": external_id,
        "mapping_method": method,
        "method": method,
        "verification_status": IDENTITY_EXACT,
        "status": IDENTITY_EXACT,
        "confidence": 1.0,
        "verified": True,
        "joinable": True,
        "verified_at": utc_now(),
        "evidence_request_id": evidence_request_id,
        "provenance": provenance or {"source_id": source_id},
    }
    if provider_code is not None:
        link["provider_code"] = provider_code
    return link


def _vaastav_links(
    official_by_id: dict[int, dict[str, Any]],
    payload: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    links: dict[int, dict[str, Any]] = {}
    for row in _csv_rows(payload, "players_raw"):
        try:
            element_id = int(str(row.get("id") or "").strip())
            provider_code = int(str(row.get("code") or "").strip())
        except ValueError:
            continue
        official = official_by_id.get(element_id)
        if official is None:
            continue
        try:
            official_code = int(official.get("code"))
        except (TypeError, ValueError):
            continue
        if provider_code != official_code:
            continue
        links[element_id] = _exact_link(
            source_id="vaastav_fpl",
            external_id=element_id,
            method="FPL_ELEMENT_ID_AND_CODE_EXACT",
            evidence_request_id="players_raw",
            provider_code=provider_code,
            provenance={"source_id": "vaastav_fpl", "request_id": "players_raw"},
        )
    return links


def _coverage_health(mapped: int, canonical: int, deterministic_bridge: bool) -> str:
    if not deterministic_bridge or canonical <= 0:
        return "RED"
    if mapped == canonical:
        return "GREEN"
    if mapped > 0:
        return "AMBER"
    return "RED"


def _unmapped_external_coverage(
    source_ids: list[str],
    *,
    canonical_count: int,
    entity_label: str,
) -> dict[str, dict[str, Any]]:
    return {
        source_id: {
            "strategy": "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE",
            "deterministic_bridge": False,
            "identity_health": "RED",
            "mapped_status": IDENTITY_UNMAPPED,
            f"mapped_{entity_label}_count": 0,
            f"canonical_{entity_label}_count": canonical_count,
            "coverage_ratio": 0.0,
            f"unmapped_{entity_label}_count": canonical_count,
            "join_allowed": False,
        }
        for source_id in source_ids
        if source_id != "official_fpl"
    }


def _team_identity_bridge(
    official_snapshot: dict[str, Any],
    results: dict[str, dict[str, Any]],
    source_ids: list[str],
) -> dict[str, Any]:
    teams = {
        int(team["id"]): team
        for team in _official_teams(official_snapshot)
        if team.get("id") is not None
    }
    generated_at = utc_now()
    mappings: dict[str, dict[str, Any]] = {}
    for team_id, team in teams.items():
        mappings[str(team_id)] = {
            "canonical_team_id": f"fpl-team:{team_id}",
            "official_fpl_team_id": team_id,
            "source_id": "official_fpl",
            "source_native_team_id": team_id,
            "name": team.get("name"),
            "short_name": team.get("short_name"),
            "mapping_method": "OFFICIAL_CANONICAL_TEAM_ID",
            "verification_status": IDENTITY_EXACT,
            "verified_at": generated_at,
            "provenance": {"source_id": "official_fpl", "source_path": "bootstrap.teams"},
            "links": {},
        }

    coverage = _unmapped_external_coverage(
        source_ids,
        canonical_count=len(teams),
        entity_label="team",
    )

    predictor_rows = list(
        (((results.get("official_price_predictor") or {}).get("data") or {}).get("players")) or []
    )
    if "official_price_predictor" in source_ids and predictor_rows:
        predictor_team_ids = {
            int(row["team"])
            for row in predictor_rows
            if row.get("team") is not None
        }
        mapped_ids = sorted(set(teams) & predictor_team_ids)
        for team_id in mapped_ids:
            mappings[str(team_id)]["links"]["official_price_predictor"] = _exact_link(
                source_id="official_price_predictor",
                external_id=team_id,
                method="OFFICIAL_DERIVED_SHARED_TEAM_ID",
                evidence_request_id=None,
                provenance={
                    "source_id": "official_price_predictor",
                    "derived_from": "official_fpl.bootstrap",
                },
            )
        coverage["official_price_predictor"] = {
            "strategy": "OFFICIAL_DERIVED_SHARED_TEAM_ID",
            "deterministic_bridge": True,
            "identity_health": _coverage_health(len(mapped_ids), len(teams), True),
            "mapped_status": IDENTITY_EXACT if mapped_ids else IDENTITY_UNMAPPED,
            "mapped_team_count": len(mapped_ids),
            "canonical_team_count": len(teams),
            "coverage_ratio": round(len(mapped_ids) / len(teams), 6) if teams else 0.0,
            "unmapped_team_count": max(0, len(teams) - len(mapped_ids)),
            "join_allowed": bool(mapped_ids),
        }

    return {
        "canonical_authority": "official_fpl",
        "canonical_key": "official_fpl_team_id",
        "canonical_identity_health": "GREEN" if teams else "RED",
        "canonical_team_count": len(teams),
        "coverage": coverage,
        "mappings": mappings,
    }


def _fixture_identity_bridge(
    official_snapshot: dict[str, Any],
    source_ids: list[str],
) -> dict[str, Any]:
    fixtures = {
        int(fixture["id"]): fixture
        for fixture in _official_fixtures(official_snapshot)
        if fixture.get("id") is not None
    }
    generated_at = utc_now()
    mappings: dict[str, dict[str, Any]] = {}
    for fixture_id, fixture in fixtures.items():
        mappings[str(fixture_id)] = {
            "canonical_fixture_id": f"fpl-fixture:{fixture_id}",
            "official_fpl_fixture_id": fixture_id,
            "source_id": "official_fpl",
            "source_native_fixture_id": fixture_id,
            "event": fixture.get("event"),
            "kickoff_time": fixture.get("kickoff_time"),
            "official_fpl_team_h_id": fixture.get("team_h"),
            "official_fpl_team_a_id": fixture.get("team_a"),
            "mapping_method": "OFFICIAL_CANONICAL_FIXTURE_ID",
            "verification_status": IDENTITY_EXACT,
            "verified_at": generated_at,
            "provenance": {"source_id": "official_fpl", "source_path": "fixtures"},
            "links": {},
        }

    return {
        "canonical_authority": "official_fpl",
        "canonical_key": "official_fpl_fixture_id",
        "canonical_identity_health": "GREEN" if fixtures else "RED",
        "canonical_fixture_count": len(fixtures),
        "coverage": _unmapped_external_coverage(
            source_ids,
            canonical_count=len(fixtures),
            entity_label="fixture",
        ),
        "mappings": mappings,
    }


def build_player_identity_map(
    official_snapshot: dict[str, Any],
    results: dict[str, dict[str, Any]],
    source_ids: list[str],
) -> dict[str, Any]:
    elements = _official_elements(official_snapshot)
    official_by_id = {
        int(player["id"]): player
        for player in elements
        if player.get("id") is not None
    }
    canonical_ids = list(official_by_id)

    provider_links: dict[str, dict[int, dict[str, Any]]] = {}
    coverage: dict[str, dict[str, Any]] = {}

    if "official_price_predictor" in source_ids:
        derived_rows = list(
            (((results.get("official_price_predictor") or {}).get("data") or {}).get("players")) or []
        )
        row_ids = {
            int(row["id"])
            for row in derived_rows
            if row.get("id") is not None
        }
        provider_links["official_price_predictor"] = {
            element_id: _exact_link(
                source_id="official_price_predictor",
                external_id=element_id,
                method="OFFICIAL_DERIVED_SHARED_ELEMENT_ID",
                evidence_request_id=None,
                provenance={
                    "source_id": "official_price_predictor",
                    "derived_from": "official_fpl.bootstrap",
                },
            )
            for element_id in canonical_ids
            if element_id in row_ids
        }

    if "vaastav_fpl" in source_ids:
        provider_links["vaastav_fpl"] = _vaastav_links(
            official_by_id,
            results.get("vaastav_fpl") or {},
        )

    generated_at = utc_now()
    mappings: dict[str, dict[str, Any]] = {}
    for element_id, official in official_by_id.items():
        links: dict[str, dict[str, Any]] = {}
        unresolved: dict[str, str] = {}
        for source_id in source_ids:
            if source_id == "official_fpl":
                continue
            link = (provider_links.get(source_id) or {}).get(element_id)
            if link:
                links[source_id] = link
            else:
                unresolved[source_id] = IDENTITY_UNMAPPED
        mappings[str(element_id)] = {
            "canonical_player_id": f"fpl:{element_id}",
            "official_fpl_element_id": element_id,
            "source_id": "official_fpl",
            "source_native_player_id": element_id,
            "official_code": official.get("code"),
            "web_name": official.get("web_name"),
            "mapping_method": "OFFICIAL_CANONICAL_ELEMENT_ID",
            "verification_status": IDENTITY_EXACT,
            "canonical_status": IDENTITY_EXACT,
            "verified_at": generated_at,
            "provenance": {"source_id": "official_fpl", "source_path": "bootstrap.elements"},
            "links": links,
            "unresolved": unresolved,
        }

    for source_id in source_ids:
        if source_id == "official_fpl":
            continue
        links = provider_links.get(source_id) or {}
        mapped = len(links)
        if source_id == "official_price_predictor":
            strategy = "OFFICIAL_DERIVED_SHARED_ELEMENT_ID"
            deterministic_bridge = True
        elif source_id == "vaastav_fpl":
            strategy = "FPL_ELEMENT_ID_AND_CODE_EXACT"
            deterministic_bridge = True
        else:
            strategy = "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE"
            deterministic_bridge = False
        identity_health = _coverage_health(mapped, len(canonical_ids), deterministic_bridge)
        coverage[source_id] = {
            "strategy": strategy,
            "deterministic_bridge": deterministic_bridge,
            "identity_health": identity_health,
            "mapped_status": IDENTITY_EXACT if mapped else IDENTITY_UNMAPPED,
            "mapped_player_count": mapped,
            "canonical_player_count": len(canonical_ids),
            "coverage_ratio": round(mapped / len(canonical_ids), 6) if canonical_ids else 0.0,
            "unmapped_player_count": max(0, len(canonical_ids) - mapped),
            "join_allowed": deterministic_bridge and mapped > 0,
        }

    aggregate_health = "GREEN"
    external_coverages = list(coverage.values())
    if any(row.get("identity_health") == "RED" for row in external_coverages):
        aggregate_health = "AMBER" if any(row.get("mapped_player_count", 0) for row in external_coverages) else "RED"
    elif any(row.get("identity_health") == "AMBER" for row in external_coverages):
        aggregate_health = "AMBER"

    team_bridge = _team_identity_bridge(official_snapshot, results, source_ids)
    fixture_bridge = _fixture_identity_bridge(official_snapshot, source_ids)
    bridge_health = aggregate_health
    if team_bridge["canonical_identity_health"] == "RED" or fixture_bridge["canonical_identity_health"] == "RED":
        bridge_health = "RED"
    elif any(
        row.get("identity_health") in {"AMBER", "RED"}
        for bridge in (team_bridge, fixture_bridge)
        for row in (bridge.get("coverage") or {}).values()
    ):
        bridge_health = "AMBER" if bridge_health != "RED" else "RED"

    return {
        "schema_version": 3,
        "generated_at": generated_at,
        "canonical_authority": "official_fpl",
        "canonical_key": "official_fpl_element_id",
        "identity_health": aggregate_health,
        "bridge_identity_health": bridge_health,
        "bridge_scope": ["PLAYER", "TEAM", "FIXTURE"],
        "status_vocabulary": [
            IDENTITY_EXACT,
            IDENTITY_VERIFIED_MANUAL,
            IDENTITY_UNMAPPED,
            IDENTITY_AMBIGUOUS,
            IDENTITY_ORPHANED,
            IDENTITY_STALE,
        ],
        "canonical_joinable_statuses": sorted(CANONICAL_JOINABLE_STATUSES),
        "governance": {
            "fuzzy_name_matching_allowed": False,
            "silent_fuzzy_runtime_join_allowed": False,
            "unverified_ids_are_never_fabricated": True,
            "partial_mapping_is_explicit": True,
            "provider_links_require_deterministic_evidence": True,
            "unmapped_is_safer_than_guessed_join": True,
        },
        "canonical_player_count": len(canonical_ids),
        "coverage": coverage,
        "mappings": mappings,
        "entity_bridges": {
            "player": {
                "canonical_authority": "official_fpl",
                "canonical_key": "official_fpl_element_id",
                "identity_health": aggregate_health,
                "canonical_player_count": len(canonical_ids),
                "coverage": coverage,
            },
            "team": team_bridge,
            "fixture": fixture_bridge,
        },
    }


def external_ids_for_player(
    identity_map: dict[str, Any],
    element_id: int,
    source_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    mapping = dict((identity_map.get("mappings") or {}).get(str(element_id)) or {})
    links = dict(mapping.get("links") or {})
    external_ids = {
        source_id: (
            (links.get(source_id) or {}).get("external_id")
            if (links.get(source_id) or {}).get("status") in CANONICAL_JOINABLE_STATUSES
            else None
        )
        for source_id in source_ids
        if source_id != "official_fpl"
    }
    identity_links = {
        source_id: dict(link)
        for source_id, link in links.items()
        if link.get("status") in CANONICAL_JOINABLE_STATUSES
    }
    return external_ids, identity_links
