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
from src.runtime_v3 import domain_process_runner
from src.runtime_v3 import orchestrator as legacy
from src.runtime_v3 import registry_compiler
from src.utils import DATA, ROOT, atomic_json, read_json
from src.version import ENGINE_VERSION, SCHEMA_VERSION

DOMAIN_PATH = ROOT / "config" / "runtime" / "execution_domains.json"
PERFORMANCE_PATH = DATA / "runtime_performance.json"
FAST_LANE_POLICY_PATH = ROOT / "config" / "runtime" / "fast_lane_policy.json"
DOMAIN_RUNTIME_ID = "v3-domain-pipeline-v2"
_DOMAIN_RESULT_PREFIX = "V3_DOMAIN_RESULT="
_CANONICAL_PHASES = ("ACQUIRE", "ENRICH", "MODEL", "DECISION", "GOVERNANCE", "PUBLISH")
_CANONICAL_DOMAINS = (
    "official_state",
    "personal_team_state",
    "football_context",
    "weather_context",
    "market_context",
    "prediction",
    "squad_decision",
    "challenger_analysis",
    "framework_governance",
    "prediction_validation",
    "reporting",
    "serving",
)


def _load_domains() -> dict[str, Any]:
    payload = json.loads(DOMAIN_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_EXECUTION_DOMAINS_V2":
        raise RuntimeError("unexpected execution domain registry")
    domains = payload.get("domains")
    if not isinstance(domains, dict) or len(domains) != int(payload.get("domain_count") or 0):
        raise RuntimeError("execution domain count does not match its registry contract")
    if tuple(domains) != _CANONICAL_DOMAINS:
        raise RuntimeError(f"canonical execution domain order drifted: {tuple(domains)}")
    phases = payload.get("canonical_phases")
    if not isinstance(phases, dict) or tuple(phases) != _CANONICAL_PHASES:
        raise RuntimeError("canonical execution phase contract drifted")
    if int(payload.get("phase_count") or 0) != len(_CANONICAL_PHASES):
        raise RuntimeError("execution phase count does not match its registry contract")
    phase_domains = [str(name) for phase in _CANONICAL_PHASES for name in phases.get(phase) or []]
    if len(phase_domains) != len(set(phase_domains)) or set(phase_domains) != set(domains):
        raise RuntimeError("canonical phases must cover every execution domain exactly once")
    for phase, names in phases.items():
        for name in names:
            if (domains.get(str(name)) or {}).get("phase") != phase:
                raise RuntimeError(f"execution domain phase drift: {name} is not owned by {phase}")
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

    owner = {
        capability: domain_name
        for domain_name, spec in domains.items()
        for capability in spec.get("capabilities") or []
    }
    remaining = set(domains)
    completed: set[str] = set()
    while remaining:
        ready = {
            name
            for name in remaining
            if set(domains[name].get("depends_on") or []).issubset(completed)
        }
        if not ready:
            raise RuntimeError(f"execution domain dependency cycle: {sorted(remaining)}")
        completed.update(ready)
        remaining.difference_update(ready)

    def ancestors(domain_name: str) -> set[str]:
        found: set[str] = set()
        pending = list(domains[domain_name].get("depends_on") or [])
        while pending:
            dependency = str(pending.pop())
            if dependency in found:
                continue
            found.add(dependency)
            pending.extend(domains[dependency].get("depends_on") or [])
        return found

    for domain_name, spec in domains.items():
        upstream = ancestors(domain_name)
        domain_capabilities = set(spec.get("capabilities") or [])
        for capability in domain_capabilities:
            for dependency in (service_registry["services"][capability].get("depends_on") or []):
                dependency_owner = owner[str(dependency)]
                if dependency_owner != domain_name and dependency_owner not in upstream:
                    raise RuntimeError(
                        "execution domain dependency does not cover capability dependency: "
                        f"{domain_name}:{capability} requires {dependency_owner}:{dependency}"
                    )


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


def _fast_lane_policy() -> dict[str, Any]:
    payload = json.loads(FAST_LANE_POLICY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_FAST_LANE_POLICY_V1":
        raise RuntimeError("unexpected V3 fast-lane policy registry")
    return payload


def _run_domain_in_process(
    domain_name: str,
    *,
    mode: str,
    stats: bool,
    deep_stats: bool,
    profile_name: str,
    cache_dir: Path,
    cache_ttl: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    previous = {
        key: os.environ.get(key)
        for key in ("FPL_HTTP_CACHE_DIR", "FPL_HTTP_CACHE_TTL_SECONDS", "FPL_EXECUTION_PROFILE")
    }
    os.environ["FPL_HTTP_CACHE_DIR"] = str(cache_dir)
    os.environ["FPL_HTTP_CACHE_TTL_SECONDS"] = str(cache_ttl)
    os.environ["FPL_EXECUTION_PROFILE"] = profile_name
    try:
        payload = domain_process_runner.run_domain(domain_name, mode, stats, deep_stats, profile_name)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    payload["process_elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    payload["execution_boundary"] = "IN_PROCESS_COALESCED"
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
    canonical_latest = read_json(DATA / "latest.json", {})
    workspace_latest = read_json(workspace / "latest.json", {})
    if not isinstance(canonical_latest, dict) or not isinstance(workspace_latest, dict):
        raise RuntimeError(f"{domain_name} latest.json fan-in requires object payloads")

    promotion_plan: list[tuple[str, Path]] = []
    for capability in capabilities:
        for relative in services[capability].get("artifacts") or []:
            name = str(relative)
            source = workspace / name
            if not source.is_file():
                raise RuntimeError(f"{domain_name} validated artifact missing before fan-in: {name}")
            promotion_plan.append((name, source))

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

    workspace_state = read_json(workspace / "incremental_reuse_state.json", {})
    canonical_state = read_json(DATA / "incremental_reuse_state.json", {})
    if not isinstance(canonical_state, dict):
        canonical_state = {}
    if isinstance(workspace_state, dict) and isinstance(workspace_state.get("services"), dict):
        canonical_state.setdefault("schema_version", workspace_state.get("schema_version", 1))
        canonical_state.setdefault("registry", workspace_state.get("registry", "V3_INCREMENTAL_REUSE_STATE_V1"))
        canonical_services = canonical_state.setdefault("services", {})
        for capability in capabilities:
            if capability in workspace_state["services"]:
                canonical_services[capability] = workspace_state["services"][capability]

    copied: list[str] = []
    copied_bytes = 0
    for name, source in promotion_plan:
        target = DATA / name
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_suffix(target.suffix + f".{domain_name.lower()}.fan-in.tmp")
        shutil.copy2(source, staging)
        os.replace(staging, target)
        copied.append(name)
        copied_bytes += target.stat().st_size
    atomic_json(DATA / "latest.json", canonical_latest)
    if canonical_state:
        atomic_json(DATA / "incremental_reuse_state.json", canonical_state)

    return {
        "domain": domain_name,
        "workspace_isolated": True,
        "promoted_artifacts": sorted(set(copied)),
        "promoted_bytes": copied_bytes,
        "merged_latest_keys": sorted(set(merged_latest_keys)),
        "merged_latest_file_keys": sorted(set(merged_file_keys)),
    }



def _parallel_wave_isolation_safe(
    wave: tuple[str, ...],
    domain_registry: dict[str, Any],
    services: dict[str, Any],
) -> bool:
    """Only parallelize compiled waves whose capability outputs cannot collide."""
    if len(wave) < 2:
        return False
    artifacts_seen: set[str] = set()
    latest_keys_seen: set[str] = set()
    latest_file_keys_seen: set[str] = set()
    for domain_name in wave:
        domain_spec = domain_registry["domains"].get(domain_name) or {}
        capabilities = [str(value) for value in domain_spec.get("capabilities") or []]
        if not capabilities:
            return False
        if any(not bool((services.get(capability) or {}).get("isolated", False)) for capability in capabilities):
            return False
        artifacts = {
            str(value)
            for capability in capabilities
            for value in (services[capability].get("artifacts") or [])
        }
        latest_keys = {
            str(value)
            for capability in capabilities
            for value in (services[capability].get("latest_keys") or [])
        }
        latest_file_keys = {
            str(value)
            for capability in capabilities
            for value in (services[capability].get("latest_file_keys") or [])
        }
        if artifacts_seen & artifacts or latest_keys_seen & latest_keys or latest_file_keys_seen & latest_file_keys:
            return False
        artifacts_seen.update(artifacts)
        latest_keys_seen.update(latest_keys)
        latest_file_keys_seen.update(latest_file_keys)
    return True

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
    phase: str,
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
        "phase": phase,
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
    compiled_plan = registry_compiler.compile_runtime_plan(
        domain_registry=domain_registry,
        service_registry=service_registry,
    )
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

        pending = list(compiled_plan["domain_order"])
        fast_policy = _fast_lane_policy()
        coalesced_fast = profile_name in set(fast_policy.get("profiles") or [])
        parallel_waves = [] if coalesced_fast else [
            tuple(str(domain) for domain in wave)
            for wave in compiled_plan["domain_waves"]
            if len(wave) > 1
            and _parallel_wave_isolation_safe(
                tuple(str(domain) for domain in wave),
                domain_registry,
                services,
            )
        ]
        parallel_wave_domains = {domain for wave in parallel_waves for domain in wave}
        while pending:
            ready_wave = next(
                (
                    wave
                    for wave in parallel_waves
                    if all(
                        domain in pending
                        and set(domain_registry["domains"][domain].get("depends_on") or []).issubset(completed_domains)
                        for domain in wave
                    )
                ),
                None,
            )
            if ready_wave is not None:
                workspaces: dict[str, Path] = {}
                capabilities_by_domain: dict[str, list[str]] = {}
                for domain_name in ready_wave:
                    domain_spec = domain_registry["domains"][domain_name]
                    capabilities = [str(value) for value in domain_spec.get("capabilities") or []]
                    domain_set = set(capabilities)
                    for capability in capabilities:
                        spec = services[capability]
                        external_deps = {str(dep) for dep in spec.get("depends_on") or []} - domain_set
                        missing = sorted(external_deps - completed_capabilities)
                        if missing:
                            raise RuntimeError(
                                f"parallel domain ordering violates capability dependency: {domain_name}:{capability} missing={missing}"
                            )
                    capabilities_by_domain[domain_name] = capabilities
                    workspaces[domain_name] = _seed_isolated_domain(domain_name, capabilities, services, temp_root)

                wave_started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=len(ready_wave), thread_name_prefix="v3-domain") as pool:
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
                        for domain_name in ready_wave
                    }
                    payloads = {domain_name: futures[domain_name].result() for domain_name in ready_wave}
                wave_wall_ms = round((time.perf_counter() - wave_started) * 1000.0, 3)

                for domain_name in ready_wave:
                    fan_in = _promote_isolated_domain(
                        domain_name,
                        capabilities_by_domain[domain_name],
                        services,
                        workspaces[domain_name],
                    )
                    fan_in["parallel_wave_wall_ms"] = wave_wall_ms
                    if len(ready_wave) == 2:
                        fan_in["parallel_pair_wall_ms"] = wave_wall_ms
                    _accept_domain_result(
                        domain_name,
                        payloads[domain_name],
                        capabilities_by_domain[domain_name],
                        services,
                        capability_results,
                        completed_capabilities,
                        domain_results,
                        phase=str(domain_registry["domains"][domain_name]["phase"]),
                        fan_in=fan_in,
                    )
                    completed_domains.add(domain_name)
                    pending.remove(domain_name)
                parallel_pairs_executed.append(list(ready_wave))
                continue

            progressed = False
            for domain_name in list(pending):
                if domain_name in parallel_wave_domains:
                    continue
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

                if coalesced_fast:
                    domain_payload = _run_domain_in_process(
                        domain_name,
                        mode=mode,
                        stats=stats,
                        deep_stats=deep_stats,
                        profile_name=profile_name,
                        cache_dir=cache_dir,
                        cache_ttl=cache_ttl,
                    )
                else:
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
                    phase=str(domain_spec["phase"]),
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
        batch_registry = module_batch_runner._registry()
        performance["module_batching"] = {
            "registry": batch_registry["registry"],
            "generated_from": batch_registry.get("generated_from"),
            "human_maintained_registry": False,
            "batched_services": sorted(
                name for name, row in capability_results.items()
                if row.get("single_process_module_batch") is True
            ),
        }
        performance["compiled_execution_plan"] = {
            "registry": compiled_plan["registry"],
            "plan_sha256": compiled_plan["plan_sha256"],
            "phase_count": compiled_plan["phase_count"],
            "domain_count": compiled_plan["domain_count"],
            "capability_count": compiled_plan["capability_count"],
            "domain_waves": compiled_plan["domain_waves"],
            "batch_registry": batch_registry["registry"],
            "runtime_assurance": "PASS",
        }
        performance["domain_process_execution"] = {
            "enabled": not coalesced_fast,
            "process_count": 0 if coalesced_fast else len(domain_results),
            "phase_count": int(domain_registry["phase_count"]),
            "one_process_per_execution_domain": not coalesced_fast,
            "coalesced_fast_lane": coalesced_fast,
            "execution_boundary": "IN_PROCESS_COALESCED" if coalesced_fast else "DOMAIN_PROCESS",
            "fail_closed_after_partial_execution": bool(fast_policy.get("fail_closed_after_partial_execution", True)) if coalesced_fast else True,
            "fallback_to_multi_process_allowed": bool(fast_policy.get("fallback_to_multi_process_allowed", False)) if coalesced_fast else True,
            "business_ownership_unchanged": True,
            "isolated_parallel_domains": sorted(parallel_wave_domains),
            "parallel_pairs_executed": parallel_pairs_executed,
            "compiled_parallel_waves": [list(wave) for wave in parallel_waves],
            "parallel_wave_scheduler": "COMPILED_ISOLATION_SAFE",
            "deterministic_fan_in": True,
        }
        performance["runtime_id"] = DOMAIN_RUNTIME_ID
        performance["architecture"] = domain_registry["architecture"]
        performance["execution_domain_count"] = len(domain_results)
        performance["execution_phase_count"] = int(domain_registry["phase_count"])
        performance["execution_phases"] = domain_registry["canonical_phases"]
        performance["canonical_domain_order"] = list(compiled_plan["domain_order"])
        performance["execution_order"] = list(domain_results)
        performance["execution_phase_results"] = {
            phase: {
                "status": "SUCCESS",
                "domains": list(names),
            }
            for phase, names in domain_registry["canonical_phases"].items()
        }
        performance["capability_owner_count"] = len(capability_results)
        performance["execution_domains"] = domain_results
        performance["cross_capability_copy_promotion"] = False
        performance["isolated_domain_fan_in_promotion"] = bool(parallel_pairs_executed)
        performance["ephemeral_artifacts_removed"] = legacy._cleanup_ephemeral(service_registry, DATA)
        atomic_json(PERFORMANCE_PATH, performance)

        latest = read_json(DATA / "latest.json", {})
        runtime_meta = latest.setdefault("runtime_architecture", {})
        runtime_meta.update({
            "id": DOMAIN_RUNTIME_ID,
            "architecture": domain_registry["architecture"],
            "service_count": len(domain_results),
            "execution_domain_count": len(domain_results),
            "execution_phase_count": int(domain_registry["phase_count"]),
            "execution_phases": domain_registry["canonical_phases"],
            "canonical_domain_order": list(compiled_plan["domain_order"]),
            "execution_order": list(domain_results),
            "dependency_aware_scheduling": True,
            "shared_official_cache": True,
            "capability_owner_count": len(capability_results),
            "shared_canonical_domain_workspace": True,
            "one_process_per_execution_domain": not coalesced_fast,
            "coalesced_fast_lane": coalesced_fast,
            "execution_boundary": "IN_PROCESS_COALESCED" if coalesced_fast else "DOMAIN_PROCESS",
            "isolated_parallel_domains": sorted(parallel_wave_domains),
            "compiled_parallel_waves": [list(wave) for wave in parallel_waves],
            "parallel_wave_scheduler": "COMPILED_ISOLATION_SAFE",
            "deterministic_fan_in": True,
            "cross_capability_copy_promotion": False,
            "isolated_domain_fan_in_promotion": bool(parallel_pairs_executed),
            "compiled_execution_plan_registry": compiled_plan["registry"],
            "compiled_execution_plan_sha256": compiled_plan["plan_sha256"],
            "compiled_domain_waves": compiled_plan["domain_waves"],
            "module_batch_registry": batch_registry["registry"],
            "module_batches_derived": True,
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
        "execution_phase_count": int(domain_registry["phase_count"]),
        "capability_owner_count": len(capability_results),
        "compiled_execution_plan": performance.get("compiled_execution_plan"),
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