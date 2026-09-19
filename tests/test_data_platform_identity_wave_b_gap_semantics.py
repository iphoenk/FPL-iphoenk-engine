from __future__ import annotations

from src.runtime_v6.identity_coverage import build_player_identity_coverage_truth


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
                },
            },
            "2": {
                "official_fpl_element_id": 2,
                "links": {"opta_the_analyst": _link(1002, "EXACT")},
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
                "mapped_player_count": 1,
                "mapped_status": "VERIFIED_MANUAL",
                "join_allowed": True,
                "configured_mapping_count": 1,
                "duplicate_canonical_code_count": 0,
                "conflicting_existing_link_count": 0,
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


def test_partial_provider_universe_stays_amber_even_when_observed_rows_are_joined() -> None:
    datasets = {
        "understat": {
            "record_groups": {
                "players": [
                    {
                        "source_native_id": 10,
                        "player_name": "Diagnostic only",
                        "official_element_id": 1,
                        "identity_status": "VERIFIED_MANUAL",
                    }
                ]
            }
        }
    }
    row = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())["sources"]["understat"]
    assert row["canonical_coverage_ratio"] == 0.25
    assert row["canonical_coverage_health"] == "AMBER"
    assert row["observed_join_coverage_ratio"] == 1.0
    assert row["player_identity_health"] == "AMBER"
    assert row["wave_b_closure_ready"] is False
    assert row["identity_health_reason"] == "UNKNOWN_PROVIDER_PRESENCE_REMAINS"
    assert row["provider_native_classification_counts"] == {
        "VERIFIED": 1,
        "ACTIONABLE_UNMAPPED": 0,
        "REVIEWED_PROVIDER_LIMITATION": 0,
        "NO_PROVIDER_ENTITY": 0,
        "NOT_APPLICABLE": 0,
        "CONFLICT": 0,
    }
    assert row["canonical_classification_counts"]["UNKNOWN_PROVIDER_PRESENCE"] == 3


def test_observed_unmapped_is_red_for_wave_b_but_not_integrity_corruption() -> None:
    datasets = {
        "understat": {
            "record_groups": {
                "players": [
                    {
                        "source_native_id": 10,
                        "official_element_id": 1,
                        "identity_status": "VERIFIED_MANUAL",
                    },
                    {
                        "source_native_id": 12,
                        "player_name": "Display only",
                        "club": "Example FC",
                        "official_element_id": None,
                        "identity_status": "UNMAPPED",
                    },
                ]
            }
        }
    }
    report = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())
    row = report["sources"]["understat"]
    assert report["integrity_status"] == "PASS"
    assert row["observed_join_health"] == "AMBER"
    assert row["player_identity_health"] == "RED"
    assert row["wave_b_closure_ready"] is False
    assert row["provider_entity_exists_but_unmapped_count"] == 1
    assert row["provider_native_classification_counts"]["ACTIONABLE_UNMAPPED"] == 1
    gap = next(item for item in row["provider_native_inventory"] if item["source_native_id"] == "12")
    assert gap["classification"] == "ACTIONABLE_UNMAPPED"
    assert gap["diagnostic_display_is_not_identity_evidence"] is True


def test_duplicate_native_id_is_fail_closed_even_when_target_is_same() -> None:
    datasets = {
        "understat": {
            "record_groups": {
                "players": [
                    {"source_native_id": 10, "official_element_id": 1, "identity_status": "VERIFIED_MANUAL"},
                    {"source_native_id": 10, "official_element_id": 1, "identity_status": "VERIFIED_MANUAL"},
                ]
            }
        }
    }
    report = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())
    row = report["sources"]["understat"]
    assert row["duplicate_observed_native_record_count"] == 1
    assert row["duplicate_observed_native_ids"] == ["10"]
    assert row["player_identity_health"] == "RED"
    assert row["provider_native_classification_counts"]["CONFLICT"] == 1
    assert report["integrity_status"] == "FAIL"
    assert "understat:duplicate_observed_native_id" in report["integrity_errors"]


def test_partial_surface_never_invents_no_provider_entity() -> None:
    row = build_player_identity_coverage_truth(_identity_map(), {}, _evidence())["sources"]["understat"]
    assert row["absence_classification_status"] == "NOT_PROVEN"
    assert row["no_provider_entity_count"] is None
    assert row["canonical_classification_counts"]["NO_PROVIDER_ENTITY"] is None
    assert row["canonical_classification_counts"]["UNKNOWN_PROVIDER_PRESENCE"] == 3
    assert row["player_identity_health"] == "NOT_ASSESSED"
