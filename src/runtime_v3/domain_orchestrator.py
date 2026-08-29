from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
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
_DOMAIN_RESULT_PREFIX = "V3_DOMAIN_RESULT="
_PARALLEL_ISOLATED_DOMAINS = ("MODEL", "MARKET")


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
    """Compatibility primitive retained for tests and controlled fallback paths."""
    reuse_active = incremental_reuse.active(profile_name, name)
    reuse_diagnostic_before = incremental_reuse.diagnose(name, profile_name) if name in (incremental_reuse._registry().get("services") or {}) else None
    reused = legacy._reuse_service(name, spec, DATA, profile_cfg)
    if reused is None and reuse_active:
        reused = incremental_reuse.try_reuse(name, spec, profile_name)
    if reused is not None:
        reused["execution_boundary"] = "DOMAIN_SHARED_CANONICAL"
        if reuse_diagnostic_before is not None:
            reused["reuse_diagnostic_before"] = reuse_diagnostic_before
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
    if reuse_diagnostic_before is not None:
        result["reuse_diagnostic_before"] = reuse_diagnostic_before
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


def _run_domain_process(
    domain_name: str,
    *,
    mode: str,
    stats: bool,
    deep_stats: bool,
    profile_name: str,
    cache_dir: Path,
    cache_ttl: int,
    timeout: int,
    data_dir: Path = DATA,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "src.runtime_v3.domain_process_runner",
        "--domain",
        domain_name,
        "--mode",
        mode,
        "--profile",
        profile_name,
        "--stats" if stats else "--no-stats",
    ]
    if deep_stats:
        cmd.append("--deep-stats")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["FPL_DATA_DIR"] = str(data_dir)
    env["FPL_HTTP_CACHE_DIR"] = str(cache_dir)
    env["FPL_HTTP_CACHE_TTL_SECONDS"] = str(cache_ttl)
    env["FPL_EXECUTION_PROFILE"] = profile_name
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    if proc.returncode != 0:
        raise RuntimeError(
            f"domain process {domain_name} failed rc={proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '')[-4000:]}"
        )
    marker = next(
        (line for line in reversed((proc.stdout or "").splitlines()) if line.startswith(_DOMAIN_RESULT_PREFIX)),
        None,
    )
    if marker is None:
        raise RuntimeError(f"domain process {domain_name} emitted no result marker")
    payload = json.loads(marker[len(_DOMAIN_RESULT_PREFIX):])
    if payload.get("status") != "SUCCESS":
        raise RuntimeError(f"domain process {domain_name} returned {payload.get('status')}")
    payload["process_elapsed_ms"] = elapsed_ms
    payload["process_stdout_tail"] = (proc.stdout or "")[-4000:]
    payload["process_stderr_tail"] = (proc.stderr or "")[-4000:]
    return payload


def _domain_seed_paths(capabilities: list[str], services: dict[str, Any]) -> list[str]:
    paths = {"latest.json", "incremental_reuse_state.json"}
    for capability in capabilities:
        spec = services[capability]
        paths.update(str(value) for value in spec.get("inputs") or [])
        paths.update(str(value) for value in spec.get("artifacts") or [])
    return sorted(paths)


def _seed_isolated_domain(domain_name: str, capabilities: list[str], services: dict[str, Any], temp_root: Path) -> Path:
    workspace = temp_root / f"isolated-{domain_name.lower()}"
    workspace.mkdir(parents=True, exist_ok=True)
    for relative in _domain_seed_paths(capabilities, services):
        source = DATA / relative
        if not source.is_file():
            continue
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return workspace


