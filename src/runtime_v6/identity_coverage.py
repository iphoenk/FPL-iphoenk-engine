from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .http_client import utc_now

EVIDENCE_CONFIG = Path(__file__).resolve().parents[2] / "config" / "v6" / "identity_evidence_sources.json"
_JOINABLE = {"EXACT", "VERIFIED_MANUAL"}
_PROVIDER_COMPLETENESS = {
    "opta_the_analyst": "CANONICAL_SHARED_NAMESPACE_COMPLETE",
    "understat": "CURRENT_SEASON_STATS_OBSERVATION",
    "fotmob": "PARTIAL_LEAGUE_STATS_OBSERVATION",
    "statmuse": "PARTIAL_QUERY_RESULT",
}


class IdentityCoverageError(RuntimeError):
    pass


def load_identity_evidence_config(path: Path = EVIDENCE_CONFIG) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityCoverageError("identity evidence config unreadable") from exc
    if payload.get("schema_version") != 1:
        raise IdentityCoverageError("identity evidence config schema mismatch")
    if payload.get("canonical_authority") != "official_fpl":
        raise IdentityCoverageError("identity evidence canonical authority must be official_fpl")
    if payload.get("fuzzy_name_matching_allowed") is not False:
        raise IdentityCoverageError("identity evidence must forbid fuzzy name matching")
    return payload


def _player_rows(dataset: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(dataset, dict):
        return []
    rows = ((dataset.get("record_groups") or {}).get("players") or [])
    return [dict(row) for row in rows if isinstance(row, dict)]


def _observed_truth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_native: dict[str, list[dict[str, Any]]] = {}
    missing_native = 0
    for row in rows:
        native = row.get("source_native_id")
        if native is None or str(native).strip() == "":
            missing_native += 1
            continue
        by_native.setdefault(str(native), []).append(row)

    joined_native: set[str] = set()
    unmapped_native: set[str] = set()
    conflicts: set[str] = set()
    duplicate_native_records = 0

    for native, native_rows in by_native.items():
        duplicate_native_records += max(0, len(native_rows) - 1)
        joined_targets: set[int] = set()
        has_joinable = False
        for row in native_rows:
            status = str(row.get("identity_status") or "")
            official = row.get("official_element_id")
            try:
                official_id = int(official) if official is not None else None
            except (TypeError, ValueError):
                official_id = None
            if status in _JOINABLE and official_id is not None and official_id > 0:
                has_joinable = True
                joined_targets.add(official_id)
        if len(joined_targets) > 1:
            conflicts.add(native)
        elif has_joinable:
            joined_native.add(native)
        else:
            unmapped_native.add(native)

    observed = len(by_native)
    joined = len(joined_native - conflicts)
    unmapped = len(unmapped_native)
    conflict_count = len(conflicts)
    ratio = round(joined / observed, 6) if observed else 0.0
    if conflict_count or missing_native:
        health = "RED"
    elif observed and joined == observed:
        health = "GREEN"
    elif observed and joined:
        health = "AMBER"
    else:
        health = "RED"

    return {
        "observed_provider_player_count": observed,
        "observed_joined_player_count": joined,
        "observed_unmapped_player_count": unmapped,
        "observed_join_coverage_ratio": ratio,
        "observed_join_health": health,
        "duplicate_observed_native_record_count": duplicate_native_records,
        "missing_native_id_record_count": missing_native,
        "identity_conflict_count": conflict_count,
        "observed_unmapped_native_ids": sorted(unmapped_native),
        "conflicting_native_ids": sorted(conflicts),
    }


def _canonical_truth(identity_map: dict[str, Any], source_id: str, canonical_count: int) -> dict[str, Any]:
    coverage = ((identity_map.get("coverage") or {}).get(source_id) or {})
    mapped = int(coverage.get("mapped_player_count") or 0)
    ratio = round(mapped / canonical_count, 6) if canonical_count else 0.0
    health = "GREEN" if canonical_count and mapped == canonical_count else ("AMBER" if mapped else "RED")
    return {
        "canonical_player_count": canonical_count,
        "canonical_mapped_player_count": mapped,
        "canonical_coverage_ratio": ratio,
        "canonical_coverage_health": health,
        "mapping_strategy": coverage.get("strategy"),
        "mapped_status": coverage.get("mapped_status"),
        "join_allowed_for_verified_rows": bool(coverage.get("join_allowed")),
        "configured_mapping_count": coverage.get("configured_mapping_count"),
        "duplicate_canonical_code_count": int(coverage.get("duplicate_canonical_code_count") or 0),
        "configured_link_conflict_count": int(coverage.get("conflicting_existing_link_count") or 0),
    }


def build_player_identity_coverage_truth(
    identity_map: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
    evidence_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_config = evidence_config or load_identity_evidence_config()
    canonical_count = int(identity_map.get("canonical_player_count") or len(identity_map.get("mappings") or {}))
    if canonical_count <= 0:
        raise IdentityCoverageError("canonical player count unavailable")

    sources: dict[str, Any] = {}
    for source_id in ("opta_the_analyst", "understat", "fotmob", "statmuse"):
        canonical = _canonical_truth(identity_map, source_id, canonical_count)
        if source_id == "opta_the_analyst":
            observed = {
                "observed_provider_player_count": canonical_count,
                "observed_joined_player_count": canonical["canonical_mapped_player_count"],
                "observed_unmapped_player_count": max(0, canonical_count - canonical["canonical_mapped_player_count"]),
                "observed_join_coverage_ratio": canonical["canonical_coverage_ratio"],
                "observed_join_health": "GREEN" if canonical["canonical_mapped_player_count"] == canonical_count else "RED",
                "duplicate_observed_native_record_count": 0,
                "missing_native_id_record_count": 0,
                "identity_conflict_count": canonical["configured_link_conflict_count"],
                "observed_unmapped_native_ids": [],
                "conflicting_native_ids": [],
            }
            absence_status = "PROVEN_BY_SHARED_NAMESPACE"
            no_provider_entity_count: int | None = 0
        else:
            observed = _observed_truth(_player_rows(datasets.get(source_id)))
            absence_status = "NOT_PROVEN"
            no_provider_entity_count = None

        sources[source_id] = {
            **canonical,
            **observed,
            "provider_universe_completeness": _PROVIDER_COMPLETENESS[source_id],
            "absence_classification_status": absence_status,
            "no_provider_entity_count": no_provider_entity_count,
            "provider_entity_exists_but_unmapped_count": observed["observed_unmapped_player_count"],
            "fuzzy_or_name_join_used": False,
        }

    return {
        "schema_version": 1,
        "canonical": True,
        "semantic_class": "IDENTITY_COVERAGE_TRUTH",
        "authority": "V6_DETERMINISTIC_IDENTITY",
        "generated_at": utc_now(),
        "canonical_authority": "official_fpl",
        "canonical_player_count": canonical_count,
        "coverage_semantics": {
            "canonical_coverage": "verified provider identities divided by all Official FPL players",
            "observed_join_coverage": "verified joins divided by unique provider-native player records actually observed by the current V6 acquisition surface",
            "observed_join_coverage_is_not_provider_universe_coverage": True,
            "no_provider_entity_requires_complete_provider_universe_proof": True,
        },
        "sources": sources,
        "evidence_posture": evidence_config,
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "fuzzy_name_matching_allowed": False,
            "unobserved_player_is_not_assumed_absent_from_provider": True,
            "partial_verified_coverage_is_truthful": True,
            "observed_unmapped_records_fail_closed": True,
            "reep_v1_overlay_is_not_runtime_join_authority": True,
        },
    }
