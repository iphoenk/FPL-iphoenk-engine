from __future__ import annotations

import json
from pathlib import Path

from src.utils import ROOT

TERMINOLOGY_PATH = ROOT / "config" / "runtime" / "capability_terminology.json"
DOMAIN_PATH = ROOT / "config" / "runtime" / "execution_domains.json"
LEGACY_CONTRACT_PATH = ROOT / "config" / "v3_service_registry.json"


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"registry root must be an object: {path}")
    return payload


def run() -> dict:
    errors: list[str] = []
    terminology = _load(TERMINOLOGY_PATH)
    domains = _load(DOMAIN_PATH)
    legacy = _load(LEGACY_CONTRACT_PATH)

    if terminology.get("registry") != "V3_CAPABILITY_TERMINOLOGY_V1":
        errors.append("unexpected capability terminology registry")
    if terminology.get("canonical_runtime_boundary") != "execution_domain":
        errors.append("execution_domain must be the canonical runtime boundary")
    if terminology.get("canonical_business_unit") != "capability":
        errors.append("capability must be the canonical business unit")

    contract_source = terminology.get("contract_source") or {}
    if contract_source.get("path") != "config/v3_service_registry.json":
        errors.append("legacy capability contract path drift")
    if contract_source.get("collection_key") != "services":
        errors.append("legacy capability collection key drift")
    if contract_source.get("status") != "LEGACY_COMPATIBILITY_ALIAS":
        errors.append("legacy services collection must be marked compatibility-only")
    if contract_source.get("canonical_semantics") != "capabilities":
        errors.append("legacy services collection must have capability semantics")

    policies = terminology.get("policy") or {}
    for key in (
        "services_key_is_compatibility_only",
        "capabilities_are_not_processes",
        "execution_domains_are_process_boundaries",
        "capability_ownership_is_preserved",
        "legacy_filename_does_not_define_runtime_topology",
        "new_runtime_telemetry_must_use_capability_terminology",
        "big_bang_registry_rename_is_forbidden_without_migration_proof",
    ):
        if policies.get(key) is not True:
            errors.append(f"terminology policy missing {key}=true")

    capabilities = legacy.get("services") or {}
    if not isinstance(capabilities, dict) or not capabilities:
        errors.append("legacy contract catalog has no capabilities")
        capabilities = {}

    declared_domains = domains.get("domains") or {}
    assignments = [
        str(capability)
        for spec in declared_domains.values()
        for capability in (spec.get("capabilities") or [])
    ]
    duplicate_assignments = sorted({name for name in assignments if assignments.count(name) > 1})
    if duplicate_assignments:
        errors.append(f"capabilities assigned to multiple domains: {duplicate_assignments}")

    expected_capabilities = int(terminology.get("capability_count") or 0)
    expected_domains = int(terminology.get("execution_domain_count") or 0)
    if len(capabilities) != expected_capabilities:
        errors.append(f"capability count drift: expected={expected_capabilities} actual={len(capabilities)}")
    if len(declared_domains) != expected_domains:
        errors.append(f"execution domain count drift: expected={expected_domains} actual={len(declared_domains)}")
    if set(assignments) != set(capabilities):
        errors.append(
            "capability/domain coverage drift: "
            f"missing={sorted(set(capabilities) - set(assignments))} "
            f"extra={sorted(set(assignments) - set(capabilities))}"
        )
    if len(assignments) != len(capabilities):
        errors.append(
            f"capability assignment cardinality drift: assigned={len(assignments)} declared={len(capabilities)}"
        )

    domain_policy = domains.get("policy") or {}
    if domain_policy.get("capability_registry_is_contract_catalog_not_process_count") is not True:
        errors.append("execution domain registry must declare capability catalog is not process count")
    if domain_policy.get("execution_domains_are_process_orchestration_boundaries_not_business_owners") is not True:
        errors.append("execution domain registry must own runtime process-boundary semantics")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "registry": terminology.get("registry"),
        "canonical_runtime_boundary": terminology.get("canonical_runtime_boundary"),
        "canonical_business_unit": terminology.get("canonical_business_unit"),
        "execution_domain_count": len(declared_domains),
        "capability_count": len(capabilities),
        "legacy_collection_key": contract_source.get("collection_key"),
        "legacy_collection_status": contract_source.get("status"),
    }


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
