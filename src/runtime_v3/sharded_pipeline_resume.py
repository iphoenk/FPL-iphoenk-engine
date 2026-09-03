from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.runtime_v3 import domain_process_runner, registry_compiler
from src.utils import ROOT

SHARD_POLICY_PATH = ROOT / "config" / "runtime" / "package_optimizer_sharding.json"


def _policy() -> dict[str, Any]:
    payload = json.loads(SHARD_POLICY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_PACKAGE_OPTIMIZER_SHARDING_V1":
        raise RuntimeError("unexpected package optimizer sharding policy")
    return payload


def _resume_domain(policy: dict[str, Any]) -> str:
    name = str((policy.get("workflow") or {}).get("resume_from_domain") or "")
    if not name:
        raise RuntimeError("sharded optimizer resume boundary missing")
    return name


def _resume_waves(plan: dict[str, Any], start: str) -> tuple[list[list[str]], list[list[str]]]:
    waves = [
        [str(name) for name in wave]
        for wave in plan.get("domain_waves") or []
        if isinstance(wave, list) and wave
    ]
    if not waves:
        raise RuntimeError("compiled runtime plan contains no topological domain waves")
    matches = [index for index, wave in enumerate(waves) if start in wave]
    if len(matches) != 1:
        raise RuntimeError(f"sharded optimizer resume boundary is not uniquely present in compiled domain waves: {start}")
    start_wave = matches[0]
    return waves[:start_wave], waves[start_wave:]


def resume(*, mode: str = "daily", stats: bool = True, deep_stats: bool = False, profile: str = "exhaustive_precompute") -> dict[str, Any]:
    policy = _policy()
    domain_registry = registry_compiler.load_domain_registry()
    service_registry = registry_compiler.load_capability_registry()
    plan = registry_compiler.compile_runtime_plan(
        domain_registry=domain_registry,
        service_registry=service_registry,
    )
    domain_order = [str(name) for name in plan.get("domain_order") or []]
    start = _resume_domain(policy)
    if start not in domain_order:
        raise RuntimeError(f"sharded optimizer resume boundary is not a registered execution domain: {start}")

    precompleted_waves, selected_waves = _resume_waves(plan, start)
    precompleted_order = [name for wave in precompleted_waves for name in wave]
    domains = domain_registry.get("domains") or {}
    services = service_registry.get("services") or {}
    completed_domains = set(precompleted_order)
    completed_capabilities = {
        str(capability)
        for domain_name in precompleted_order
        for capability in (domains.get(domain_name) or {}).get("capabilities") or []
    }
    results: dict[str, Any] = {}
    executed_waves: list[list[str]] = []

    for wave in selected_waves:
        wave_domains = set(wave)
        # Every dependency of a topological wave must already be completed before
        # that wave begins. Siblings in one wave are intentionally independent.
        for domain_name in wave:
            domain = domains.get(domain_name) or {}
            dependencies = {str(dep) for dep in domain.get("depends_on") or []}
            missing_domains = sorted(dependencies - completed_domains)
            if missing_domains:
                raise RuntimeError(f"sharded resume domain dependency not satisfied: {domain_name} missing={missing_domains}")
            capabilities = [str(name) for name in domain.get("capabilities") or []]
            domain_set = set(capabilities)
            for capability in capabilities:
                spec = services.get(capability) or {}
                external = {str(dep) for dep in spec.get("depends_on") or []} - domain_set
                external_owners = {
                    str(plan.get("capability_owner", {}).get(dep) or "")
                    for dep in external
                }
                if external_owners & wave_domains:
                    raise RuntimeError(
                        f"compiled domain wave contains an external capability dependency inside the same wave: {domain_name}:{capability}"
                    )
                missing_capabilities = sorted(external - completed_capabilities)
                if missing_capabilities:
                    raise RuntimeError(
                        f"sharded resume capability dependency not satisfied: {domain_name}:{capability} missing={missing_capabilities}"
                    )

        completed_this_wave: list[tuple[str, list[str]]] = []
        for domain_name in wave:
            capabilities = [str(name) for name in (domains.get(domain_name) or {}).get("capabilities") or []]
            payload = domain_process_runner.run_domain(domain_name, mode, stats, deep_stats, profile)
            if payload.get("status") != "SUCCESS":
                raise RuntimeError(f"sharded resume domain failed: {domain_name}")
            results[domain_name] = payload
            completed_this_wave.append((domain_name, capabilities))

        for domain_name, capabilities in completed_this_wave:
            completed_domains.add(domain_name)
            completed_capabilities.update(capabilities)
        executed_waves.append(list(wave))

    return {
        "status": "SUCCESS",
        "registry": policy["registry"],
        "resume_from_domain": start,
        "precompleted_domains": precompleted_order,
        "executed_domains": list(results),
        "executed_domain_waves": executed_waves,
        "profile": profile,
        "mode": mode,
        "results": results,
        "governance": {
            "domain_order_from_compiled_registry": True,
            "domain_waves_from_compiled_registry": True,
            "resume_boundary_expands_to_complete_topological_wave": True,
            "downstream_business_modules_not_hardcoded": True,
            "capability_dependencies_checked": True,
            "business_authority_unchanged": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume V3 domain DAG after sharded package optimizer fan-in")
    parser.add_argument("--mode", choices=["daily", "deadline", "live"], default="daily")
    parser.add_argument("--stats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--deep-stats", action="store_true")
    parser.add_argument("--profile", default=str((_policy().get("workflow") or {}).get("authority_profile") or "exhaustive_precompute"))
    args = parser.parse_args()
    result = resume(mode=args.mode, stats=args.stats, deep_stats=args.deep_stats, profile=args.profile)
    print(json.dumps({
        "status": result["status"],
        "resume_from_domain": result["resume_from_domain"],
        "executed_domains": result["executed_domains"],
        "executed_domain_waves": result["executed_domain_waves"],
        "profile": result["profile"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
