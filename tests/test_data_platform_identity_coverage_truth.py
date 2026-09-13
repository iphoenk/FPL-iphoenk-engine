from __future__ import annotations

from src.runtime_v6.identity_coverage import build_player_identity_coverage_truth


def _identity_map() -> dict:
    return {
        "canonical_player_count": 4,
        "mappings": {str(i): {} for i in range(1, 5)},
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
    assert row["canonical_coverage_ratio"] == 0.5
    assert row["canonical_coverage_health"] == "AMBER"
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


def test_conflicting_native_identity_is_red() -> None:
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
    row = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())["sources"]["fotmob"]
    assert row["observed_provider_player_count"] == 1
    assert row["duplicate_observed_native_record_count"] == 1
    assert row["identity_conflict_count"] == 1
    assert row["observed_joined_player_count"] == 0
    assert row["observed_join_health"] == "RED"
    assert row["conflicting_native_ids"] == ["20"]


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
