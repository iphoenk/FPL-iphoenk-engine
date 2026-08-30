from __future__ import annotations

from src.runtime_v3 import capability_terminology_validate


def test_capability_terminology_contract_is_canonical_and_complete() -> None:
    result = capability_terminology_validate.run()
    assert result["status"] == "PASS", result["errors"]
    assert result["canonical_runtime_boundary"] == "execution_domain"
    assert result["canonical_business_unit"] == "capability"
    assert result["execution_domain_count"] == 11
    assert result["capability_count"] == 21
    assert result["legacy_collection_key"] == "services"
    assert result["legacy_collection_status"] == "LEGACY_COMPATIBILITY_ALIAS"
