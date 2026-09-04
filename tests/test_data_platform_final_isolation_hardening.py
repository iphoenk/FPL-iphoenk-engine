from pathlib import Path

from src.runtime_v6.architecture_independence_validate import validate_repository
from src.runtime_v6.collector import _zero_authority_fields
from src.runtime_v6.consumer import _governance_failures, _invalid_result
from src.runtime_v6.registry import ZERO_AUTHORITY_KEYS


def _valid_governance() -> dict[str, object]:
    return {
        "data_only": True,
        "production_ingestion_schedule_only": True,
        **{key: "NONE" for key in ZERO_AUTHORITY_KEYS},
    }


def test_v6_runtime_boundary_has_no_other_engine_dependencies():
    assert validate_repository(Path(".")) == []


def test_collector_serializes_every_zero_authority_dimension_from_single_keyset():
    policy = {key: "NONE" for key in ZERO_AUTHORITY_KEYS}
    fields = _zero_authority_fields(policy)

    assert tuple(fields) == ZERO_AUTHORITY_KEYS
    assert all(value == "NONE" for value in fields.values())
    assert _zero_authority_fields() == policy


def test_consumer_rejects_any_business_authority_leak_not_only_prediction_core():
    baseline = _valid_governance()
    assert _governance_failures(baseline) == []

    for key in ZERO_AUTHORITY_KEYS:
        mutated = dict(baseline)
        mutated[key] = "ENABLED"
        assert f"UNEXPECTED_{key.upper()}" in _governance_failures(mutated)


def test_consumer_fallback_is_external_source_only_and_never_other_engine_artifacts():
    result = _invalid_result("TEST_FAILURE")

    assert result["direct_fallback_eligible"] is True
    assert result["fallback_scope"] == "EXTERNAL_SOURCES_ONLY"
    assert result["engine_artifact_fallback_allowed"] is False


def test_v6_primary_documentation_names_owned_dependency_locks():
    text = Path("docs/V6_FRESH_DATA_PLATFORM.md").read_text(encoding="utf-8")

    assert "requirements-v6.lock" in text
    assert "requirements-v6-ci.lock" in text
    assert "V6 never reads V3/V4/V5 runtime branches, data trees, caches, manifests, or engine artifacts" in text
