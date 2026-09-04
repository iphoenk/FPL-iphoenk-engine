from __future__ import annotations

import csv
import io
from typing import Any

from .http_client import utc_now


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
        links[element_id] = {
            "external_id": element_id,
            "method": "FPL_ELEMENT_ID_AND_CODE_EXACT",
            "confidence": 1.0,
            "verified": True,
            "evidence_request_id": "players_raw",
            "provider_code": provider_code,
        }
    return links


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

    # The internal Official price predictor is derived from the same Official
    # FPL bootstrap and therefore shares the canonical element namespace.
    if "official_price_predictor" in source_ids:
        derived_rows = list((((results.get("official_price_predictor") or {}).get("data") or {}).get("players")) or [])
        row_ids = {
            int(row["id"])
            for row in derived_rows
            if row.get("id") is not None
        }
        links = {
            element_id: {
                "external_id": element_id,
                "method": "OFFICIAL_DERIVED_SHARED_ELEMENT_ID",
                "confidence": 1.0,
                "verified": True,
                "evidence_request_id": None,
            }
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
        for source_id, by_player in provider_links.items():
            link = by_player.get(element_id)
            if link:
                links[source_id] = link
        mappings[str(element_id)] = {
            "canonical_player_id": f"fpl:{element_id}",
            "official_fpl_element_id": element_id,
            "official_code": official.get("code"),
            "web_name": official.get("web_name"),
            "links": links,
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
        coverage[source_id] = {
            "strategy": strategy,
            "deterministic_bridge": deterministic_bridge,
            "mapped_player_count": mapped,
            "canonical_player_count": len(canonical_ids),
            "coverage_ratio": round(mapped / len(canonical_ids), 6) if canonical_ids else 0.0,
            "unmapped_player_count": max(0, len(canonical_ids) - mapped),
        }

    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "canonical_authority": "official_fpl",
        "canonical_key": "official_fpl_element_id",
        "governance": {
            "fuzzy_name_matching_allowed": False,
            "unverified_ids_are_never_fabricated": True,
            "partial_mapping_is_explicit": True,
            "provider_links_require_deterministic_evidence": True,
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
    external_ids = {
        source_id: (links.get(source_id) or {}).get("external_id")
        for source_id in source_ids
        if source_id != "official_fpl"
    }
    identity_links = {
        source_id: dict(link)
        for source_id, link in links.items()
    }
    return external_ids, identity_links
