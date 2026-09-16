from __future__ import annotations

import re
from copy import deepcopy
from html.parser import HTMLParser
from typing import Any

from .http_client import utc_now

IDENTITY_EXACT = "EXACT"
METHOD = "FFSCOUT_PUBLIC_PREMIERLEAGUE_MEDIA_CODE_EXACT"
NORMALIZATION_VERSION = "V6_FFSCOUT_PUBLIC_PLAYER_1"
_PL_MEDIA_CODE_RE = re.compile(r"/players/(?:[^/?#]+/)?(\d+)\.png(?:[?#].*)?$", re.IGNORECASE)


class FFScoutPublicError(RuntimeError):
    pass


def _int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _request_body(payload: dict[str, Any], request_id: str) -> str:
    row = ((payload.get("data") or {}).get(request_id) or {})
    body = row.get("body") if isinstance(row, dict) else None
    return body if isinstance(body, str) else ""


class _PremierLeagueAvatarParser(HTMLParser):
    def __init__(self, request_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.request_id = request_id
        self.rows: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        values = {str(key).lower(): value for key, value in attrs}
        src = values.get("src") or values.get("data-src") or values.get("data-lazy-src")
        if not isinstance(src, str) or "resources.premierleague.com" not in src.lower():
            return
        match = _PL_MEDIA_CODE_RE.search(src)
        if not match:
            return
        code = _int(match.group(1))
        if code is None or code <= 0:
            return
        alt = str(values.get("alt") or "").strip()
        display_name = alt
        if display_name.lower().startswith("avatar of "):
            display_name = display_name[10:].strip()
        self.rows.append(
            {
                "source_native_id": code,
                "premierleague_media_code": code,
                "player_name": display_name or None,
                "request_id": self.request_id,
                "image_url": src,
            }
        )


def _observed_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    by_code: dict[int, list[dict[str, Any]]] = {}
    seen_occurrences: set[tuple[int, str, str]] = set()
    for request_id in ("team_news", "home"):
        body = _request_body(payload, request_id)
        if not body.strip():
            continue
        parser = _PremierLeagueAvatarParser(request_id)
        parser.feed(body)
        for row in parser.rows:
            code = _int(row.get("premierleague_media_code"))
            if code is None:
                continue
            image_url = str(row.get("image_url") or "").strip()
            occurrence = (code, request_id, image_url)
            if occurrence in seen_occurrences:
                continue
            seen_occurrences.add(occurrence)
            by_code.setdefault(code, []).append(dict(row))

    rows: list[dict[str, Any]] = []
    for code, evidence_rows in sorted(by_code.items()):
        request_ids = sorted({str(row.get("request_id")) for row in evidence_rows if row.get("request_id")})
        image_urls = sorted({str(row.get("image_url")) for row in evidence_rows if row.get("image_url")})
        names = sorted({str(row.get("player_name")).strip() for row in evidence_rows if str(row.get("player_name") or "").strip()})
        observations = sorted(
            [
                {
                    "request_id": str(row.get("request_id") or "").strip() or None,
                    "image_url": str(row.get("image_url") or "").strip() or None,
                }
                for row in evidence_rows
            ],
            key=lambda item: (str(item.get("request_id") or ""), str(item.get("image_url") or "")),
        )
        observation_types = sorted(
            {
                "PREDICTED_LINEUP_PUBLIC_REFERENCE" if request_id == "team_news" else "PUBLIC_PLAYER_REFERENCE"
                for request_id in request_ids
            }
        )
        rows.append(
            {
                "source_native_id": code,
                "premierleague_media_code": code,
                "player_name": names[0] if names else None,
                "request_id": request_ids[0] if len(request_ids) == 1 else None,
                "request_ids": request_ids,
                "image_url": image_urls[0] if len(image_urls) == 1 else None,
                "image_urls": image_urls,
                "observation_type": (
                    "PREDICTED_LINEUP_PUBLIC_REFERENCE"
                    if "PREDICTED_LINEUP_PUBLIC_REFERENCE" in observation_types
                    else "PUBLIC_PLAYER_REFERENCE"
                ),
                "observation_types": observation_types,
                "observation_count": len(observations),
                "observations": observations,
            }
        )
    return rows


def _official_by_code(identity_map: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], set[int]]:
    by_code: dict[int, dict[str, Any]] = {}
    duplicate_codes: set[int] = set()
    for mapping in (identity_map.get("mappings") or {}).values():
        if not isinstance(mapping, dict):
            continue
        code = _int(mapping.get("official_code"))
        if code is None or code <= 0:
            continue
        if code in by_code:
            duplicate_codes.add(code)
            continue
        by_code[code] = mapping
    for code in duplicate_codes:
        by_code.pop(code, None)
    return by_code, duplicate_codes