def _promote_isolated_domain(
    domain_name: str,
    capabilities: list[str],
    services: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    copied: list[str] = []
    copied_bytes = 0
    for capability in capabilities:
        spec = services[capability]
        for relative in spec.get("artifacts") or []:
            name = str(relative)
            source = workspace / name
            if not source.is_file():
                continue
            target = DATA / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(name)
            copied_bytes += target.stat().st_size

    canonical_latest = read_json(DATA / "latest.json", {})
    workspace_latest = read_json(workspace / "latest.json", {})
    if not isinstance(canonical_latest, dict) or not isinstance(workspace_latest, dict):
        raise RuntimeError(f"{domain_name} latest.json fan-in requires object payloads")
    canonical_files = canonical_latest.setdefault("files", {})
    workspace_files = workspace_latest.get("files") if isinstance(workspace_latest.get("files"), dict) else {}
    merged_latest_keys: list[str] = []
    merged_file_keys: list[str] = []
    for capability in capabilities:
        spec = services[capability]
        for key in spec.get("latest_keys") or []:
            key = str(key)
            if key in workspace_latest:
                canonical_latest[key] = workspace_latest[key]
                merged_latest_keys.append(key)
        for key in spec.get("latest_file_keys") or []:
            key = str(key)
            if key in workspace_files:
                canonical_files[key] = workspace_files[key]
                merged_file_keys.append(key)
    atomic_json(DATA / "latest.json", canonical_latest)

    workspace_state = read_json(workspace / "incremental_reuse_state.json", {})
    if isinstance(workspace_state, dict) and isinstance(workspace_state.get("services"), dict):
        canonical_state = read_json(DATA / "incremental_reuse_state.json", {})
        if not isinstance(canonical_state, dict):
            canonical_state = {}
        canonical_state.setdefault("schema_version", workspace_state.get("schema_version", 1))
        canonical_state.setdefault("registry", workspace_state.get("registry", "V3_INCREMENTAL_REUSE_STATE_V1"))
        canonical_services = canonical_state.setdefault("services", {})
        for capability in capabilities:
            if capability in workspace_state["services"]:
                canonical_services[capability] = workspace_state["services"][capability]
        atomic_json(DATA / "incremental_reuse_state.json", canonical_state)

    return {
        "domain": domain_name,
        "workspace_isolated": True,
        "promoted_artifacts": sorted(set(copied)),
        "promoted_bytes": copied_bytes,
        "merged_latest_keys": sorted(set(merged_latest_keys)),
        "merged_latest_file_keys": sorted(set(merged_file_keys)),
    }


def _reuse_diagnostic_summary(name: str, capability_results: dict[str, dict[str, Any]], profile_name: str) -> dict[str, Any]:
    row = capability_results.get(name) or {}
    before = row.get("reuse_diagnostic_before")
    if isinstance(before, dict):
        return {
            **before,
            "decision_time": True,
            "execution_status": row.get("status"),
            "reuse_mode": row.get("reuse_mode"),
        }
    return {
        **incremental_reuse.diagnose(name, profile_name),
        "decision_time": False,
        "execution_status": row.get("status"),
        "reuse_mode": row.get("reuse_mode"),
    }


def _accept_domain_result(
    domain_name: str,
    domain_payload: dict[str, Any],
    capabilities: list[str],
    services: dict[str, Any],
    capability_results: dict[str, dict[str, Any]],
    completed_capabilities: set[str],
    domain_results: dict[str, dict[str, Any]],
    *,
    fan_in: dict[str, Any] | None = None,
) -> None:
    results = domain_payload.get("results") or {}
    for capability in capabilities:
        result = results.get(capability)
        if not isinstance(result, dict):
            raise RuntimeError(f"domain {domain_name} omitted capability result {capability}")
        result["execution_domain"] = domain_name
        capability_results[capability] = result
        if result.get("status") not in {"SUCCESS", "REUSED"} and bool(services[capability].get("critical", True)):
            raise RuntimeError(f"critical capability {capability} failed in {domain_name}: {result.get('error')}")
        completed_capabilities.add(capability)
    domain_results[domain_name] = {
        "status": "SUCCESS",
        "elapsed_ms": domain_payload.get("elapsed_ms"),
        "process_elapsed_ms": domain_payload.get("process_elapsed_ms"),
        "capabilities": capabilities,
        "workspace_isolated": bool(fan_in),
        "fan_in": fan_in,
    }


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

    wall_started = time.perf_counter()
    capability_results: dict[str, dict[str, Any]] = {}
    domain_results: dict[str, dict[str, Any]] = {}
    completed_capabilities: set[str] = set()
    completed_domains: set[str] = set()
    parallel_pairs_executed: list[list[str]] = []

    with tempfile.TemporaryDirectory(prefix="fpl-v3-domain-") as tmp:
        temp_root = Path(tmp)
        configured_cache = os.getenv("FPL_RUNTIME_CACHE_DIR", "").strip()
        cache_dir = Path(configured_cache).expanduser().resolve() / "official" if configured_cache else temp_root / "official-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        pending = list(domain_registry["domains"].keys())
        while pending:
            parallel_ready = all(
                domain in pending
                and set(domain_registry["domains"][domain].get("depends_on") or []).issubset(completed_domains)
                for domain in _PARALLEL_ISOLATED_DOMAINS
            )
            if parallel_ready:
                workspaces: dict[str, Path] = {}
                capabilities_by_domain: dict[str, list[str]] = {}
                for domain_name in _PARALLEL_ISOLATED_DOMAINS:
                    capabilities = [str(value) for value in domain_registry["domains"][domain_name].get("capabilities") or []]
                    capabilities_by_domain[domain_name] = capabilities
                    workspaces[domain_name] = _seed_isolated_domain(domain_name, capabilities, services, temp_root)
                pair_started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix="v3-domain") as pool:
                    futures = {
                        domain_name: pool.submit(
                            _run_domain_process,
                            domain_name,
                            mode=mode,
                            stats=stats,
                            deep_stats=deep_stats,
                            profile_name=profile_name,
                            cache_dir=cache_dir,
                            cache_ttl=cache_ttl,
                            timeout=timeout,
                            data_dir=workspaces[domain_name],
                        )
                        for domain_name in _PARALLEL_ISOLATED_DOMAINS
                    }
                    payloads = {domain_name: futures[domain_name].result() for domain_name in _PARALLEL_ISOLATED_DOMAINS}
                pair_wall_ms = round((time.perf_counter() - pair_started) * 1000.0, 3)
                for domain_name in _PARALLEL_ISOLATED_DOMAINS:
                    fan_in = _promote_isolated_domain(
                        domain_name,
                        capabilities_by_domain[domain_name],
                        services,
                        workspaces[domain_name],
                    )
                    fan_in["parallel_pair_wall_ms"] = pair_wall_ms
                    _accept_domain_result(
                        domain_name,
                        payloads[domain_name],
                        capabilities_by_domain[domain_name],
                        services,
                        capability_results,
                        completed_capabilities,
                        domain_results,
                        fan_in=fan_in,
                    )
                    completed_domains.add(domain_name)
                    pending.remove(domain_name)
                parallel_pairs_executed.append(list(_PARALLEL_ISOLATED_DOMAINS))
                continue

            progressed = False
            for domain_name in list(pending):
                domain_spec = domain_registry["domains"][domain_name]
                if not set(domain_spec.get("depends_on") or []).issubset(completed_domains):
                    continue
                capabilities = [str(value) for value in domain_spec.get("capabilities") or []]
                domain_set = set(capabilities)
                for capability in capabilities:
                    spec = services[capability]
                    external_deps = {str(dep) for dep in spec.get("depends_on") or []} - domain_set
                    missing = sorted(external_deps - completed_capabilities)
                    if missing:
                        raise RuntimeError(
                            f"domain ordering violates capability dependency: {domain_name}:{capability} missing={missing}"
                        )

                domain_payload = _run_domain_process(
                    domain_name,
                    mode=mode,
                    stats=stats,
                    deep_stats=deep_stats,
                    profile_name=profile_name,
                    cache_dir=cache_dir,
                    cache_ttl=cache_ttl,
                    timeout=timeout,
                )
                _accept_domain_result(
                    domain_name,
                    domain_payload,
                    capabilities,
                    services,
                    capability_results,
                    completed_capabilities,
                    domain_results,
                )
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
            "diagnostics_semantics": "PRE_EXECUTION_DECISION_STATE_WHEN_AVAILABLE",
            "diagnostics": {
                name: _reuse_diagnostic_summary(name, capability_results, profile_name)
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
        performance["domain_process_execution"] = {
            "enabled": True,
            "process_count": len(domain_results),
            "one_process_per_execution_domain": True,
            "business_ownership_unchanged": True,
            "isolated_parallel_domains": list(_PARALLEL_ISOLATED_DOMAINS),
            "parallel_pairs_executed": parallel_pairs_executed,
            "deterministic_fan_in": True,
        }
        performance["runtime_id"] = DOMAIN_RUNTIME_ID
        performance["architecture"] = domain_registry["architecture"]
        performance["execution_domain_count"] = len(domain_results)
        performance["capability_owner_count"] = len(capability_results)
        performance["execution_domains"] = domain_results
        performance["cross_capability_copy_promotion"] = bool(parallel_pairs_executed)
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
            "one_process_per_execution_domain": True,
            "isolated_parallel_domains": list(_PARALLEL_ISOLATED_DOMAINS),
            "deterministic_fan_in": True,
            "cross_capability_copy_promotion": bool(parallel_pairs_executed),
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
        "domain_process_execution": performance.get("domain_process_execution"),
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
