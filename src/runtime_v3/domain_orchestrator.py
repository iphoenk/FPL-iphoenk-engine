from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from src.runtime_v3 import incremental_reuse
from src.runtime_v3 import module_batch_runner
from src.runtime_v3 import orchestrator as legacy
from src.utils import DATA, ROOT, atomic_json, read_json
from src.version import ENGINE_VERSION, SCHEMA_VERSION

DOMAIN_PATH = ROOT / "config" / "runtime" / "execution_domains.json"
PERFORMANCE_PATH = DATA / "runtime_performance.json"
DOMAIN_RUNTIME_ID = "v3-domain-pipeline-v1"


def _load_domains() -> dict[str, Any]:
    payload = json.loads(DOMAIN_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_EXECUTION_DOMAINS_V1":
        raise RuntimeError("unexpected execution domain registry")
    domains = payload.get("domains")
    if not isinstance(domains, dict) or len(domains) != 7:
        raise RuntimeError("V3.26 requires exactly seven execution domains")
    return payload


def _validate_domain_coverage(domain_registry: dict[str, Any], service_registry: dict[str, Any]) -> None:
    services = set((service_registry.get("services") or {}).keys())
    seen: list[str] = []
    domains = domain_registry["domains"]
    for name, spec in domains.items():
        for dep in spec.get("depends_on") or []:
            if dep not in domains:
                raise RuntimeError(f"execution domain {name} depends on unknown domain {dep}")
        seen.extend(str(value) for value in spec.get("capabilities") or [])
    if len(seen) != len(set(seen)):
        duplicates = sorted({name for name in seen if seen.count(name) > 1})
        raise RuntimeError(f"capability assigned to multiple execution domains: {duplicates}")
    missing = sorted(services - set(seen))
    extra = sorted(set(seen) - services)
    if missing or extra:
        raise RuntimeError(f"execution domain coverage drift: missing={missing} extra={extra}")


def _profile(mode: str, deep_stats: bool, explicit: str | None) -> tuple[str, dict[str, Any]]:
    profiles = legacy._load_profiles().get("profiles") or {}
    profile_name = str(explicit or legacy._default_profile(mode, deep_stats))
    profile_cfg = profiles.get(profile_name)
    if not isinstance(profile_cfg, dict):
        raise RuntimeError(f"unknown execution profile: {profile_name}")
    return profile_name, profile_cfg


def _execution_spec(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    shared_spec = dict(spec)
    shared_spec["isolated"] = False
    batches = module_batch_runner._registry().get("batches") or {}
    if name in batches:
        shared_spec["commands"] = [{
            "module": "src.runtime_v3.module_batch_runner",
            "args": ["--batch", name, "{stats}", "{deep_stats}", "--mode", "{mode}"],
        }]
        shared_spec["single_process_module_batch"] = True
    return shared_spec


def _run_capability(
    name: str,
    spec: dict[str, Any],
    *,
    cache_dir: Path,
    context: dict[str, str],
    timeout: int,
    profile_name: str,
    profile_cfg: dict[str, Any],
) -> dict[str, Any]:
    reuse_active = incremental_reuse.active(profile_name)
    reused = legacy._reuse_service(name, spec, DATA, profile_cfg)
    if reused is None and reuse_active:
        reused = incremental_reuse.try_reuse(name, spec, profile_name)
    if reused is not None:
        reused["execution_boundary"] = "DOMAIN_SHARED_CANONICAL"
        return reused

    input_fingerprint_before = incremental_reuse.fingerprint(name) if reuse_active else None
    shared_spec = _execution_spec(name, spec)
    result = legacy._run_service(
        name,
        shared_spec,
        canonical=DATA,
        services_root=DATA,
        cache_dir=cache_dir,
        context=context,
        timeout=timeout,
        submitted_at=time.perf_counter(),
    )
    if input_fingerprint_before:
        result["input_fingerprint_before"] = input_fingerprint_before
    if shared_spec.get("single_process_module_batch"):
        result["single_process_module_batch"] = True
    if result["status"] != "SUCCESS":
        return result

    validation_started = time.perf_counter()
    try:
        result["artifact_validation"] = legacy._validate_service_outputs(name, result, shared_spec)
        result["validation_ms"] = round((time.perf_counter() - validation_started) * 1000.0, 3)
        result["promotion_ms"] = 0.0
        result["promoted_output_bytes"] = 0
        result["execution_boundary"] = "DOMAIN_SHARED_CANONICAL"
        if reuse_active:
            incremental_reuse.record(name, profile_name, input_fingerprint_before)
        return result
    except Exception as exc:
        result["status"] = "FAILED"
        result["failure_stage"] = "artifact_validation"
        result["validation_ms"] = round((time.perf_counter() - validation_started) * 1000.0, 3)
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def run(mode: str = "daily", stats: bool = True, deep_stats: bool = False, profile: str | None = None) -> dict[str, Any]:
    service_registry = legacy._load_registry()
    legacy._validate_dag(service_registry)
    domain_registry = _load_domains()
    _validate_domain_coverage(domain_registry, service_registry)
    profile_name, profile_cfg = _profile(mode, deep_stats, profile)

    services = service_registry["services"]
    runtime = service_registry.get("runtime") or {}
    timeout = max(1, int(runtime.get("service_timeout_seconds") or 1))
    cache_ttl = max(1, int(runtime.get("http_cache_ttl_seconds") or 1))
    context = {
        "mode": mode,
        "stats": "--stats" if stats else "--no-stats",
        "deep_stats": "--deep-stats" if deep_stats else "",
        "http_cache_ttl": str(cache_ttl),
        "profile": profile_name,
    }

    wall_started = time.perf_counter()
    capability_results: dict[str, dict[str, Any]] = {}
    domain_results: dict[str, dict[str, Any]] = {}
    completed_capabilities: set[str] = set()
    completed_domains: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="fpl-v3-domain-") as tmp:
        temp_root = Path(tmp)
        configured_cache = os.getenv("FPL_RUNTIME_CACHE_DIR", "").strip()
        cache_dir = Path(configured_cache).expanduser().resolve() / "official" if configured_cache else temp_root / "official-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        pending = list(domain_registry["domains"].keys())
        while pending:
            progressed = False
            for domain_name in list(pending):
                domain_spec = domain_registry["domains"][domain_name]
                if not set(domain_spec.get("depends_on") or []).issubset(completed_domains):
                    continue
                domain_started = time.perf_counter()
                domain_capabilities: list[str] = []
                for capability in domain_spec.get("capabilities") or []:
                    capability = str(capability)
                    spec = services[capability]
                    missing_deps = sorted(set(str(dep) for dep in spec.get("depends_on") or []) - completed_capabilities)
                    if missing_deps:
                        raise RuntimeError(
                            f"domain ordering violates capability dependency: {domain_name}:{capability} missing={missing_deps}"
                        )
                    result = _run_capability(
                        capability,
                        spec,
                        cache_dir=cache_dir,
                        context=context,
                        timeout=timeout,
                        profile_name=profile_name,
                        profile_cfg=profile_cfg,
                    )
                    result["execution_domain"] = domain_name
                    capability_results[capability] = result
                    domain_capabilities.append(capability)
                    if result["status"] in {"SUCCESS", "REUSED"}:
                        completed_capabilities.add(capability)
                        continue
                    if bool(spec.get("critical", True)):
                        raise RuntimeError(f"critical capability {capability} failed in {domain_name}: {result.get('error')}")
                    result["discarded_stale_outputs"] = legacy._clear_failed_service_outputs(DATA, spec)
                    completed_capabilities.add(capability)

                domain_results[domain_name] = {
                    "status": "SUCCESS",
                    "elapsed_ms": round((time.perf_counter() - domain_started) * 1000.0, 3),
                    "capabilities": domain_capabilities,
                }
                completed_domains.add(domain_name)
                pending.remove(domain_name)
                progressed = True
            if not progressed:
                raise RuntimeError(f"execution domain DAG stalled: {pending}")

        total_ms = (time.perf_counter() - wall_started) * 1000.0
        performance = legacy._write_runtime_metadata(
            service_registry,
            capability_results,
            total_ms,
            cache_dir,
            profile_name,
            profile_cfg,
            temp_root,
        )
        reuse_registry = incremental_reuse._registry().get("services") or {}
        reuse_active = incremental_reuse.active(profile_name)
        performance["content_addressed_reuse"] = {
            "enabled": reuse_active,
            "inactive_reason": incremental_reuse.inactive_reason(profile_name),
            "reused_services": sorted(
                name for name, row in capability_results.items()
                if row.get("reuse_mode") == "CONTENT_ADDRESSED"
            ),
            "diagnostics": {
                name: incremental_reuse.diagnose(name, profile_name)
                for name in reuse_registry
            },
        }
        performance["module_batching"] = {
            "registry": "V3_MODULE_BATCHES_V1",
            "batched_services": sorted(
                name for name, row in capability_results.items()
                if row.get("single_process_module_batch") is True
            ),
        }
        performance["runtime_id"] = DOMAIN_RUNTIME_ID
        performance["architecture"] = domain_registry["architecture"]
        performance["execution_domain_count"] = len(domain_results)
        performance["capability_owner_count"] = len(capability_results)
        performance["execution_domains"] = domain_results
        performance["cross_capability_copy_promotion"] = False
        performance["ephemeral_artifacts_removed"] = legacy._cleanup_ephemeral(service_registry, DATA)
        atomic_json(PERFORMANCE_PATH, performance)

        latest = read_json(DATA / "latest.json", {})
        runtime_meta = latest.setdefault("runtime_architecture", {})
        runtime_meta.update({
            "id": DOMAIN_RUNTIME_ID,
            "architecture": domain_registry["architecture"],
            "service_count": len(domain_results),
            "execution_domain_count": len(domain_results),
            "capability_owner_count": len(capability_results),
            "shared_canonical_domain_workspace": True,
            "cross_capability_copy_promotion": False,
            "total_wall_ms": round(total_ms, 3),
        })
        atomic_json(DATA / "latest.json", latest)

    print(json.dumps({
        "runtime": DOMAIN_RUNTIME_ID,
        "architecture": domain_registry["architecture"],
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "execution_profile": profile_name,
        "total_wall_ms": performance["total_wall_ms"],
        "target_wall_ms": performance.get("target_wall_ms"),
        "within_target_slo": performance.get("within_target_slo"),
        "within_target_budget": performance.get("within_target_budget"),
        "execution_domain_count": len(domain_results),
        "capability_owner_count": len(capability_results),
        "domains": domain_results,
        "content_addressed_reuse": performance.get("content_addressed_reuse"),
        "module_batching": performance.get("module_batching"),
        "resources": performance.get("resources"),
    }, ensure_ascii=False))
    return performance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "deadline", "live"], default="daily")
    parser.add_argument("--stats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--deep-stats", action="store_true")
    parser.add_argument("--profile", choices=["fast_decision", "live", "full_refresh", "deep_stats"])
    args = parser.parse_args()
    run(mode=args.mode, stats=args.stats, deep_stats=args.deep_stats, profile=args.profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
