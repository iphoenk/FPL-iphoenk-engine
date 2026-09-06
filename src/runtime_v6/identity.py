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


def _official_elements(official_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return list((((official_snapshot.get("official") or {}).get("bootstrap") or {}).get("elements")) or [])


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
    external_id: Any,
    method: str,
    evidence_request_id: str | None,
    provider_code: Any = None,
) -> dict[str, Any]:
    link = {
        "external_id": external_id,
        "method": method,
        "status": IDENTITY_EXACT,
        "confidence": 1.0,
        "verified": True,
        "joinable": True,
        "verified_at": utc_now(),
        "evidence_request_id": evidence_request_id,
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
            external_id=element_id,
            method="FPL_ELEMENT_ID_AND_CODE_EXACT",
            evidence_request_id="players_raw",
            provider_code=provider_code,
        )
    return links


def _coverage_health(mapped: int, canonical: int, deterministic_bridge: bool) -> str:
    if not deterministic_bridge:
        return "RED"
    if canonical <= 0:
        return "RED"
    if mapped == canonical:
        return "GREEN"
    if mapped > 0:
        return "AMBER"
    return "RED"


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
        derived_rows = list((((results.get("official_price_predictor") or {}).get("data") or {}).get("players")) or [])
        row_ids = {
            int(row["id"])
            for row in derived_rows
            if row.get("id") is not None
        }
        links = {
            element_id: _exact_link(
                external_id=element_id,
                method="OFFICIAL_DERIVED_SHARED_ELEMENT_ID",
                evidence_request_id=None,
            )
            for element_id in canonical_ids
            if element_id in row_ids
        }
        provider_links["official_price_predictor"] = links

    if "vaastav_fpl" in source_ids:
        provider_links["vaastav_fpl"] = _vaastav_links(
            official_by_id,
            results.get("vaastav_fpl") or {},
        )

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
            "official_code": official.get("code"),
            "web_name": official.get("web_name"),
            "canonical_status": IDENTITY_EXACT,
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

    return {
        "schema_version": 2,
        "generated_at": utc_now(),
        "canonical_authority": "official_fpl",
        "canonical_key": "official_fpl_element_id",
        "identity_health": aggregate_health,
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
    }


def external_ids_for_player(
    identity_map: dict[str, Any],
    element_id: int,
    source_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    mapping = dict((identity_map.get("mappings") or {}).get(str(element_id)) or {})
    links = dict(mapping.get("links") or {})
    # Preserve explicit nulls for every configured provider so downstream schemas
    # remain stable. Null does not mean joinable; only verified statuses below do.
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
