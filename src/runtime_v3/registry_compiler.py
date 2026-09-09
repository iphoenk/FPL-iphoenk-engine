from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.utils import ROOT, atomic_json

DOMAIN_PATH = ROOT / "config" / "runtime" / "execution_domains.json"
CAPABILITY_PATH = ROOT / "config" / "v3_service_registry.json"

DOMAIN_REGISTRY_ID = "V3_EXECUTION_DOMAINS_V2"
COMPILED_REGISTRY_ID = "V3_COMPILED_EXECUTION_PLAN_V1"
DERIVED_BATCH_REGISTRY_ID = "V3_MODULE_BATCHES_DERIVED_V2"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"registry root must be an object: {path}")
    return payload


def load_domain_registry() -> dict[str, Any]:
    payload = _read_json(DOMAIN_PATH)
    if payload.get("registry") != DOMAIN_REGISTRY_ID:
        raise RuntimeError(f"unexpected execution domain registry: {payload.get('registry')}")
    return payload


def load_capability_registry() -> dict[str, Any]:
    payload = _read_json(CAPABILITY_PATH)
    services = payload.get("services")
    if not isinstance(services, dict) or not services:
        raise RuntimeError("capability registry contains no services")
    return payload


def _module_path(module: str) -> Path:
    return ROOT / (module.replace(".", "/") + ".py")


def _topological_waves(order: list[str], dependencies: dict[str, set[str]], label: str) -> list[list[str]]:
    remaining = set(order)
    completed: set[str] = set()
    waves: list[list[str]] = []
    while remaining:
        ready = [
            name
            for name in order
            if name in remaining and dependencies[name].issubset(completed)
        ]
        if not ready:
            raise RuntimeError(f"{label} dependency cycle or unresolved dependency: {sorted(remaining)}")
        waves.append(ready)
        completed.update(ready)
        remaining.difference_update(ready)
    return waves


def _ancestors(name: str, dependencies: dict[str, set[str]]) -> set[str]:
    found: set[str] = set()
    pending = list(dependencies[name])
    while pending:
        dependency = pending.pop()
        if dependency in found:
            continue
        found.add(dependency)
        pending.extend(dependencies[dependency])
    return found


