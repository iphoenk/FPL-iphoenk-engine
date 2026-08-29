from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT, atomic_json

EXECUTION_REGISTRY = ROOT / "config" / "runtime" / "execution_registry.json"
IMPLEMENTATION_CATALOG = ROOT / "config" / "v3_service_registry.json"
ARTIFACT_CONTRACTS = ROOT / "config" / "runtime" / "artifact_contracts.json"
CAPABILITY_OWNERSHIP = ROOT / "config" / "runtime" / "capability_ownership.json"
DEFAULT_OUTPUT = DATA / "runtime_execution_plan.json"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"registry must be an object: {path}")
    return payload


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ancestors(services: dict[str, dict[str, Any]], service_id: str) -> set[str]:
    found: set[str] = set()
    pending = list(services[service_id].get("depends_on") or [])
    while pending:
        dependency = str(pending.pop())
        if dependency in found:
            continue
        found.add(dependency)
        pending.extend(str(value) for value in services[dependency].get("depends_on") or [])
    return found


def _compile_waves(services: dict[str, dict[str, Any]]) -> list[list[str]]:
    pending = list(services)
    completed: set[str] = set()
    waves: list[list[str]] = []
    while pending:
        ready = [
            service_id
            for service_id in pending
            if set(str(value) for value in services[service_id].get("depends_on") or []).issubset(completed)
        ]
        if not ready:
            raise RuntimeError(f"execution dependency cycle detected: {pending}")
        waves.append(ready)
        completed.update(ready)
        pending = [service_id for service_id in pending if service_id not in ready]
    return waves


def _critical_path_depth(services: dict[str, dict[str, Any]], waves: list[list[str]]) -> dict[str, Any]:
    depth: dict[str, int] = {}
    for wave in waves:
        for service_id in wave:
            deps = [str(value) for value in services[service_id].get("depends_on") or []]
            depth[service_id] = 1 + max((depth[dep] for dep in deps), default=0)
    longest = max(depth.values(), default=0)
    terminal = [service_id for service_id, value in depth.items() if value == longest]
    return {"max_dependency_depth": longest, "terminal_services": terminal, "depth_by_service": depth}


