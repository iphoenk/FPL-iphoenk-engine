from __future__ import annotations

from src.runtime_v3 import capability_telemetry


def test_capability_telemetry_is_canonical_and_legacy_aliases_match() -> None:
    result = capability_telemetry.run()
    assert result["status"] == "PASS", result["errors"]
    assert result["registry"] == "V3_CAPABILITY_TELEMETRY_V1"
    assert result["canonical_runtime_boundary"] == "execution_domain"
    assert result["execution_domain_count"] == 11
    assert result["canonical_business_unit"] == "capability"
    assert result["capability_count"] == 22
    assert result["background_capability_count"] == 22
    assert result["interactive_endpoint_count"] == 1
    aliases = result["compatibility_aliases"]
    assert aliases["service_count"] == result["capability_count"]
    assert aliases["root_services"] == result["root_capabilities"]
    assert aliases["background_service_count"] == result["background_capability_count"]
    assert aliases["interactive_service_count"] == result["interactive_endpoint_count"]