def _exact_link(code: int, evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    request_ids = sorted({str(row.get("request_id")) for row in evidence_rows if row.get("request_id")})
    image_urls = sorted({str(row.get("image_url")) for row in evidence_rows if row.get("image_url")})
    return {
        "source_id": "ffscout",
        "source_native_id": code,
        "external_id": code,
        "mapping_method": METHOD,
        "method": METHOD,
        "verification_status": IDENTITY_EXACT,
        "status": IDENTITY_EXACT,
        "confidence": 1.0,
        "verified": True,
        "joinable": True,
        "verified_at": utc_now(),
        "evidence_request_id": request_ids[0] if len(request_ids) == 1 else None,
        "provenance": {
            "source_id": "ffscout",
            "canonical_anchor": "official_fpl.bootstrap.elements.code",
            "embedded_identifier_namespace": "resources.premierleague.com player media code",
            "official_fpl_code": code,
            "request_ids": request_ids,
            "image_urls": image_urls,
            "name_matching_used": False,
            "fuzzy_matching_used": False,
            "public_content_only": True,
        },
    }


def enrich_ffscout_public_identity(
    identity_map: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Join public FFScout player references using the embedded Premier League media code.

    FFScout public pages render player avatars from resources.premierleague.com and the
    numeric media key in those URLs is the same identifier exposed by Official FPL as
    bootstrap.elements.code. Player names are retained only as display evidence and are
    never used to resolve identity.
    """

    payload = results.get("ffscout")
    if not isinstance(payload, dict):
        return identity_map

    out = deepcopy(identity_map)
    by_code, duplicate_codes = _official_by_code(out)
    evidence_by_code: dict[int, list[dict[str, Any]]] = {}
    for row in _observed_rows(payload):
        code = _int(row.get("premierleague_media_code"))
        if code is not None:
            evidence_by_code.setdefault(code, []).append(row)

    mapped = 0
    orphaned = 0
    for code, evidence in sorted(evidence_by_code.items()):
        mapping = by_code.get(code)
        if mapping is None:
            orphaned += 1
            continue
        links = mapping.setdefault("links", {})
        existing = links.get("ffscout") or {}
        if existing and str(existing.get("source_native_id")) != str(code):
            continue
        links["ffscout"] = _exact_link(code, evidence)
        unresolved = mapping.get("unresolved")
        if isinstance(unresolved, dict):
            unresolved.pop("ffscout", None)
        mapped += 1

    canonical_count = int(out.get("canonical_player_count") or len(out.get("mappings") or {}))
    health = "GREEN" if canonical_count > 0 and mapped == canonical_count else ("AMBER" if mapped else "RED")
    coverage = {
        "strategy": METHOD,
        "deterministic_bridge": True,
        "identity_health": health,
        "mapped_status": IDENTITY_EXACT if mapped else "UNMAPPED",
        "mapped_player_count": mapped,
        "canonical_player_count": canonical_count,
        "coverage_ratio": round(mapped / canonical_count, 6) if canonical_count else 0.0,
        "unmapped_player_count": max(0, canonical_count - mapped),
        "observed_public_media_code_count": len(evidence_by_code),
        "orphaned_observed_code_count": orphaned,
        "duplicate_canonical_code_count": len(duplicate_codes),
        "join_allowed": mapped > 0,
        "name_matching_used": False,
        "fuzzy_matching_used": False,
        "public_content_only": True,
        "fail_closed_on_duplicate_or_unknown_code": True,
    }
    out.setdefault("coverage", {})["ffscout"] = coverage
    player_bridge = ((out.setdefault("entity_bridges", {})).setdefault("player", {}))
    player_bridge.setdefault("coverage", {})["ffscout"] = deepcopy(coverage)
    out.setdefault("governance", {}).update(
        {
            "ffscout_public_player_identity_method": METHOD,
            "ffscout_player_name_matching": False,
            "ffscout_public_only_without_member_auth": True,
        }
    )
    return out


def _identity_by_code(identity_map: dict[str, Any]) -> dict[int, tuple[int, str]]:
    resolved: dict[int, tuple[int, str]] = {}
    conflicts: set[int] = set()
    for mapping in (identity_map.get("mappings") or {}).values():
        if not isinstance(mapping, dict):
            continue
        link = ((mapping.get("links") or {}).get("ffscout") or {})
        if not isinstance(link, dict) or link.get("joinable") is not True:
            continue
        code = _int(link.get("source_native_id"))
        element_id = _int(mapping.get("official_fpl_element_id"))
        status = str(link.get("status") or "UNMAPPED")
        if code is None or element_id is None:
            continue
        if code in resolved and resolved[code][0] != element_id:
            conflicts.add(code)
            continue
        resolved[code] = (element_id, status)
    for code in conflicts:
        resolved.pop(code, None)
    return resolved


def _normalized_observations(row: dict[str, Any]) -> set[tuple[str, str]]:
    observations: set[tuple[str, str]] = set()
    for item in row.get("observations") or []:
        if not isinstance(item, dict):
            continue
        request_id = str(item.get("request_id") or "").strip()
        image_url = str(item.get("image_url") or "").strip()
        if request_id or image_url:
            observations.add((request_id, image_url))
    if observations:
        return observations
    request_id = str(row.get("request_id") or "").strip()
    image_url = str(row.get("image_url") or "").strip()
    if request_id or image_url:
        observations.add((request_id, image_url))
    return observations


def _consolidate_normalized_player_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_native: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("source_native_id") is None:
            continue
        native = str(row.get("source_native_id")).strip()
        if not native:
            continue
        by_native.setdefault(native, []).append(dict(row))

    consolidated: list[dict[str, Any]] = []
    for native, native_rows in sorted(by_native.items(), key=lambda item: (int(item[0]) if item[0].isdigit() else 10**18, item[0])):
        official_ids = {
            int(row["official_element_id"])
            for row in native_rows
            if row.get("official_element_id") is not None and str(row.get("official_element_id")).strip()
        }
        if len(official_ids) > 1:
            raise FFScoutPublicError(
                f"ffscout native id {native} maps to multiple Official FPL elements: {sorted(official_ids)}"
            )

        observations: set[tuple[str, str]] = set()
        request_ids: set[str] = set()
        image_urls: set[str] = set()
        names: set[str] = set()
        observation_types: set[str] = set()
        for row in native_rows:
            observations.update(_normalized_observations(row))
            request_ids.update(str(value).strip() for value in (row.get("request_ids") or []) if str(value).strip())
            image_urls.update(str(value).strip() for value in (row.get("image_urls") or []) if str(value).strip())
            if str(row.get("request_id") or "").strip():
                request_ids.add(str(row.get("request_id")).strip())
            if str(row.get("image_url") or "").strip():
                image_urls.add(str(row.get("image_url")).strip())
            if str(row.get("player_name") or "").strip():
                names.add(str(row.get("player_name")).strip())
            observation_types.update(
                str(value).strip() for value in (row.get("observation_types") or []) if str(value).strip()
            )
            if str(row.get("observation_type") or "").strip():
                observation_types.add(str(row.get("observation_type")).strip())

        for request_id, image_url in observations:
            if request_id:
                request_ids.add(request_id)
            if image_url:
                image_urls.add(image_url)
        if "team_news" in request_ids:
            observation_types.add("PREDICTED_LINEUP_PUBLIC_REFERENCE")
        if any(request_id != "team_news" for request_id in request_ids):
            observation_types.add("PUBLIC_PLAYER_REFERENCE")

        mapped_rows = [row for row in native_rows if row.get("official_element_id") is not None]
        status_rank = {"EXACT": 3, "VERIFIED_MANUAL": 2, "UNMAPPED": 0}
        selected_status = max(
            (str(row.get("identity_status") or "UNMAPPED") for row in mapped_rows),
            key=lambda value: status_rank.get(value, 1),
            default="UNMAPPED",
        )
        identity_method = next(
            (str(row.get("identity_method")) for row in reversed(mapped_rows) if row.get("identity_method")),
            None,
        )
        sorted_requests = sorted(request_ids)
        sorted_images = sorted(image_urls)
        sorted_types = sorted(observation_types)
        sorted_observations = [
            {"request_id": request_id or None, "image_url": image_url or None}
            for request_id, image_url in sorted(observations)
        ]
        code = _int(native)
        consolidated.append(
            {
                "source_native_id": code if code is not None else native,
                "premierleague_media_code": code if code is not None else native,
                "player_name": sorted(names)[0] if names else None,
                "request_id": sorted_requests[0] if len(sorted_requests) == 1 else None,
                "request_ids": sorted_requests,
                "image_url": sorted_images[0] if len(sorted_images) == 1 else None,
                "image_urls": sorted_images,
                "observation_type": (
                    "PREDICTED_LINEUP_PUBLIC_REFERENCE"
                    if "PREDICTED_LINEUP_PUBLIC_REFERENCE" in observation_types
                    else (sorted_types[0] if sorted_types else "PUBLIC_PLAYER_REFERENCE")
                ),
                "observation_types": sorted_types,
                "observation_count": len(sorted_observations),
                "observations": sorted_observations,
                "official_element_id": next(iter(official_ids)) if official_ids else None,
                "identity_status": selected_status if official_ids else "UNMAPPED",
                "join_ready": bool(official_ids and selected_status in {"EXACT", "VERIFIED_MANUAL"}),
                "identity_method": identity_method if official_ids else None,
            }
        )
    return consolidated


def build_ffscout_public_dataset(
    payload: dict[str, Any],
    identity_map: dict[str, Any],
) -> dict[str, Any]:
    reverse = _identity_by_code(identity_map)
    players: list[dict[str, Any]] = []
    for row in _observed_rows(payload):
        code = _int(row.get("premierleague_media_code"))
        resolved = reverse.get(code or -1)
        player = dict(row)
        player["observation_type"] = str(
            row.get("observation_type")
            or (
                "PREDICTED_LINEUP_PUBLIC_REFERENCE"
                if row.get("request_id") == "team_news"
                else "PUBLIC_PLAYER_REFERENCE"
            )
        )
        player["official_element_id"] = resolved[0] if resolved else None
        player["identity_status"] = resolved[1] if resolved else "UNMAPPED"
        player["join_ready"] = bool(resolved and resolved[1] in {"EXACT", "VERIFIED_MANUAL"})
        player["identity_method"] = METHOD if resolved else None
        players.append(player)

    snapshot_ids = sorted(
        {
            str(row.get("sha256"))
            for row in (payload.get("data") or {}).values()
            if isinstance(row, dict) and row.get("sha256")
        }
    )
    return {
        "schema_version": 1,
        "normalization_version": NORMALIZATION_VERSION,
        "source_id": "ffscout",
        "generated_at": utc_now(),
        "effective_at": payload.get("checked_at"),
        "canonical": True,
        "semantic_class": "NORMALIZED_FACT",
        "authority": "FFSCOUT_PUBLIC",
        "source_snapshot_ids": snapshot_ids,
        "source_health": payload.get("health"),
        "source_effective_state": payload.get("effective_state"),
        "current_run_action": payload.get("current_run_action"),
        "normalization_status": "NORMALIZED" if players else "EMPTY_OR_SCHEMA_UNAVAILABLE",
        "record_count": len(_consolidate_normalized_player_rows(players)),
        "record_groups": {"players": _consolidate_normalized_player_rows(players)},
        "governance": {
            "data_only": True,
            "public_content_only": True,
            "member_paywalled_stats_not_acquired": True,
            "source_native_records_preserved": True,
            "cross_source_synthesis": False,
            "silent_fuzzy_identity_join": False,
            "identity_join_requires_embedded_premierleague_media_code": True,
            "player_identity_rows_are_unique_by_source_native_id": True,
            "multiple_observations_for_same_native_id_are_consolidated": True,
            "observation_evidence_is_retained": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "may_override_official_fpl": False,
        },
    }


def augment_ffscout_public_dataset(
    results: dict[str, dict[str, Any]],
    identity_map: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    payload = results.get("ffscout")
    if not isinstance(payload, dict):
        return datasets
    out = dict(datasets)
    overlay = build_ffscout_public_dataset(payload, identity_map)
    existing = out.get("ffscout")
    if not isinstance(existing, dict):
        out["ffscout"] = overlay
        return out

    merged = deepcopy(existing)
    groups = merged.setdefault("record_groups", {})
    current = groups.get("players") if isinstance(groups.get("players"), list) else []
    observed = ((overlay.get("record_groups") or {}).get("players") or [])
    groups["players"] = _consolidate_normalized_player_rows([*current, *observed])
    merged["record_count"] = sum(len(rows) for rows in groups.values() if isinstance(rows, list))
    if groups["players"]:
        merged["normalization_status"] = "NORMALIZED"
    merged.setdefault("governance", {}).update(overlay["governance"])
    merged["governance"]["ffscout_public_player_normalization_version"] = NORMALIZATION_VERSION
    merged["governance"]["player_identity_rows_are_unique_by_source_native_id"] = True
    merged["governance"]["multiple_observations_for_same_native_id_are_consolidated"] = True
    merged["governance"]["observation_evidence_is_retained"] = True
    out["ffscout"] = merged
    return out
