from __future__ import annotations

import json

from src.engines import architecture_contract_validate, v3_architecture_ownership_guard
from src.runtime_v3 import capability_terminology_validate


def run() -> dict:
    terminology = capability_terminology_validate.run()
    architecture = architecture_contract_validate.run()
    ownership = v3_architecture_ownership_guard.run()

    errors: list[str] = []
    if terminology.get("status") != "PASS":
        errors.append("capability terminology contract is not PASS")
    if architecture.get("status") != "PASS":
        errors.append("architecture contract is not PASS")
    if ownership.get("status") != "PASS":
        errors.append("architecture ownership guard is not PASS")

    capability_count = int(architecture.get("service_count") or 0)
    root_capabilities = list(architecture.get("root_services") or [])
    background_capability_count = int(ownership.get("background_service_count") or 0)
    interactive_endpoint_count = int(ownership.get("interactive_service_count") or 0)
    execution_domain_count = int(terminology.get("execution_domain_count") or 0)

    if capability_count != int(terminology.get("capability_count") or 0):
        errors.append(
            "architecture capability count alias drift: "
            f"architecture={capability_count} terminology={terminology.get('capability_count')}"
        )
    if background_capability_count != capability_count:
        errors.append(
            "background capability count drift: "
            f"background={background_capability_count} architecture={capability_count}"
        )
    if execution_domain_count <= 0:
        errors.append("execution domain count must be positive and terminology-registry owned")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "registry": "V3_CAPABILITY_TELEMETRY_V1",
        "canonical_runtime_boundary": "execution_domain",
        "execution_domain_count": execution_domain_count,
        "canonical_business_unit": "capability",
        "capability_count": capability_count,
        "root_capabilities": root_capabilities,
        "background_capability_count": background_capability_count,
        "interactive_endpoint_count": interactive_endpoint_count,
        "compatibility_aliases": {
            "service_count": architecture.get("service_count"),
            "root_services": architecture.get("root_services"),
            "background_service_count": ownership.get("background_service_count"),
            "interactive_service_count": ownership.get("interactive_service_count"),
            "total_bounded_service_count": ownership.get("total_bounded_service_count"),
        },
        "policy": {
            "canonical_telemetry_uses_capability_terminology": True,
            "legacy_service_fields_are_read_only_compatibility_aliases": True,
            "legacy_aliases_must_equal_canonical_values": True,
            "interactive_endpoint_is_not_counted_as_background_capability": True,
            "execution_domain_count_is_terminology_registry_owned": True,
        },
    }
    return result


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
