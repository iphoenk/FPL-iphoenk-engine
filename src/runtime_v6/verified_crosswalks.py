from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .http_client import utc_now

CONFIG = Path(__file__).resolve().parents[2] / "config" / "v6" / "verified_crosswalks.json"
STATUS = "VERIFIED_MANUAL"
OPTA_STATUS = "EXACT"
OPTA_METHOD = "OFFICIAL_FPL_CODE_SHARED_OPTA_NUMERIC_NAMESPACE"
OPTA_CONTRACT_EVIDENCE = [
    "official_fpl:bootstrap.elements.code",
    "https://github.com/withqwerty/reep/blob/0ec59faa5d81615b7a8200ae6121023a3bc14ce3/README.md",
]


class VerifiedCrosswalkError(RuntimeError):
    pass


def _int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_verified_crosswalks(path: Path = CONFIG) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerifiedCrosswalkError("verified crosswalk config unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise VerifiedCrosswalkError("verified crosswalk schema mismatch")
    if payload.get("canonical_authority") != "official_fpl":
        raise VerifiedCrosswalkError("verified crosswalk canonical authority must be official_fpl")
    if payload.get("fuzzy_matching_allowed") is not False:
        raise VerifiedCrosswalkError("verified crosswalk must forbid fuzzy matching")

    for source_id, source in (payload.get("sources") or {}).items():
        if not isinstance(source, dict):
            raise VerifiedCrosswalkError(f"invalid crosswalk source: {source_id}")
        native_seen: set[int] = set()
        official_seen: set[int] = set()
        for row in source.get("teams") or []:
            native = _int(row.get("source_native_id")) if isinstance(row, dict) else None
            official = _int(row.get("official_fpl_team_id")) if isinstance(row, dict) else None
            if native is None or official is None or native <= 0 or official <= 0:
                raise VerifiedCrosswalkError(f"invalid team crosswalk row: {source_id}")
            if native in native_seen:
                raise VerifiedCrosswalkError(f"duplicate native team id: {source_id}:{native}")
            if official in official_seen:
                raise VerifiedCrosswalkError(f"duplicate Official FPL team id: {source_id}:{official}")
            native_seen.add(native)
            official_seen.add(official)
    return payload


def _fotmob_json(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = (((results.get("fotmob") or {}).get("data") or {}).get("league") or {}).get("json")
    return dict(row) if isinstance(row, dict) else {}


def _observed_fotmob_team_ids(results: dict[str, dict[str, Any]]) -> set[int]:
    raw = _fotmob_json(results)
    observed: set[int] = set()

    matches_container = raw.get("matches") if isinstance(raw.get("matches"), dict) else {}
    matches = matches_container.get("allMatches") or matches_container.get("matches") or []
    if isinstance(matches, list):
        for match in matches:
            if not isinstance(match, dict):
                continue
            for side in ("home", "away"):
                team = match.get(side) if isinstance(match.get(side), dict) else {}
                team_id = _int(team.get("id"))
                if team_id is not None:
                    observed.add(team_id)

    for block in raw.get("table") or []:
        if not isinstance(block, dict):
            continue
        data = block.get("data") if isinstance(block.get("data"), dict) else {}
        table = data.get("table") if isinstance(data.get("table"), dict) else {}
        rows = table.get("all") or []
        if not isinstance(rows, list):
            continue
        for team in rows:
            if not isinstance(team, dict):
                continue
            team_id = _int(team.get("id"))
            if team_id is not None:
                observed.add(team_id)
    return observed


def _link(source_id: str, native_id: int, config_source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_native_id": native_id,
        "external_id": native_id,
        "mapping_method": str(config_source.get("verification_method") or "VERIFIED_MANUAL_CROSSWALK"),
        "method": str(config_source.get("verification_method") or "VERIFIED_MANUAL_CROSSWALK"),
        "verification_status": STATUS,
        "status": STATUS,
        "confidence": 1.0,
        "verified": True,
        "joinable": True,
        "verified_at": config_source.get("verified_at"),
        "provenance": {
            "source_id": source_id,
            "crosswalk_config": "config/v6/verified_crosswalks.json",
            "evidence": list(config_source.get("evidence") or []),
            "source_native_id_observed_current_snapshot": True,
        },
    }


def _opta_link(native_id: int) -> dict[str, Any]:
    return {
        "source_id": "opta_the_analyst",
        "source_native_id": native_id,
        "external_id": native_id,
        "mapping_method": OPTA_METHOD,
        "method": OPTA_METHOD,
        "verification_status": OPTA_STATUS,
        "status": OPTA_STATUS,
        "confidence": 1.0,
        "verified": True,
        "joinable": True,
        "verified_at": utc_now(),
        "evidence_request_id": "official_fpl.bootstrap.elements.code",
        "provenance": {
            "canonical_source": "official_fpl",
            "canonical_field": "bootstrap.elements.code",
            "provider_namespace": "opta_numeric",
            "evidence": list(OPTA_CONTRACT_EVIDENCE),
            "name_matching_used": False,
        },
    }


def _enrich_opta_numeric_players(
    identity_map: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if "opta_the_analyst" not in results:
        return identity_map

    mappings = identity_map.get("mappings") or {}
    canonical_count = int(identity_map.get("canonical_player_count") or len(mappings))
    mapped = 0
    seen_codes: set[int] = set()
    for mapping in mappings.values():
        if not isinstance(mapping, dict):
            continue
        code = _int(mapping.get("official_code"))
        if code is None or code <= 0 or code in seen_codes:
            continue
        seen_codes.add(code)
        links = mapping.setdefault("links", {})
        links["opta_the_analyst"] = _opta_link(code)
        unresolved = mapping.get("unresolved")
        if isinstance(unresolved, dict):
            unresolved.pop("opta_the_analyst", None)
        mapped += 1

    health = "GREEN" if canonical_count > 0 and mapped == canonical_count else ("AMBER" if mapped else "RED")
    identity_map.setdefault("coverage", {})["opta_the_analyst"] = {
        "strategy": OPTA_METHOD,
        "deterministic_bridge": True,
        "identity_health": health,
        "mapped_status": OPTA_STATUS if mapped else "UNMAPPED",
        "mapped_player_count": mapped,
        "canonical_player_count": canonical_count,
        "coverage_ratio": round(mapped / canonical_count, 6) if canonical_count else 0.0,
        "unmapped_player_count": max(0, canonical_count - mapped),
        "join_allowed": mapped > 0,
        "shared_namespace_field": "official_fpl.bootstrap.elements.code",
        "name_matching_used": False,
    }
    return identity_map


def enrich_verified_external_crosswalks(
    identity_map: dict[str, Any],
    results: dict[str, dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_verified_crosswalks()
    out = _enrich_opta_numeric_players(deepcopy(identity_map), results)
    team_bridge = ((out.get("entity_bridges") or {}).get("team") or {})
    mappings = team_bridge.get("mappings") or {}
    coverage = team_bridge.setdefault("coverage", {})
    canonical_team_count = int(team_bridge.get("canonical_team_count") or len(mappings))

    for source_id, config_source in (config.get("sources") or {}).items():
        if source_id != "fotmob":
            continue
        observed = _observed_fotmob_team_ids(results)
        configured_rows = list(config_source.get("teams") or [])
        mapped = 0
        for row in configured_rows:
            native_id = int(row["source_native_id"])
            official_id = int(row["official_fpl_team_id"])
            if native_id not in observed:
                continue
            mapping = mappings.get(str(official_id))
            if not isinstance(mapping, dict):
                continue
            links = mapping.setdefault("links", {})
            links[source_id] = _link(source_id, native_id, config_source)
            mapped += 1

        health = "GREEN" if canonical_team_count > 0 and mapped == canonical_team_count else ("AMBER" if mapped else "RED")
        coverage[source_id] = {
            "strategy": "VERIFIED_MANUAL_SOURCE_NATIVE_TEAM_CROSSWALK",
            "deterministic_bridge": True,
            "identity_health": health,
            "mapped_status": STATUS if mapped else "UNMAPPED",
            "mapped_team_count": mapped,
            "canonical_team_count": canonical_team_count,
            "coverage_ratio": round(mapped / canonical_team_count, 6) if canonical_team_count else 0.0,
            "unmapped_team_count": max(0, canonical_team_count - mapped),
            "configured_mapping_count": len(configured_rows),
            "observed_native_team_count": len(observed),
            "join_allowed": mapped > 0,
        }

    out.setdefault("governance", {}).update(
        {
            "verified_manual_crosswalk_requires_current_native_observation": True,
            "verified_manual_crosswalk_name_matching": False,
            "verified_external_crosswalk_module": "verified_crosswalks",
            "opta_numeric_bridge_is_name_free": True,
            "opta_numeric_bridge_contract_evidence": list(OPTA_CONTRACT_EVIDENCE),
        }
    )
    return out


def build_verified_crosswalk_report(
    identity_map: dict[str, Any],
    results: dict[str, dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_verified_crosswalks()
    team_coverage = (((identity_map.get("entity_bridges") or {}).get("team") or {}).get("coverage") or {})
    player_coverage = identity_map.get("coverage") or {}
    source_report: dict[str, Any] = {}
    for source_id, source in (config.get("sources") or {}).items():
        source_report[source_id] = {
            "verification_status": source.get("verification_status"),
            "verification_method": source.get("verification_method"),
            "verified_at": source.get("verified_at"),
            "evidence": list(source.get("evidence") or []),
            "configured_team_mapping_count": len(source.get("teams") or []),
            "current_identity_coverage": team_coverage.get(source_id),
            "current_source_health": (results.get(source_id) or {}).get("health"),
            "current_source_effective_state": (results.get(source_id) or {}).get("effective_state"),
        }

    if "opta_the_analyst" in results:
        source_report["opta_the_analyst"] = {
            "verification_status": OPTA_STATUS,
            "verification_method": OPTA_METHOD,
            "verified_at": utc_now(),
            "evidence": list(OPTA_CONTRACT_EVIDENCE),
            "configured_team_mapping_count": 0,
            "current_identity_coverage": player_coverage.get("opta_the_analyst"),
            "current_source_health": (results.get("opta_the_analyst") or {}).get("health"),
            "current_source_effective_state": (results.get("opta_the_analyst") or {}).get("effective_state"),
        }

    team_records = sum(len(source.get("teams") or []) for source in (config.get("sources") or {}).values())
    opta_records = int((player_coverage.get("opta_the_analyst") or {}).get("mapped_player_count") or 0)
    return {
        "schema_version": 1,
        "canonical": True,
        "semantic_class": "IDENTITY_CROSSWALK",
        "authority": "V6_DETERMINISTIC_IDENTITY",
        "generated_at": utc_now(),
        "effective_at": utc_now(),
        "normalization_version": "V6_VERIFIED_CROSSWALK_2",
        "canonical_authority": "official_fpl",
        "fuzzy_matching_allowed": False,
        "record_count": team_records + opta_records,
        "primary_keys": ["source_id", "source_native_id"],
        "sources": source_report,
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "silent_name_matching_allowed": False,
            "unverified_records_remain_unmapped": True,
            "shared_namespace_exact_bridge_allowed": True,
        },
    }
