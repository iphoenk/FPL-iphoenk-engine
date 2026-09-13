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
    "ffscout": "PARTIAL_PUBLIC_PAGE_REFERENCE_OBSERVATION",
}
_EXPECTED_SOURCES = tuple(_PROVIDER_COMPLETENESS)


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

    limitations = payload.get("reviewed_provider_limitations") or {}
    if limitations:
        if limitations.get("policy") != "EXPLICIT_NATIVE_ID_ALLOWLIST_ONLY":
            raise IdentityCoverageError("reviewed provider limitation policy mismatch")
        if limitations.get("classification") != "NOT_APPLICABLE":
            raise IdentityCoverageError("reviewed provider limitation classification mismatch")
        for source_id, source in ((limitations.get("sources") or {}).items()):
            native_ids = [str(value).strip() for value in source.get("source_native_ids") or []]
            if not native_ids or len(native_ids) != len(set(native_ids)):
                raise IdentityCoverageError(f"{source_id}: reviewed provider limitation native IDs invalid")
            if source.get("review_status") != "REVIEWED_PROVIDER_LIMITATION":
                raise IdentityCoverageError(f"{source_id}: reviewed provider limitation status invalid")
            if not source.get("review_reference") or not source.get("evidence"):
                raise IdentityCoverageError(f"{source_id}: reviewed provider limitation evidence missing")
            if source.get("name_matching_used") is not False or source.get("fuzzy_matching_used") is not False:
                raise IdentityCoverageError(f"{source_id}: reviewed provider limitation cannot use name/fuzzy matching")
            if any(key in source for key in ("name", "player_name", "display_name")):
                raise IdentityCoverageError(f"{source_id}: reviewed provider limitation must be native-ID only")
    return payload


