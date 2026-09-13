from __future__ import annotations

from src.runtime_v6.identity_coverage import build_player_identity_coverage_truth


def test_ffscout_public_exact_code_is_tracked_as_partial_observation() -> None:
    identity = {
        "canonical_player_count": 2,
        "mappings": {
            "1": {
                "official_fpl_element_id": 1,
                "links": {
                    "opta_the_analyst": {"source_native_id": 1001, "status": "EXACT"},
                    "ffscout": {"source_native_id": 1001, "status": "EXACT"},
                },
            },
            "2": {
                "official_fpl_element_id": 2,
                "links": {"opta_the_analyst": {"source_native_id": 1002, "status": "EXACT"}},
            },
        },
        "coverage": {
            "opta_the_analyst": {
                "strategy": "OFFICIAL_FPL_CODE_SHARED_OPTA_NUMERIC_NAMESPACE",
                "mapped_player_count": 2,
                "mapped_status": "EXACT",
                "join_allowed": True,
                "duplicate_canonical_code_count": 0,
            },
            "ffscout": {
                "strategy": "FFSCOUT_PUBLIC_PREMIERLEAGUE_MEDIA_CODE_EXACT",
                "mapped_player_count": 1,
                "mapped_status": "EXACT",
                "join_allowed": True,
                "duplicate_canonical_code_count": 0,
            },
        },
    }
    datasets = {
        "ffscout": {
            "record_groups": {
                "players": [
                    {
                        "source_native_id": 1001,
                        "official_element_id": 1,
                        "identity_status": "EXACT",
                    }
                ]
            }
        }
    }
    evidence = {
        "schema_version": 1,
        "canonical_authority": "official_fpl",
        "fuzzy_name_matching_allowed": False,
    }

    report = build_player_identity_coverage_truth(identity, datasets, evidence)
    row = report["sources"]["ffscout"]

    assert row["canonical_mapped_player_count"] == 1
    assert row["canonical_coverage_ratio"] == 0.5
    assert row["observed_provider_player_count"] == 1
    assert row["observed_joined_player_count"] == 1
    assert row["observed_join_coverage_ratio"] == 1.0
    assert row["observed_join_health"] == "GREEN"
    assert row["provider_universe_completeness"] == "PARTIAL_PUBLIC_PAGE_REFERENCE_OBSERVATION"
    assert row["absence_classification_status"] == "NOT_PROVEN"
    assert report["integrity_status"] == "PASS"