def _validate_registry_shape(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if registry.get("registry") != "V3_CANONICAL_EXECUTION_REGISTRY_V1":
        raise RuntimeError("unexpected canonical execution registry")
    services = registry.get("services")
    if not isinstance(services, dict) or not services:
        raise RuntimeError("canonical execution registry has no services")
    if len(services) != int(registry.get("service_count") or 0):
        raise RuntimeError("canonical execution service_count mismatch")
    if int(registry.get("phase_count") or 0) != 6:
        raise RuntimeError("canonical execution phase_count must remain six")
    phases = registry.get("canonical_phases") or {}
    assigned = [str(service_id) for names in phases.values() for service_id in (names or [])]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(services):
        raise RuntimeError("canonical phases must cover every coarse service exactly once")
    for service_id, spec in services.items():
        if spec.get("service_id") != service_id:
            raise RuntimeError(f"service_id mismatch: {service_id}")
        if spec.get("entrypoint") != "src.runtime_v3.coarse_service_runner":
            raise RuntimeError(f"unsupported coarse service entrypoint: {service_id}")
        if not isinstance(spec.get("implementation_steps"), list) or not spec["implementation_steps"]:
            raise RuntimeError(f"coarse service has no implementation steps: {service_id}")
        if spec.get("isolation_policy") not in {"SHARED_CANONICAL", "ISOLATED_FAN_IN"}:
            raise RuntimeError(f"unknown isolation policy: {service_id}")
        for dep in spec.get("depends_on") or []:
            if dep not in services:
                raise RuntimeError(f"{service_id} depends on unknown coarse service {dep}")
            if dep == service_id:
                raise RuntimeError(f"{service_id} has self dependency")
    return services


def _validate_implementation_projection(
    services: dict[str, dict[str, Any]], implementation: dict[str, Any]
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    legacy_services = implementation.get("services") or {}
    owner: dict[str, str] = {}
    for coarse_id, spec in services.items():
        for step in spec.get("implementation_steps") or []:
            step = str(step)
            if step in owner:
                raise RuntimeError(f"implementation step assigned to multiple coarse services: {step}")
            if step not in legacy_services:
                raise RuntimeError(f"unknown implementation step: {coarse_id}:{step}")
            owner[step] = coarse_id
    missing = sorted(set(legacy_services) - set(owner))
    extra = sorted(set(owner) - set(legacy_services))
    if missing or extra:
        raise RuntimeError(f"implementation coverage drift: missing={missing} extra={extra}")

    for coarse_id, spec in services.items():
        upstream = _ancestors(services, coarse_id)
        for step in spec.get("implementation_steps") or []:
            for dep in legacy_services[str(step)].get("depends_on") or []:
                dep_owner = owner[str(dep)]
                if dep_owner != coarse_id and dep_owner not in upstream:
                    raise RuntimeError(
                        "coarse dependency graph does not cover implementation dependency: "
                        f"{coarse_id}:{step} requires {dep_owner}:{dep}"
                    )
    return owner, legacy_services


def _validate_declared_outputs(
    services: dict[str, dict[str, Any]], legacy_services: dict[str, dict[str, Any]]
) -> None:
    for coarse_id, spec in services.items():
        derived: set[str] = set()
        for step in spec.get("implementation_steps") or []:
            derived.update(str(value) for value in legacy_services[str(step)].get("artifacts") or [])
        declared = set(str(value) for value in spec.get("declared_outputs") or [])
        missing = sorted(derived - declared)
        if missing:
            raise RuntimeError(f"coarse service omits implementation outputs: {coarse_id}:{missing}")


def _artifact_graph(
    registry: dict[str, Any],
    services: dict[str, dict[str, Any]],
    ownership: dict[str, Any],
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    producer_map: dict[str, list[str]] = {}
    consumer_map: dict[str, list[str]] = {}
    for service_id, spec in services.items():
        for artifact in spec.get("declared_outputs") or []:
            producer_map.setdefault(str(artifact), []).append(service_id)
        for artifact in spec.get("declared_inputs") or []:
            consumer_map.setdefault(str(artifact), []).append(service_id)

    staged = ownership.get("staged_artifacts") or {}
    for artifact, producers in producer_map.items():
        if len(producers) <= 1:
            continue
        contract = staged.get(artifact) or {}
        allowed = set(str(value) for value in contract.get("allowed_writers") or [])
        if set(producers) != allowed:
            raise RuntimeError(f"undeclared duplicate artifact writers: {artifact}:{producers}")

    preexisting = set(str(value) for value in registry.get("preexisting_artifacts") or [])
    unresolved: dict[str, list[str]] = {}
    for artifact, consumers in consumer_map.items():
        if artifact not in producer_map and artifact not in preexisting:
            unresolved[artifact] = consumers
    if unresolved:
        raise RuntimeError(f"critical inputs have no producer or preexisting classification: {unresolved}")

    return (
        {key: sorted(value) for key, value in sorted(producer_map.items())},
        {key: sorted(value) for key, value in sorted(consumer_map.items())},
        {key: sorted(value) for key, value in sorted(unresolved.items())},
    )


def compile_execution_plan(*, write: bool = True, output_path: Path | None = None) -> dict[str, Any]:
    registry = _load(EXECUTION_REGISTRY)
    implementation = _load(IMPLEMENTATION_CATALOG)
    contracts = _load(ARTIFACT_CONTRACTS)
    ownership = _load(CAPABILITY_OWNERSHIP)
    services = _validate_registry_shape(registry)
    waves = _compile_waves(services)
    implementation_owner, legacy_services = _validate_implementation_projection(services, implementation)
    _validate_declared_outputs(services, legacy_services)

    runtime_owners = set(str(value) for value in ownership.get("runtime_owners") or [])
    if runtime_owners != set(services):
        raise RuntimeError("coarse capability ownership and execution registry disagree")
    for compatibility in ownership.get("compatibility_only_modules") or []:
        if str(compatibility) in services:
            raise RuntimeError(f"compatibility module became runtime owner: {compatibility}")

    producer_map, consumer_map, unresolved = _artifact_graph(registry, services, ownership)
    known_contracts = set((contracts.get("contracts") or {}).keys())
    contracted_outputs = sorted(set(producer_map) & known_contracts)

    phase_order = [str(value) for value in (registry.get("canonical_phases") or {}).keys()]
    plan = {
        "schema_version": 1,
        "registry": "V3_COMPILED_RUNTIME_EXECUTION_PLAN_V1",
        "architecture": registry.get("architecture"),
        "source_registry": str(EXECUTION_REGISTRY.relative_to(ROOT)),
        "registry_hash": _stable_hash(registry),
        "artifact_contract_hash": _stable_hash(contracts),
        "capability_ownership_hash": _stable_hash(ownership),
        "service_count": len(services),
        "implementation_step_count": len(implementation_owner),
        "phase_count": len(phase_order),
        "phases": registry.get("canonical_phases"),
        "service_order": list(services),
        "waves": waves,
        "services": services,
        "implementation_owner_map": dict(sorted(implementation_owner.items())),
        "producer_map": producer_map,
        "consumer_map": consumer_map,
        "unresolved_inputs": unresolved,
        "contracted_outputs": contracted_outputs,
        "critical_path_metadata": _critical_path_depth(services, waves),
        "module_batches_runtime_authority": False,
        "deterministic": True
    }
    plan["plan_hash"] = _stable_hash(plan)
    if write:
        atomic_json(output_path or DEFAULT_OUTPUT, plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Validate and compile in memory without writing data output")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan = compile_execution_plan(write=not args.check, output_path=args.output)
    print(json.dumps({
        "status": "PASS",
        "registry": plan["registry"],
        "service_count": plan["service_count"],
        "implementation_step_count": plan["implementation_step_count"],
        "waves": plan["waves"],
        "plan_hash": plan["plan_hash"]
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
