from __future__ import annotations

import pytest

from src.runtime_v6.authority_contract import AuthorityContractError, validate_artifact_descriptor
from src.runtime_v6.identity_coverage import build_player_identity_coverage_truth


def _minimal_identity_map() -> dict:
    empty_coverage = {
        "strategy": "TEST_EMPTY",
        "mapped_player_count": 0,
        "mapped_status": "VERIFIED_MANUAL",
        "join_allowed": True,
        "configured_mapping_count": 0,
        "duplicate_canonical_code_count": 0,
        "conflicting_existing_link_count": 0,
    }
    return {
        "canonical_player_count": 1,
        "mappings": {
            "1": {
                "official_fpl_element_id": 1,
                "links": {
                    "opta_the_analyst": {
                        "source_native_id": 1001,
                        "status": "EXACT",
                    }
                },
            }
        },
        "coverage": {
            "opta_the_analyst": {
                "strategy": "OFFICIAL_FPL_CODE_SHARED_OPTA_NUMERIC_NAMESPACE",
                "mapped_player_count": 1,
                "mapped_status": "EXACT",
                "join_allowed": True,
                "duplicate_canonical_code_count": 0,
                "conflicting_existing_link_count": 0,
            },
            "understat": dict(empty_coverage),
            "fotmob": dict(empty_coverage),
            "statmuse": dict(empty_coverage),
            "ffscout": dict(empty_coverage),
        },
    }


def _evidence_config() -> dict:
    return {
        "schema_version": 1,
        "canonical_authority": "official_fpl",
        "fuzzy_name_matching_allowed": False,
    }


def test_identity_coverage_truth_uses_allowed_canonical_semantic_class() -> None:
    report = build_player_identity_coverage_truth(
        _minimal_identity_map(),
        {},
        _evidence_config(),
    )

    assert report["semantic_class"] == "CONTROL_TELEMETRY"
    validate_artifact_descriptor(report)


def test_identity_coverage_unknown_semantic_class_remains_fail_closed() -> None:
    report = build_player_identity_coverage_truth(
        _minimal_identity_map(),
        {},
        _evidence_config(),
    )
    report["semantic_class"] = "IDENTITY_COVERAGE_TRUTH"

    with pytest.raises(AuthorityContractError, match="unknown canonical semantic class"):
        validate_artifact_descriptor(report)
