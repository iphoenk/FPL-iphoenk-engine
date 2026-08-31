from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils import ROOT

SERVICE_REGISTRY = ROOT / "config" / "v3_service_registry.json"
DOMAIN_REGISTRY = ROOT / "config" / "runtime" / "execution_domains.json"
SLO_REGISTRY = ROOT / "config" / "runtime" / "performance_slo.json"
INSTANT_REGISTRY = ROOT / "config" / "runtime" / "instant_serving.json"
INTERACTIVE_REGISTRY = ROOT / "config" / "runtime" / "interactive_service_registry.json"
IMPLEMENTATION_STATUS = ROOT / "IMPLEMENTATION_STATUS.json"
CANONICAL_SLO_PATH = "config/runtime/performance_slo.json"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"governance registry must be an object: {path}")
    return payload


def run() -> dict[str, Any]:
    errors: list[str] = []
    services = _load(SERVICE_REGISTRY)
    domains = _load(DOMAIN_REGISTRY)
    slo = _load(SLO_REGISTRY)
    instant = _load(INSTANT_REGISTRY)
    interactive = _load(INTERACTIVE_REGISTRY)
    implementation = _load(IMPLEMENTATION_STATUS)

    service_map = services.get("services") if isinstance(services.get("services"), dict) else {}
    capability_count = len(service_map)
    domain_count = int(domains.get("domain_count") or 0)
    phase_count = int(domains.get("phase_count") or 0)

    current = ((implementation.get("production_acceptance") or {}).get("current_operational_evidence") or {})
    architecture = implementation.get("architecture") if isinstance(implementation.get("architecture"), dict) else {}
    expected_current = {
        "background_capability_count": capability_count,
        "execution_domain_count": domain_count,
        "execution_phase_count": phase_count,
    }
    for key, expected in expected_current.items():
        if int(current.get(key) or 0) != expected:
            errors.append(f"IMPLEMENTATION_STATUS current {key} drift: {current.get(key)} != {expected}")
    for key, expected in (
        ("active_background_capability_count", capability_count),
        ("execution_domain_count", domain_count),
        ("execution_phase_count", phase_count),
        ("latest_production_evidence_domain_count", domain_count),
    ):
        if int(architecture.get(key) or 0) != expected:
            errors.append(f"IMPLEMENTATION_STATUS architecture {key} drift: {architecture.get(key)} != {expected}")

    if ((implementation.get("architecture_closeout") or {}).get("topology_semantics")) != "HISTORICAL_AT_TIME":
        errors.append("historical architecture_closeout topology must be explicitly labelled HISTORICAL_AT_TIME")

    if slo.get("registry") != "RUNTIME_PERFORMANCE_SLO_V1":
        errors.append("unexpected canonical performance SLO registry")
    profiles = slo.get("profiles") if isinstance(slo.get("profiles"), dict) else {}
    instant_profile = profiles.get("instant_serving") if isinstance(profiles.get("instant_serving"), dict) else {}
    target = float(instant_profile.get("target_wall_ms") or 0)
    ceiling = float(instant_profile.get("legacy_ceiling_ms") or 0)
    if target <= 0 or ceiling <= 0 or target > ceiling:
        errors.append("invalid canonical instant_serving SLO")

    instant_perf = instant.get("performance") if isinstance(instant.get("performance"), dict) else {}
    interactive_policy = interactive.get("policy") if isinstance(interactive.get("policy"), dict) else {}
    for owner, payload, registry_key, profile_key in (
        ("instant_serving", instant_perf, "slo_registry", "slo_profile"),
        ("interactive_service_registry", interactive_policy, "performance_slo_registry", "performance_slo_profile"),
    ):
        if payload.get(registry_key) != CANONICAL_SLO_PATH:
            errors.append(f"{owner} canonical SLO registry pointer drift")
        if payload.get(profile_key) != "instant_serving":
            errors.append(f"{owner} canonical SLO profile pointer drift")

    duplicate_interactive_slo_keys = {
        "preferred_end_to_end_target_ms",
        "hard_end_to_end_ceiling_ms",
        "preferred_target_ms",
        "hard_ceiling_ms",
        "target_wall_ms",
    }
    for key in duplicate_interactive_slo_keys:
        if key in interactive_policy:
            errors.append(f"interactive policy duplicates canonical SLO number: {key}")
        if key in instant_perf:
            errors.append(f"instant serving config duplicates canonical SLO number: {key}")
    for service, spec in (interactive.get("services") or {}).items():
        if not isinstance(spec, dict):
            errors.append(f"invalid interactive service spec: {service}")
            continue
        duplicated = sorted(duplicate_interactive_slo_keys & set(spec))
        if duplicated:
            errors.append(f"interactive service {service} duplicates canonical SLO numbers: {duplicated}")

    production = implementation.get("production_acceptance") if isinstance(implementation.get("production_acceptance"), dict) else {}
    fast = profiles.get("fast_decision") if isinstance(profiles.get("fast_decision"), dict) else {}
    if production.get("canonical_performance_slo") != CANONICAL_SLO_PATH:
        errors.append("IMPLEMENTATION_STATUS canonical performance SLO pointer drift")
    if float(production.get("fast_target_ms") or 0) != float(fast.get("target_wall_ms") or 0):
        errors.append("IMPLEMENTATION_STATUS fast target projection drift")
    if float(architecture.get("instant_serving_hard_ceiling_ms") or 0) != ceiling:
        errors.append("IMPLEMENTATION_STATUS instant serving ceiling projection drift")
    if float(architecture.get("fast_slo_ms") or 0) != float(fast.get("target_wall_ms") or 0):
        errors.append("IMPLEMENTATION_STATUS fast SLO projection drift")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "canonical_topology": {
            "execution_domains": domain_count,
            "execution_phases": phase_count,
            "background_capabilities": capability_count,
        },
        "canonical_instant_slo": {
            "profile": "instant_serving",
            "target_wall_ms": target,
            "hard_ceiling_ms": ceiling,
        },
        "single_interactive_slo_authority": not any("duplicates canonical SLO" in error for error in errors),
    }


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
