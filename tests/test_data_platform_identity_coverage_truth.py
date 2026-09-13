from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.identity_coverage import (
    build_player_identity_coverage_truth,
    validate_player_identity_coverage_truth,
)


def _link(native_id: int, status: str = "VERIFIED_MANUAL") -> dict:
    return {"source_native_id": native_id, "status": status}


def _identity_map() -> dict:
    return {
        "canonical_player_count": 4,
        "mappings": {
            "1": {
                "official_fpl_element_id": 1,
                "links": {
                    "opta_the_analyst": _link(1001, "EXACT"),
                    "understat": _link(10),
                    "fotmob": _link(20),
                    "statmuse": _link(30),
                },
            },
            "2": {
                "official_fpl_element_id": 2,
                "links": {
                    "opta_the_analyst": _link(1002, "EXACT"),
                    "understat": _link(11),
                    "fotmob": _link(21),
                },
            },
            "3": {
                "official_fpl_element_id": 3,
                "links": {"opta_the_analyst": _link(1003, "EXACT")},
            },
            "4": {
                "official_fpl_element_id": 4,
                "links": {"opta_the_analyst": _link(1004, "EXACT")},
            },
        },
        "coverage": {
            "opta_the_analyst": {
                "strategy": "OFFICIAL_FPL_CODE_SHARED_OPTA_NUMERIC_NAMESPACE",
                "mapped_player_count": 4,
                "mapped_status": "EXACT",
                "join_allowed": True,
                "duplicate_canonical_code_count": 0,
            },
            "understat": {
                "strategy": "TEST_VERIFIED",
                "mapped_player_count": 2,
                "mapped_status": "VERIFIED_MANUAL",
                "join_allowed": True,
                "configured_mapping_count": 2,
                "duplicate_canonical_code_count": 0,
                "conflicting_existing_link_count": 0,
            },
            "fotmob": {
                "strategy": "TEST_VERIFIED",
                "mapped_player_count": 2,
                "mapped_status": "VERIFIED_MANUAL",
                "join_allowed": True,
                "configured_mapping_count": 2,
            },
            "statmuse": {
                "strategy": "TEST_VERIFIED",
                "mapped_player_count": 1,
                "mapped_status": "VERIFIED_MANUAL",
                "join_allowed": True,
                "configured_mapping_count": 1,
            },
        },
    }


def _evidence() -> dict:
    return {
        "schema_version": 1,
        "canonical_authority": "official_fpl",
        "fuzzy_name_matching_allowed": False,
        "governance": {"reep_v1_overlay_is_discovery_only": True},
    }


def test_partial_canonical_can_have_green_observed_join_coverage() -> None:
    datasets = {
        "understat": {
            "record_groups": {
                "players": [
                    {"source_native_id": 10, "official_element_id": 1, "identity_status": "VERIFIED_MANUAL"},
                    {"source_native_id": 11, "official_element_id": 2, "identity_status": "VERIFIED_MANUAL"},
                ]
            }
        }
    }
    report = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())
    row = report["sources"]["understat"]
    assert report["schema_version"] == 2
    assert report["integrity_status"] == "PASS"
    assert row["canonical_coverage_ratio"] == 0.5
    assert row["canonical_coverage_health"] == "AMBER"
    assert row["canonical_mapping_count_consistent"] is True
    assert row["actual_joinable_mapping_count"] == 2
    assert row["observed_join_coverage_ratio"] == 1.0
    assert row["observed_join_health"] == "GREEN"
    assert row["absence_classification_status"] == "NOT_PROVEN"
    assert row["no_provider_entity_count"] is None


def test_observed_unmapped_player_is_explicit_and_fail_closed() -> None:
    datasets = {
        "understat": {
            "record_groups": {
                "players": [
                    {"source_native_id": 10, "official_element_id": 1, "identity_status": "VERIFIED_MANUAL"},
                    {"source_native_id": 11, "official_element_id": 2, "identity_status": "VERIFIED_MANUAL"},
                    {"source_native_id": 12, "official_element_id": None, "identity_status": "UNMAPPED"},
                ]
            }
        }
    }
    row = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())["sources"]["understat"]
    assert row["observed_provider_player_count"] == 3
    assert row["observed_joined_player_count"] == 2
    assert row["provider_entity_exists_but_unmapped_count"] == 1
    assert row["observed_join_coverage_ratio"] == 0.666667
    assert row["observed_join_health"] == "AMBER"
    assert row["observed_unmapped_native_ids"] == ["12"]


