from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils import ROOT

STATUS_PATH = ROOT / "IMPLEMENTATION_STATUS.json"
SERVICE_PATH = ROOT / "config" / "v3_service_registry.json"
DOMAIN_PATH = ROOT / "config" / "runtime" / "execution_domains.json"
OWNERSHIP_PATH = ROOT / "config" / "v3_architecture_ownership_registry.json"
SLO_PATH = ROOT / "config" / "runtime" / "performance_slo.json"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"governance input must be a JSON object: {path}")
    return payload


def _module_path(module: str) -> Path:
    return ROOT / (module.replace(".", "/") + ".py")


def run() -> dict[str, Any]:
    errors: list[str] = []
    status = _load(STATUS_PATH)
    service = _load(SERVICE_PATH)
    domains = _load(DOMAIN_PATH)
    ownership = _load(OWNERSHIP_PATH)
    slo = _load(SLO_PATH)

    services = service.get("services") if isinstance(service.get("services"), dict) else {}
    capability_count = len(services)
    domain_count = int(domains.get("domain_count") or 0)
    phase_count = int(domains.get("phase_count") or 0)
    if capability_count <= 0 or domain_count <= 0 or phase_count <= 0:
        errors.append("canonical topology registries are empty or invalid")

    production = status.get("production_acceptance") if isinstance(status.get("production_acceptance"), dict) else {}
    current = production.get("current_operational_evidence") if isinstance(production.get("current_operational_evidence"), dict) else {}
    architecture = status.get("architecture") if isinstance(status.get("architecture"), dict) else {}
    expected_current = {
        "execution_domain_count": domain_count,
        "execution_phase_count": phase_count,
        "background_capability_count": capability_count,
    }
    for key, expected in expected_current.items():
        if int(current.get(key) or 0) != expected:
            errors.append(f"current topology drift: {key}={current.get(key)} expected={expected}")
    for key, expected in (
        ("execution_domain_count", domain_count),
        ("execution_phase_count", phase_count),
        ("active_background_capability_count", capability_count),
        ("latest_production_evidence_domain_count", domain_count),
    ):
        if int(architecture.get(key) or 0) != expected:
            errors.append(f"architecture topology drift: {key}={architecture.get(key)} expected={expected}")
    if current.get("topology_authority") != "config/runtime/execution_domains.json + config/v3_service_registry.json":
        errors.append("current topology authority pointer drift")
    if "HISTORICAL_REFERENCE_NOT_CURRENT_AUTHORITY" not in str(current.get("runtime_metrics_semantics") or ""):
        errors.append("static runtime metrics must be labelled historical reference, not current authority")
    for block in ("release_closeout", "architecture_closeout"):
        payload = status.get(block) if isinstance(status.get(block), dict) else {}
        if payload.get("topology_semantics") != "HISTORICAL_AT_TIME":
            errors.append(f"{block} topology must be explicitly HISTORICAL_AT_TIME")

    retired = {str(value) for value in ownership.get("legacy_business_implementations_to_retire") or []}
    if not retired:
        errors.append("retired business implementation tombstone set is missing")
    existing_retired = sorted(module for module in retired if _module_path(module).is_file())
    if existing_retired:
        errors.append(f"retired duplicate business implementations still exist: {existing_retired}")
    active_modules = {
        str(command.get("module"))
        for spec in services.values()
        if isinstance(spec, dict)
        for command in spec.get("commands") or []
        if isinstance(command, dict) and command.get("module")
    }
    reactivated = sorted(retired & active_modules)
    if reactivated:
        errors.append(f"retired business implementations reactivated by service registry: {reactivated}")

    resource = slo.get("resource_observability") if isinstance(slo.get("resource_observability"), dict) else {}
    policy = slo.get("policy") if isinstance(slo.get("policy"), dict) else {}
    if resource.get("state") != "BASELINE_COLLECTION_GOVERNED":
        errors.append("resource observability must be in governed baseline-collection state")
    if resource.get("baseline_authority") != "runtime-data/data/runtime_manifest.json":
        errors.append("resource baseline authority pointer drift")
    if resource.get("hard_limit_activation") != "REQUIRES_MULTI_RUN_PRODUCTION_BASELINE":
        errors.append("resource hard-limit activation must require genuine multi-run production evidence")
    if resource.get("false_precision_forbidden") is not True:
        errors.append("resource false-precision guard disabled")
    if resource.get("operational_health_effect") != "NON_BLOCKING_WHILE_BASELINE_GOVERNANCE_IS_VALID":
        errors.append("resource baseline collection must have explicit governed non-blocking semantics")
    if resource.get("memory_enforcement") != "OBSERVE_ONLY" or resource.get("storage_enforcement") != "OBSERVE_ONLY":
        errors.append("resource enforcement changed without governed production baseline promotion")
    if policy.get("resource_observe_only_is_governed_non_blocking_not_missing_control") is not True:
        errors.append("resource observe-only governance policy disabled")
    if policy.get("resource_hard_limits_require_multi_run_production_evidence") is not True:
        errors.append("resource hard-limit evidence policy disabled")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "canonical_topology": {
            "execution_domains": domain_count,
            "execution_phases": phase_count,
            "background_capabilities": capability_count,
        },
        "retired_business_implementations": sorted(retired),
        "retired_modules_absent": not existing_retired,
        "resource_governance_state": resource.get("state"),
        "resource_limits_evidence_gated": resource.get("hard_limit_activation") == "REQUIRES_MULTI_RUN_PRODUCTION_BASELINE",
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