def derived_batches(services: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Derive in-process module batches from the canonical capability command contract."""
    return {
        name: list(spec.get("commands") or [])
        for name, spec in services.items()
        if len(spec.get("commands") or []) > 1
    }


def derived_batch_registry(service_registry: dict[str, Any] | None = None) -> dict[str, Any]:
    service_registry = service_registry or load_capability_registry()
    services = service_registry["services"]
    return {
        "schema_version": 2,
        "registry": DERIVED_BATCH_REGISTRY_ID,
        "generated_from": "config/v3_service_registry.json#services.*.commands",
        "policy": {
            "human_maintained_batch_registry": False,
            "preserve_declared_order": True,
            "single_process_per_batch": True,
            "same_module_entrypoints": True,
            "same_artifact_contracts": True,
            "fail_closed_on_nonzero_module_exit": True,
            "no_business_logic_in_batch_runner": True,
        },
        "batches": derived_batches(services),
    }


def _artifact_maps(services: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    producers: dict[str, list[str]] = {}
    consumers: dict[str, list[str]] = {}
    for name, spec in services.items():
        for artifact in spec.get("artifacts") or []:
            producers.setdefault(str(artifact), []).append(name)
        for artifact in spec.get("inputs") or []:
            consumers.setdefault(str(artifact), []).append(name)
    return (
        {key: sorted(value) for key, value in sorted(producers.items())},
        {key: sorted(value) for key, value in sorted(consumers.items())},
    )


def compile_runtime_plan(
    domain_registry: dict[str, Any] | None = None,
    service_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile and fail-closed validate the V3 runtime control plane."""
    domain_registry = domain_registry or load_domain_registry()
    service_registry = service_registry or load_capability_registry()

    domains = domain_registry.get("domains")
    phases = domain_registry.get("canonical_phases")
    services = service_registry.get("services")
    if not isinstance(domains, dict) or not isinstance(phases, dict) or not isinstance(services, dict):
        raise RuntimeError("runtime registries are structurally invalid")

    if len(domains) != int(domain_registry.get("domain_count") or 0):
        raise RuntimeError("execution domain count does not match registry contract")
    if len(phases) != int(domain_registry.get("phase_count") or 0):
        raise RuntimeError("execution phase count does not match registry contract")

    phase_order = [str(value) for value in phases.keys()]
    domain_order = [
        str(domain)
        for phase in phase_order
        for domain in phases.get(phase) or []
    ]
    if len(domain_order) != len(set(domain_order)) or set(domain_order) != set(domains):
        raise RuntimeError("canonical phases must cover every execution domain exactly once")
    if domain_order != list(domains):
        raise RuntimeError(
            f"execution domain declaration order must match canonical phase order: {list(domains)} != {domain_order}"
        )

    owner: dict[str, str] = {}
    for domain_name, domain_spec in domains.items():
        if domain_spec.get("phase") not in phases:
            raise RuntimeError(f"execution domain {domain_name} has unknown phase {domain_spec.get('phase')}")
        if domain_name not in phases[domain_spec["phase"]]:
            raise RuntimeError(f"execution domain phase membership drift: {domain_name}")
        for capability in domain_spec.get("capabilities") or []:
            capability = str(capability)
            if capability in owner:
                raise RuntimeError(f"capability assigned to multiple execution domains: {capability}")
            owner[capability] = domain_name

    missing = sorted(set(services) - set(owner))
    extra = sorted(set(owner) - set(services))
    if missing or extra:
        raise RuntimeError(f"execution domain coverage drift: missing={missing} extra={extra}")

    domain_dependencies: dict[str, set[str]] = {}
    for domain_name, domain_spec in domains.items():
        dependencies = {str(value) for value in domain_spec.get("depends_on") or []}
        unknown = sorted(dependencies - set(domains))
        if unknown:
            raise RuntimeError(f"execution domain {domain_name} depends on unknown domains: {unknown}")
        domain_dependencies[domain_name] = dependencies
    domain_waves = _topological_waves(domain_order, domain_dependencies, "domain")

    capability_dependencies: dict[str, set[str]] = {}
    for capability, spec in services.items():
        dependencies = {str(value) for value in spec.get("depends_on") or []}
        unknown = sorted(dependencies - set(services))
        if unknown:
            raise RuntimeError(f"capability {capability} depends on unknown capabilities: {unknown}")
        capability_dependencies[capability] = dependencies
        commands = spec.get("commands") or []
        if not isinstance(commands, list) or not commands:
            raise RuntimeError(f"capability {capability} has no executable commands")
        for command in commands:
            module = str(command.get("module") or "").strip()
            if not module:
                raise RuntimeError(f"capability {capability} contains a module-less command")
            if not _module_path(module).is_file():
                raise RuntimeError(f"capability command module missing: {capability}:{module}")

    _topological_waves(list(services), capability_dependencies, "capability")

    for domain_name, domain_spec in domains.items():
        capabilities = [str(value) for value in domain_spec.get("capabilities") or []]
        position = {capability: index for index, capability in enumerate(capabilities)}
        upstream_domains = _ancestors(domain_name, domain_dependencies)
        for capability in capabilities:
            for dependency in capability_dependencies[capability]:
                dependency_owner = owner[dependency]
                if dependency_owner == domain_name:
                    if position[dependency] >= position[capability]:
                        raise RuntimeError(
                            f"internal capability order violation: {domain_name}:{capability} requires {dependency}"
                        )
                elif dependency_owner not in upstream_domains:
                    raise RuntimeError(
                        "execution domain dependency does not cover capability dependency: "
                        f"{domain_name}:{capability} requires {dependency_owner}:{dependency}"
                    )

    producers, consumers = _artifact_maps(services)
    actual_multi_writers = {
        artifact: writers
        for artifact, writers in producers.items()
        if len(writers) > 1
    }
    declared_writer_exceptions = domain_registry.get("artifact_writer_exceptions") or {}
    if not isinstance(declared_writer_exceptions, dict):
        raise RuntimeError("artifact_writer_exceptions must be an object")
    normalized_exceptions = {
        str(artifact): sorted(str(value) for value in (spec.get("writers") or []))
        for artifact, spec in declared_writer_exceptions.items()
    }
    if set(actual_multi_writers) != set(normalized_exceptions):
        missing_exceptions = sorted(set(actual_multi_writers) - set(normalized_exceptions))
        stale_exceptions = sorted(set(normalized_exceptions) - set(actual_multi_writers))
        raise RuntimeError(
            f"multi-writer artifact exception drift: missing={missing_exceptions} stale={stale_exceptions}"
        )
    for artifact, writers in actual_multi_writers.items():
        if writers != normalized_exceptions[artifact]:
            raise RuntimeError(
                f"multi-writer artifact writer drift for {artifact}: "
                f"actual={writers} declared={normalized_exceptions[artifact]}"
            )

    unresolved_inputs = {
        artifact: readers
        for artifact, readers in consumers.items()
        if artifact not in producers
    }
    batch_registry = derived_batch_registry(service_registry)

    plan: dict[str, Any] = {
        "schema_version": 1,
        "registry": COMPILED_REGISTRY_ID,
        "architecture": domain_registry.get("architecture"),
        "source_registries": {
            "domains": DOMAIN_REGISTRY_ID,
            "capabilities": "config/v3_service_registry.json",
            "module_batches": DERIVED_BATCH_REGISTRY_ID,
        },
        "phase_count": len(phases),
        "domain_count": len(domains),
        "capability_count": len(services),
        "phase_order": phase_order,
        "phases": phases,
        "domain_order": domain_order,
        "domains": domains,
        "domain_waves": domain_waves,
        "capability_owner": {key: owner[key] for key in services},
        "capability_dependencies": {
            key: sorted(capability_dependencies[key])
            for key in services
        },
        "batch_capabilities": list(batch_registry["batches"]),
        "artifact_producers": producers,
        "artifact_consumers": consumers,
        "multi_writer_artifacts": actual_multi_writers,
        "unresolved_external_or_historical_inputs": unresolved_inputs,
        "policy": {
            "execution_truth": "execution_domains + capability_contracts compiled once",
            "module_batches_are_derived": True,
            "human_maintained_module_batch_registry": False,
            "domain_dag_fail_closed": True,
            "capability_dag_fail_closed": True,
            "capability_coverage_exactly_once": True,
            "multi_writer_artifacts_must_be_explicit": True,
        },
    }
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    plan["plan_sha256"] = hashlib.sha256(canonical).hexdigest()
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    plan = compile_runtime_plan()
    if args.output:
        output = Path(args.output)
        atomic_json(output, plan)
    print(json.dumps({
        "registry": plan["registry"],
        "plan_sha256": plan["plan_sha256"],
        "phase_count": plan["phase_count"],
        "domain_count": plan["domain_count"],
        "capability_count": plan["capability_count"],
        "domain_waves": plan["domain_waves"],
        "batch_capabilities": plan["batch_capabilities"],
        "multi_writer_artifacts": plan["multi_writer_artifacts"],
        "unresolved_input_count": len(plan["unresolved_external_or_historical_inputs"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
