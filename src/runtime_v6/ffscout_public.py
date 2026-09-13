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
    by_key: dict[tuple[int, str], dict[str, Any]] = {}
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
            by_key[(code, request_id)] = row
    return [by_key[key] for key in sorted(by_key)]


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
        player["observation_type"] = (
            "PREDICTED_LINEUP_PUBLIC_REFERENCE"
            if row.get("request_id") == "team_news"
            else "PUBLIC_PLAYER_REFERENCE"
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
        "record_count": len(players),
        "record_groups": {"players": players},
        "governance": {
            "data_only": True,
            "public_content_only": True,
            "member_paywalled_stats_not_acquired": True,
            "source_native_records_preserved": True,
            "cross_source_synthesis": False,
            "silent_fuzzy_identity_join": False,
            "identity_join_requires_embedded_premierleague_media_code": True,
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
    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*current, *observed]:
        if not isinstance(row, dict) or row.get("source_native_id") is None:
            continue
        keyed[(str(row.get("source_native_id")), str(row.get("request_id") or ""))] = dict(row)
    groups["players"] = list(keyed.values())
    merged["record_count"] = sum(len(rows) for rows in groups.values() if isinstance(rows, list))
    if groups["players"]:
        merged["normalization_status"] = "NORMALIZED"
    merged.setdefault("governance", {}).update(overlay["governance"])
    merged["governance"]["ffscout_public_player_normalization_version"] = NORMALIZATION_VERSION
    out["ffscout"] = merged
    return out
