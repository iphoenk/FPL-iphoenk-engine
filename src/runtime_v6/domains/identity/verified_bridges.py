from __future__ import annotations

import csv
import io
from copy import deepcopy
from typing import Any

from .http_client import utc_now

IDENTITY_EXACT = "EXACT"


def _csv_rows(payload: dict[str, Any], request_id: str) -> list[dict[str, str]]:
    body = (((payload.get("data") or {}).get(request_id) or {}).get("body"))
    if not isinstance(body, str) or not body.strip():
        return []
    try:
        return list(csv.DictReader(io.StringIO(body)))
    except (csv.Error, TypeError):
        return []


def _int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _exact_link(
    *,
    source_id: str,
    source_native_id: int,
    method: str,
    request_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_native_id": source_native_id,
        "external_id": source_native_id,
        "mapping_method": method,
        "method": method,
        "verification_status": IDENTITY_EXACT,
        "status": IDENTITY_EXACT,
        "confidence": 1.0,
        "verified": True,
        "joinable": True,
        "verified_at": utc_now(),
        "evidence_request_id": request_id,
        "provenance": {
            "source_id": source_id,
            "request_id": request_id,
            "verification": evidence,
        },
    }


def _coverage(mapped: int, canonical: int, *, strategy: str) -> dict[str, Any]:
    if canonical <= 0:
        health = "RED"
    elif mapped == canonical:
        health = "GREEN"
    elif mapped > 0:
        health = "AMBER"
    else:
        health = "RED"
    return {
        "strategy": strategy,
        "deterministic_bridge": True,
        "identity_health": health,
        "mapped_status": IDENTITY_EXACT if mapped else "UNMAPPED",
        "coverage_ratio": round(mapped / canonical, 6) if canonical else 0.0,
        "join_allowed": mapped > 0,
    }


def _official_bootstrap(official_snapshot: dict[str, Any]) -> dict[str, Any]:
    return dict((official_snapshot.get("official") or {}).get("bootstrap") or {})


def _verified_vaastav_team_ids(
    official_snapshot: dict[str, Any],
    payload: dict[str, Any],
) -> set[int]:
    official_players = {
        int(row["id"]): row
        for row in _official_bootstrap(official_snapshot).get("elements") or []
        if row.get("id") is not None
    }
    official_team_ids = {
        int(row["id"])
        for row in _official_bootstrap(official_snapshot).get("teams") or []
        if row.get("id") is not None
    }
    verified: set[int] = set()
    for row in _csv_rows(payload, "players_raw"):
        element_id = _int(row.get("id"))
        provider_code = _int(row.get("code"))
        provider_team = _int(row.get("team"))
        official = official_players.get(element_id or -1)
        if official is None or provider_code is None or provider_team is None:
            continue
        if _int(official.get("code")) != provider_code:
            continue
        if _int(official.get("team")) != provider_team:
            continue
        if provider_team not in official_team_ids:
            continue
        verified.add(provider_team)
    return verified


def _verified_vaastav_fixture_ids(
    official_snapshot: dict[str, Any],
    payload: dict[str, Any],
) -> set[int]:
    official_fixtures = {
        int(row["id"]): row
        for row in (official_snapshot.get("official") or {}).get("fixtures") or []
        if row.get("id") is not None
    }
    verified: set[int] = set()
    for row in _csv_rows(payload, "fixtures"):
        fixture_id = _int(row.get("id"))
        team_h = _int(row.get("team_h"))
        team_a = _int(row.get("team_a"))
        official = official_fixtures.get(fixture_id or -1)
        if official is None or team_h is None or team_a is None:
            continue
        if _int(official.get("team_h")) != team_h or _int(official.get("team_a")) != team_a:
            continue

        provider_event = _int(row.get("event"))
        official_event = _int(official.get("event"))
        if provider_event is not None and official_event is not None and provider_event != official_event:
            continue

        provider_kickoff = str(row.get("kickoff_time") or "").strip()
        official_kickoff = str(official.get("kickoff_time") or "").strip()
        if provider_kickoff and official_kickoff and provider_kickoff != official_kickoff:
            continue
        verified.add(fixture_id)
    return verified