def test_native_mapping_to_multiple_canonical_players_is_red() -> None:
    datasets = {
        "fotmob": {
            "record_groups": {
                "players": [
                    {"source_native_id": 20, "official_element_id": 1, "identity_status": "VERIFIED_MANUAL"},
                    {"source_native_id": 20, "official_element_id": 2, "identity_status": "VERIFIED_MANUAL"},
                ]
            }
        }
    }
    report = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())
    row = report["sources"]["fotmob"]
    assert row["observed_provider_player_count"] == 1
    assert row["duplicate_observed_native_record_count"] == 1
    assert row["native_to_multiple_canonical_target_count"] == 1
    assert row["identity_conflict_count"] == 1
    assert row["observed_joined_player_count"] == 0
    assert row["observed_join_health"] == "RED"
    assert row["conflicting_native_ids"] == ["20"]
    assert report["integrity_status"] == "FAIL"


def test_multiple_native_ids_for_one_canonical_player_is_red() -> None:
    datasets = {
        "fotmob": {
            "record_groups": {
                "players": [
                    {"source_native_id": 20, "official_element_id": 1, "identity_status": "VERIFIED_MANUAL"},
                    {"source_native_id": 22, "official_element_id": 1, "identity_status": "VERIFIED_MANUAL"},
                ]
            }
        }
    }
    report = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())
    row = report["sources"]["fotmob"]
    assert row["canonical_target_collision_count"] == 1
    assert row["canonical_target_collisions"] == {"1": ["20", "22"]}
    assert row["observed_joined_player_count"] == 0
    assert row["identity_conflict_count"] == 1
    assert row["observed_join_health"] == "RED"
    assert report["integrity_status"] == "FAIL"


def test_declared_canonical_count_is_reconciled_to_actual_links() -> None:
    identity = deepcopy(_identity_map())
    identity["coverage"]["understat"]["mapped_player_count"] = 3
    report = build_player_identity_coverage_truth(identity, {}, _evidence())
    row = report["sources"]["understat"]
    assert row["canonical_mapped_player_count"] == 3
    assert row["actual_joinable_mapping_count"] == 2
    assert row["canonical_mapping_count_consistent"] is False
    assert row["canonical_coverage_health"] == "RED"
    assert report["integrity_status"] == "FAIL"
    assert "understat:canonical_mapping_count_mismatch" in report["integrity_errors"]


def test_opta_shared_namespace_is_complete_without_source_dataset() -> None:
    row = build_player_identity_coverage_truth(_identity_map(), {}, _evidence())["sources"]["opta_the_analyst"]
    assert row["canonical_coverage_ratio"] == 1.0
    assert row["observed_join_coverage_ratio"] == 1.0
    assert row["observed_join_health"] == "GREEN"
    assert row["absence_classification_status"] == "PROVEN_BY_SHARED_NAMESPACE"
    assert row["no_provider_entity_count"] == 0


def test_empty_partial_acquisition_does_not_claim_provider_absence() -> None:
    row = build_player_identity_coverage_truth(_identity_map(), {}, _evidence())["sources"]["statmuse"]
    assert row["observed_provider_player_count"] == 0
    assert row["observed_join_health"] == "RED"
    assert row["provider_universe_completeness"] == "PARTIAL_QUERY_RESULT"
    assert row["absence_classification_status"] == "NOT_PROVEN"
    assert row["no_provider_entity_count"] is None
    assert row["canonical_mapped_player_count"] == 1


def test_coverage_validator_accepts_clean_artifact_and_rejects_tampering() -> None:
    identity = _identity_map()
    report = build_player_identity_coverage_truth(identity, {}, _evidence())
    assert validate_player_identity_coverage_truth(report, identity) == []

    tampered = deepcopy(report)
    tampered["sources"]["understat"]["canonical_mapping_count_consistent"] = False
    errors = validate_player_identity_coverage_truth(tampered, identity)
    assert "understat:canonical_mapping_count_mismatch" in errors
