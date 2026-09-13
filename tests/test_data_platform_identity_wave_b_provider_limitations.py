from __future__ import annotations

from src.runtime_v6.identity_coverage import build_player_identity_coverage_truth, load_identity_evidence_config


def _identity_map() -> dict:
    return {
        "canonical_player_count": 2,
        "mappings": {
            "1": {"official_fpl_element_id": 1, "links": {"opta_the_analyst": {"source_native_id": 1001, "status": "EXACT"}, "fotmob": {"source_native_id": 11, "status": "VERIFIED_MANUAL"}}},
            "2": {"official_fpl_element_id": 2, "links": {"opta_the_analyst": {"source_native_id": 1002, "status": "EXACT"}}},
        },
        "coverage": {
            "opta_the_analyst": {"mapped_player_count": 2, "mapped_status": "EXACT", "join_allowed": True, "duplicate_canonical_code_count": 0},
            "fotmob": {"mapped_player_count": 1, "mapped_status": "VERIFIED_MANUAL", "join_allowed": True, "configured_mapping_count": 1, "duplicate_canonical_code_count": 0, "conflicting_existing_link_count": 0},
        },
    }


def _evidence() -> dict:
    return {
        "schema_version": 1,
        "canonical_authority": "official_fpl",
        "fuzzy_name_matching_allowed": False,
        "reviewed_provider_limitations": {
            "policy": "EXPLICIT_NATIVE_ID_ALLOWLIST_ONLY",
            "classification": "NOT_APPLICABLE",
            "sources": {
                "fotmob": {
                    "source_native_ids": [22],
                    "reason": "PROVIDER_PROFILE_SURFACE_HAS_NO_TRUSTED_EXTERNAL_PERSON_ID",
                    "review_status": "REVIEWED_PROVIDER_LIMITATION",
                    "review_reference": "github-actions:run/test",
                    "evidence": ["exact-native-id-audit"],
                    "name_matching_used": False,
                    "fuzzy_matching_used": False,
                }
            },
        },
        "governance": {},
    }


def test_reviewed_provider_limitation_is_visible_but_non_blocking_for_wave_b():
    datasets = {"fotmob": {"record_groups": {"players": [
        {"source_native_id": 11, "official_element_id": 1, "identity_status": "VERIFIED_MANUAL"},
        {"source_native_id": 22, "official_element_id": None, "identity_status": "UNMAPPED"},
    ]}}}
    row = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())["sources"]["fotmob"]
    assert row["observed_provider_player_count"] == 2
    assert row["observed_joined_player_count"] == 1
    assert row["observed_join_coverage_ratio"] == 0.5
    assert row["observed_join_eligible_player_count"] == 1
    assert row["provider_max_observed_join_coverage_ratio"] == 1.0
    assert row["observed_unmapped_player_count"] == 0
    assert row["observed_reviewed_provider_limitation_count"] == 1
    assert row["player_identity_health"] == "GREEN"
    assert row["wave_b_closure_ready"] is True
    assert row["provider_native_classification_counts"]["NOT_APPLICABLE"] == 1
    item = next(v for v in row["provider_native_inventory"] if v["source_native_id"] == "22")
    assert item["classification"] == "NOT_APPLICABLE"
    assert item["provider_limitation"]["review_status"] == "REVIEWED_PROVIDER_LIMITATION"


def test_unreviewed_observed_unmapped_remains_red():
    datasets = {"fotmob": {"record_groups": {"players": [
        {"source_native_id": 11, "official_element_id": 1, "identity_status": "VERIFIED_MANUAL"},
        {"source_native_id": 33, "official_element_id": None, "identity_status": "UNMAPPED"},
    ]}}}
    row = build_player_identity_coverage_truth(_identity_map(), datasets, _evidence())["sources"]["fotmob"]
    assert row["observed_unmapped_player_count"] == 1
    assert row["player_identity_health"] == "RED"
    assert row["wave_b_closure_ready"] is False


def test_production_reviewed_limitations_are_native_id_only_and_audited():
    evidence = load_identity_evidence_config()
    limitations = evidence["reviewed_provider_limitations"]
    assert limitations["policy"] == "EXPLICIT_NATIVE_ID_ALLOWLIST_ONLY"
    assert limitations["classification"] == "NOT_APPLICABLE"
    assert len(limitations["sources"]["fotmob"]["source_native_ids"]) == 34
    assert limitations["sources"]["understat"]["source_native_ids"] == [15045]
    assert limitations["sources"]["statmuse"]["source_native_ids"] == [703]
    for source in limitations["sources"].values():
        assert source["review_status"] == "REVIEWED_PROVIDER_LIMITATION"
        assert source["review_reference"] == "github-actions:run/34765558511"
        assert source["name_matching_used"] is False
        assert source["fuzzy_matching_used"] is False
        assert "name" not in source and "player_name" not in source and "display_name" not in source