def _player_rows(dataset: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(dataset, dict):
        return []
    rows = ((dataset.get("record_groups") or {}).get("players") or [])
    return [dict(row) for row in rows if isinstance(row, dict)]


def _diagnostic_label(row: dict[str, Any]) -> dict[str, Any]:
    """Display-only context. These fields are never used as identity keys."""
    return {
        "player_name": row.get("player_name") or row.get("name"),
        "club": row.get("club") or row.get("team_title") or row.get("team_name"),
    }


def _observed_truth(
    rows: list[dict[str, Any]],
    reviewed_limitations: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    by_native: dict[str, list[dict[str, Any]]] = {}
    missing_native = 0
    for row in rows:
        native = row.get("source_native_id")
        if native is None or str(native).strip() == "":
            missing_native += 1
            continue
        by_native.setdefault(str(native).strip(), []).append(row)

    reviewed_limitations = reviewed_limitations or {}
    joined_native: set[str] = set()
    unmapped_native: set[str] = set()
    reviewed_nonjoinable_native: set[str] = set()
    native_to_multiple_targets: set[str] = set()
    canonical_to_natives: dict[int, set[str]] = {}
    duplicate_native_records = 0
    duplicate_native_ids: set[str] = set()
    inventory: list[dict[str, Any]] = []

    for native, native_rows in sorted(by_native.items()):
        duplicate_count = max(0, len(native_rows) - 1)
        duplicate_native_records += duplicate_count
        if duplicate_count:
            duplicate_native_ids.add(native)

        joined_targets: set[int] = set()
        has_joinable = False
        join_statuses: set[str] = set()
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
                join_statuses.add(status)

        limitation = reviewed_limitations.get(native)
        if len(joined_targets) > 1:
            native_to_multiple_targets.add(native)
        elif has_joinable:
            joined_native.add(native)
            target = next(iter(joined_targets))
            canonical_to_natives.setdefault(target, set()).add(native)
        elif limitation:
            reviewed_nonjoinable_native.add(native)
        else:
            unmapped_native.add(native)

        if duplicate_count or len(joined_targets) > 1:
            classification = "CONFLICT"
            reason = "DUPLICATE_NATIVE_ID" if duplicate_count else "NATIVE_ID_MULTIPLE_CANONICAL_TARGETS"
        elif has_joinable:
            classification = "VERIFIED"
            reason = "DETERMINISTIC_JOIN"
        elif limitation:
            classification = "NOT_APPLICABLE"
            reason = str(limitation.get("reason") or "REVIEWED_PROVIDER_LIMITATION_NO_TRUSTED_CROSS_ID")
        else:
            classification = "PROVIDER_ENTITY_EXISTS_BUT_UNMAPPED"
            reason = "OBSERVED_NATIVE_ENTITY_WITHOUT_DETERMINISTIC_JOIN"

        diagnostic = _diagnostic_label(native_rows[0])
        inventory.append(
            {
                "source_native_id": native,
                "classification": classification,
                "reason": reason,
                "official_element_id": next(iter(joined_targets)) if len(joined_targets) == 1 else None,
                "identity_status": sorted(join_statuses)[0] if len(join_statuses) == 1 else None,
                "duplicate_record_count": duplicate_count,
                "diagnostic_display": diagnostic,
                "diagnostic_display_is_not_identity_evidence": True,
                "provider_limitation": dict(limitation) if limitation and not has_joinable else None,
            }
        )

    canonical_target_collisions = {
        official_id: sorted(natives)
        for official_id, natives in canonical_to_natives.items()
        if len(natives) > 1
    }
    collision_native_ids = {
        native
        for natives in canonical_target_collisions.values()
        for native in natives
    }
    hard_conflict_native_ids = native_to_multiple_targets | collision_native_ids | duplicate_native_ids

    # Reclassify any native ID implicated by a reverse canonical collision.
    if collision_native_ids:
        for item in inventory:
            if item["source_native_id"] in collision_native_ids:
                item["classification"] = "CONFLICT"
                item["reason"] = "MULTIPLE_NATIVE_IDS_ONE_CANONICAL_TARGET"

    observed = len(by_native)
    joined = len(joined_native - hard_conflict_native_ids)
    unmapped = len(unmapped_native)
    reviewed_nonjoinable = len(reviewed_nonjoinable_native - hard_conflict_native_ids)
    join_eligible = max(0, observed - reviewed_nonjoinable)
    native_conflict_count = len(native_to_multiple_targets)
    canonical_collision_count = len(canonical_target_collisions)
    conflict_count = native_conflict_count + canonical_collision_count
    ratio = round(joined / observed, 6) if observed else 0.0
    provider_max_ratio = round(joined / join_eligible, 6) if join_eligible else (1.0 if observed and reviewed_nonjoinable == observed else 0.0)

    # Keep the Wave-A coverage signal for backwards compatibility.
    if conflict_count or missing_native or duplicate_native_records:
        observed_health = "RED"
    elif observed and joined == observed:
        observed_health = "GREEN"
    elif observed and joined:
        observed_health = "AMBER"
    else:
        observed_health = "RED"

    # Wave-B identity health is intentionally stricter: an observed provider
    # entity that is still unmapped is a real unresolved identity defect.
    if conflict_count or missing_native or duplicate_native_records or unmapped:
        player_identity_health = "RED"
    elif observed and joined + reviewed_nonjoinable == observed:
        player_identity_health = "GREEN"
    else:
        player_identity_health = "NOT_ASSESSED"

    classification_counts = {
        "VERIFIED": sum(item["classification"] == "VERIFIED" for item in inventory),
        "PROVIDER_ENTITY_EXISTS_BUT_UNMAPPED": sum(
            item["classification"] == "PROVIDER_ENTITY_EXISTS_BUT_UNMAPPED" for item in inventory
        ),
        "NO_PROVIDER_ENTITY": 0,
        "NOT_APPLICABLE": sum(item["classification"] == "NOT_APPLICABLE" for item in inventory),
        "CONFLICT": sum(item["classification"] == "CONFLICT" for item in inventory),
    }

    return {
        "observed_provider_player_count": observed,
        "observed_joined_player_count": joined,
        "observed_unmapped_player_count": unmapped,
        "observed_reviewed_provider_limitation_count": reviewed_nonjoinable,
        "observed_join_eligible_player_count": join_eligible,
        "observed_join_coverage_ratio": ratio,
        "provider_max_observed_join_coverage_ratio": provider_max_ratio,
        "observed_join_health": observed_health,
        "player_identity_health": player_identity_health,
        "wave_b_closure_ready": player_identity_health == "GREEN",
        "duplicate_observed_native_record_count": duplicate_native_records,
        "duplicate_observed_native_ids": sorted(duplicate_native_ids),
        "missing_native_id_record_count": missing_native,
        "identity_conflict_count": conflict_count,
        "native_to_multiple_canonical_target_count": native_conflict_count,
        "canonical_target_collision_count": canonical_collision_count,
        "observed_unmapped_native_ids": sorted(unmapped_native),
        "reviewed_provider_limitation_native_ids": sorted(reviewed_nonjoinable_native),
        "conflicting_native_ids": sorted(native_to_multiple_targets | collision_native_ids | duplicate_native_ids),
        "canonical_target_collisions": {
            str(official_id): natives
            for official_id, natives in sorted(canonical_target_collisions.items())
        },
        "provider_native_classification_counts": classification_counts,
        "provider_native_inventory": inventory,
    }


def _actual_joinable_links(identity_map: dict[str, Any], source_id: str) -> dict[str, Any]:
    native_to_canonical: dict[str, set[int]] = {}
    joinable_count = 0
    missing_native = 0
    for mapping in (identity_map.get("mappings") or {}).values():
        if not isinstance(mapping, dict):
            continue
        link = ((mapping.get("links") or {}).get(source_id) or {})
        if str(link.get("status") or "") not in _JOINABLE:
            continue
        try:
            official_id = int(mapping.get("official_fpl_element_id"))
        except (TypeError, ValueError):
            continue
        native = link.get("source_native_id")
        if native is None or str(native).strip() == "":
            missing_native += 1
            continue
        native_key = str(native).strip()
        joinable_count += 1
        native_to_canonical.setdefault(native_key, set()).add(official_id)

    duplicate_native_ids = {
        native: sorted(targets)
        for native, targets in native_to_canonical.items()
        if len(targets) > 1
    }
    return {
        "actual_joinable_mapping_count": joinable_count,
        "actual_joinable_missing_native_id_count": missing_native,
        "actual_duplicate_native_id_count": len(duplicate_native_ids),
        "actual_duplicate_native_ids": duplicate_native_ids,
    }


def _canonical_truth(identity_map: dict[str, Any], source_id: str, canonical_count: int) -> dict[str, Any]:
    coverage = ((identity_map.get("coverage") or {}).get(source_id) or {})
    mapped = int(coverage.get("mapped_player_count") or 0)
    actual = _actual_joinable_links(identity_map, source_id)
    count_consistent = mapped == actual["actual_joinable_mapping_count"]
    ratio = round(mapped / canonical_count, 6) if canonical_count else 0.0
    hard_error = (
        not count_consistent
        or actual["actual_joinable_missing_native_id_count"] > 0
        or actual["actual_duplicate_native_id_count"] > 0
        or int(coverage.get("duplicate_canonical_code_count") or 0) > 0
        or int(coverage.get("conflicting_existing_link_count") or 0) > 0
        or mapped > canonical_count
    )
    if hard_error:
        health = "RED"
    elif canonical_count and mapped == canonical_count:
        health = "GREEN"
    else:
        health = "AMBER" if mapped else "RED"
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
        "canonical_mapping_count_consistent": count_consistent,
        **actual,
    }


def _source_integrity_errors(source_id: str, row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if row.get("canonical_mapping_count_consistent") is not True:
        errors.append(f"{source_id}:canonical_mapping_count_mismatch")
    if int(row.get("actual_joinable_missing_native_id_count") or 0):
        errors.append(f"{source_id}:joinable_mapping_missing_native_id")
    if int(row.get("actual_duplicate_native_id_count") or 0):
        errors.append(f"{source_id}:duplicate_native_id_across_canonical_players")
    if int(row.get("duplicate_canonical_code_count") or 0):
        errors.append(f"{source_id}:duplicate_canonical_code")
    if int(row.get("configured_link_conflict_count") or 0):
        errors.append(f"{source_id}:configured_link_conflict")
    if int(row.get("duplicate_observed_native_record_count") or 0):
        errors.append(f"{source_id}:duplicate_observed_native_id")
    if int(row.get("missing_native_id_record_count") or 0):
        errors.append(f"{source_id}:observed_record_missing_native_id")
    if int(row.get("identity_conflict_count") or 0):
        errors.append(f"{source_id}:observed_identity_conflict")
    return errors


def validate_player_identity_coverage_truth(
    report: dict[str, Any],
    identity_map: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 2:
        errors.append("identity_coverage_schema_mismatch")
    if report.get("canonical_authority") != "official_fpl":
        errors.append("identity_coverage_canonical_authority_mismatch")
    if int(report.get("canonical_player_count") or 0) != int(identity_map.get("canonical_player_count") or 0):
        errors.append("identity_coverage_canonical_player_count_mismatch")
    if ((report.get("governance") or {}).get("fuzzy_name_matching_allowed")) is not False:
        errors.append("identity_coverage_fuzzy_policy_invalid")

    sources = report.get("sources") or {}
    for source_id in _EXPECTED_SOURCES:
        row = sources.get(source_id)
        if not isinstance(row, dict):
            errors.append(f"{source_id}:identity_coverage_source_missing")
            continue
        errors.extend(_source_integrity_errors(source_id, row))

    declared = [str(value) for value in report.get("integrity_errors") or []]
    if sorted(set(declared)) != sorted(set(errors)):
        errors.append("identity_coverage_declared_integrity_errors_mismatch")
    expected_status = "PASS" if not [error for error in errors if error != "identity_coverage_declared_integrity_errors_mismatch"] else "FAIL"
    if report.get("integrity_status") != expected_status:
        errors.append("identity_coverage_integrity_status_mismatch")
    return errors


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
    for source_id in _EXPECTED_SOURCES:
        canonical = _canonical_truth(identity_map, source_id, canonical_count)
        if source_id == "opta_the_analyst":
            observed = {
                "observed_provider_player_count": canonical_count,
                "observed_joined_player_count": canonical["canonical_mapped_player_count"],
                "observed_unmapped_player_count": max(0, canonical_count - canonical["canonical_mapped_player_count"]),
                "observed_join_coverage_ratio": canonical["canonical_coverage_ratio"],
                "observed_join_health": "GREEN" if canonical["canonical_coverage_health"] == "GREEN" else "RED",
                "player_identity_health": "GREEN" if canonical["canonical_coverage_health"] == "GREEN" else "RED",
                "wave_b_closure_ready": canonical["canonical_coverage_health"] == "GREEN",
                "duplicate_observed_native_record_count": 0,
                "duplicate_observed_native_ids": [],
                "missing_native_id_record_count": 0,
                "identity_conflict_count": canonical["actual_duplicate_native_id_count"],
                "native_to_multiple_canonical_target_count": canonical["actual_duplicate_native_id_count"],
                "canonical_target_collision_count": 0,
                "observed_unmapped_native_ids": [],
                "conflicting_native_ids": sorted(canonical["actual_duplicate_native_ids"]),
                "canonical_target_collisions": {},
                "provider_native_classification_counts": {
                    "VERIFIED": canonical["canonical_mapped_player_count"],
                    "PROVIDER_ENTITY_EXISTS_BUT_UNMAPPED": max(0, canonical_count - canonical["canonical_mapped_player_count"]),
                    "NO_PROVIDER_ENTITY": 0,
                    "NOT_APPLICABLE": 0,
                    "CONFLICT": canonical["actual_duplicate_native_id_count"],
                },
                "provider_native_inventory": [],
            }
            absence_status = "PROVEN_BY_SHARED_NAMESPACE"
            no_provider_entity_count: int | None = 0
        else:
            limitation_source = ((((evidence_config.get("reviewed_provider_limitations") or {}).get("sources") or {}).get(source_id)) or {})
            limitation_common = {key: value for key, value in limitation_source.items() if key != "source_native_ids"}
            reviewed_limitations = {str(value).strip(): dict(limitation_common) for value in limitation_source.get("source_native_ids") or []}
            observed = _observed_truth(_player_rows(datasets.get(source_id)), reviewed_limitations)
            absence_status = "NOT_PROVEN"
            no_provider_entity_count = None

        unknown_provider_presence = (
            None
            if no_provider_entity_count is None
            else max(0, canonical_count - canonical["canonical_mapped_player_count"] - no_provider_entity_count)
        )
        if no_provider_entity_count is None:
            unknown_provider_presence = max(0, canonical_count - canonical["canonical_mapped_player_count"])

        sources[source_id] = {
            **canonical,
            **observed,
            "provider_universe_completeness": _PROVIDER_COMPLETENESS[source_id],
            "absence_classification_status": absence_status,
            "no_provider_entity_count": no_provider_entity_count,
            "provider_entity_exists_but_unmapped_count": observed["observed_unmapped_player_count"],
            "canonical_classification_counts": {
                "VERIFIED": canonical["canonical_mapped_player_count"],
                "PROVIDER_ENTITY_EXISTS_BUT_UNMAPPED_OBSERVED": observed["observed_unmapped_player_count"],
                "NOT_APPLICABLE_OBSERVED": observed.get("observed_reviewed_provider_limitation_count", 0),
                "NO_PROVIDER_ENTITY": no_provider_entity_count,
                "UNKNOWN_PROVIDER_PRESENCE": unknown_provider_presence,
                "CONFLICT": observed["identity_conflict_count"],
            },
            "fuzzy_or_name_join_used": False,
        }

    integrity_errors = [
        error
        for source_id, row in sources.items()
        for error in _source_integrity_errors(source_id, row)
    ]

    return {
        "schema_version": 2,
        "canonical": True,
        "semantic_class": "IDENTITY_COVERAGE_TRUTH",
        "authority": "V6_DETERMINISTIC_IDENTITY",
        "generated_at": utc_now(),
        "canonical_authority": "official_fpl",
        "canonical_player_count": canonical_count,
        "integrity_status": "PASS" if not integrity_errors else "FAIL",
        "integrity_errors": integrity_errors,
        "coverage_semantics": {
            "canonical_coverage": "verified provider identities divided by all Official FPL players",
            "observed_join_coverage": "verified joins divided by unique provider-native player records actually observed by the current V6 acquisition surface",
            "observed_join_coverage_is_not_provider_universe_coverage": True,
            "no_provider_entity_requires_complete_provider_universe_proof": True,
            "canonical_mapping_count_is_reconciled_to_actual_joinable_links": True,
            "provider_native_to_canonical_mapping_is_one_to_one": True,
            "wave_b_green_identity_requires_zero_actionable_observed_unmapped": True,
            "reviewed_provider_limitations_are_excluded_only_from_provider_max_join_denominator": True,
            "raw_observed_join_coverage_remains_visible": True,
            "wave_b_green_identity_does_not_require_657_canonical_mappings": True,
            "provider_native_inventory_names_are_diagnostic_only": True,
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
            "unreviewed_observed_unmapped_records_fail_closed": True,
            "reviewed_provider_limitations_are_non_blocking": True,
            "identity_collisions_fail_closed": True,
            "duplicate_native_ids_fail_closed": True,
            "canonical_and_observed_identity_counts_are_reconciled": True,
            "ffscout_public_identity_is_coverage_tracked": True,
            "reep_v1_overlay_is_not_runtime_join_authority": True,
            "wave_b_health_is_provider_observation_based": True,
        },
    }