def enrich_shared_identity_bridges(
    identity_map: dict[str, Any],
    official_snapshot: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Add only shared-namespace bridges that can be proved from upstream fields.

    This deliberately does not perform name matching. Vaastav mirrors Official FPL
    identifiers, but team/fixture links are accepted only when independent fields
    agree with the current Official snapshot.
    """

    out = deepcopy(identity_map)
    vaastav = results.get("vaastav_fpl") or {}
    if not vaastav:
        return out

    entity_bridges = out.setdefault("entity_bridges", {})
    team_bridge = entity_bridges.get("team") or {}
    fixture_bridge = entity_bridges.get("fixture") or {}

    team_mappings = team_bridge.get("mappings") or {}
    verified_team_ids = _verified_vaastav_team_ids(official_snapshot, vaastav)
    for team_id in sorted(verified_team_ids):
        mapping = team_mappings.get(str(team_id))
        if not isinstance(mapping, dict):
            continue
        links = mapping.setdefault("links", {})
        links["vaastav_fpl"] = _exact_link(
            source_id="vaastav_fpl",
            source_native_id=team_id,
            method="FPL_SHARED_TEAM_ID_WITH_PLAYER_ID_CODE_TEAM_PROOF",
            request_id="players_raw",
            evidence={
                "shared_team_id": True,
                "player_element_id_exact": True,
                "player_code_exact": True,
                "player_team_id_exact": True,
            },
        )
    if isinstance(team_bridge, dict):
        canonical_team_count = int(team_bridge.get("canonical_team_count") or len(team_mappings))
        row = _coverage(
            len(verified_team_ids),
            canonical_team_count,
            strategy="FPL_SHARED_TEAM_ID_WITH_PLAYER_ID_CODE_TEAM_PROOF",
        )
        row.update(
            {
                "mapped_team_count": len(verified_team_ids),
                "canonical_team_count": canonical_team_count,
                "unmapped_team_count": max(0, canonical_team_count - len(verified_team_ids)),
            }
        )
        team_bridge.setdefault("coverage", {})["vaastav_fpl"] = row

    fixture_mappings = fixture_bridge.get("mappings") or {}
    verified_fixture_ids = _verified_vaastav_fixture_ids(official_snapshot, vaastav)
    for fixture_id in sorted(verified_fixture_ids):
        mapping = fixture_mappings.get(str(fixture_id))
        if not isinstance(mapping, dict):
            continue
        links = mapping.setdefault("links", {})
        links["vaastav_fpl"] = _exact_link(
            source_id="vaastav_fpl",
            source_native_id=fixture_id,
            method="FPL_SHARED_FIXTURE_ID_WITH_TEAM_EVENT_KICKOFF_PROOF",
            request_id="fixtures",
            evidence={
                "shared_fixture_id": True,
                "home_team_id_exact": True,
                "away_team_id_exact": True,
                "event_checked_when_present": True,
                "kickoff_checked_when_present": True,
            },
        )
    if isinstance(fixture_bridge, dict):
        canonical_fixture_count = int(
            fixture_bridge.get("canonical_fixture_count") or len(fixture_mappings)
        )
        row = _coverage(
            len(verified_fixture_ids),
            canonical_fixture_count,
            strategy="FPL_SHARED_FIXTURE_ID_WITH_TEAM_EVENT_KICKOFF_PROOF",
        )
        row.update(
            {
                "mapped_fixture_count": len(verified_fixture_ids),
                "canonical_fixture_count": canonical_fixture_count,
                "unmapped_fixture_count": max(
                    0, canonical_fixture_count - len(verified_fixture_ids)
                ),
            }
        )
        fixture_bridge.setdefault("coverage", {})["vaastav_fpl"] = row

    out.setdefault("governance", {}).update(
        {
            "shared_namespace_links_require_cross_field_proof": True,
            "name_only_bridge_allowed": False,
            "verified_bridge_enrichment_module": "verified_bridges",
        }
    )
    out["schema_version"] = max(4, int(out.get("schema_version") or 0))
    return out
