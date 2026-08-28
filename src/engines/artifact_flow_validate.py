from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from src.utils import ROOT

SERVICE_REGISTRY = ROOT / "config" / "v3_service_registry.json"
FLOW_REGISTRY = ROOT / "config" / "runtime" / "artifact_flow_registry.json"


def _load(path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run() -> dict[str, Any]:
    services_payload = _load(SERVICE_REGISTRY)
    flow = _load(FLOW_REGISTRY)
    services = services_payload.get("services") or {}
    service_ids = set(services)
    passthrough = {
        str(service): {str(name) for name in names or []}
        for service, names in (flow.get("fan_in_passthrough") or {}).items()
    }
    chains = flow.get("staged_mutation_chains") or {}
    final_owners = flow.get("canonical_final_owners") or {}
    errors: list[str] = []

    if flow.get("registry") != "V3_ARTIFACT_FLOW_OWNERSHIP_V1":
        errors.append("artifact flow registry id drift")

    declared: dict[str, list[str]] = defaultdict(list)
    for service_name, spec in services.items():
        ignored = passthrough.get(service_name, set())
        unknown_passthrough = ignored - {str(name) for name in spec.get("artifacts") or []}
        if unknown_passthrough:
            errors.append(f"{service_name} passthrough names not declared by service: {sorted(unknown_passthrough)}")
        for artifact in spec.get("artifacts") or []:
            name = str(artifact)
            if name in ignored:
                continue
            declared[name].append(service_name)

    actual_multi = {name: writers for name, writers in declared.items() if len(writers) > 1}
    for artifact, writers in actual_multi.items():
        chain = chains.get(artifact)
        if not isinstance(chain, dict):
            errors.append(f"undeclared multi-writer artifact: {artifact} <- {writers}")
            continue
        expected = [str(value) for value in chain.get("writers") or []]
        if writers != expected:
            errors.append(f"artifact mutation order drift for {artifact}: actual={writers} expected={expected}")
        final_owner = str(chain.get("final_owner") or "")
        if not expected or final_owner != expected[-1]:
            errors.append(f"artifact chain final owner must be last writer: {artifact}")
        if str(final_owners.get(artifact) or "") != final_owner:
            errors.append(f"canonical final owner mismatch for {artifact}")

    unused_chains = sorted(set(chains) - set(actual_multi))
    if unused_chains:
        errors.append(f"staged mutation chains declared without actual multi-writer flow: {unused_chains}")

    for artifact, owner in final_owners.items():
        owner = str(owner)
        if owner not in service_ids:
            errors.append(f"canonical final owner is not a service: {artifact} -> {owner}")
        writers = declared.get(str(artifact), [])
        if writers and owner not in writers:
            errors.append(f"canonical owner does not declare artifact: {artifact} owner={owner} writers={writers}")
        if len(writers) == 1 and writers[0] != owner:
            errors.append(f"single-writer artifact owner mismatch: {artifact} writer={writers[0]} owner={owner}")

    policy = flow.get("policy") or {}
    for key in (
        "one_final_owner_per_artifact",
        "fan_in_passthrough_is_not_ownership",
        "staged_mutation_requires_explicit_order",
        "undeclared_multi_writer_is_forbidden",
    ):
        if policy.get(key) is not True:
            errors.append(f"artifact flow policy missing {key}=true")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "declared_artifacts": len(declared),
        "multi_writer_artifacts": actual_multi,
        "declared_mutation_chains": sorted(chains),
        "fan_in_passthrough": {key: sorted(value) for key, value in passthrough.items()},
        "policy": {
            "undeclared_multi_writer_count": sum(1 for name in actual_multi if name not in chains),
            "all_multi_writer_flows_explicit": all(name in chains for name in actual_multi),
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
