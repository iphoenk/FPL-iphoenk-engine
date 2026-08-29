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
from src.runtime_v3 import orchestrator as legacy
from src.runtime_v3.registry_compiler import compile_execution_plan
from src.utils import DATA, ROOT, atomic_json, read_json
from src.version import ENGINE_VERSION, SCHEMA_VERSION

RUNTIME_ID = "v3-domain-pipeline-v2"
CONTROL_PLANE_ID = "v3-control-plane-v1"
PERFORMANCE_PATH = DATA / "runtime_performance.json"
_RESULT_PREFIX = "V3_COARSE_SERVICE_RESULT="


def _profile(mode: str, deep_stats: bool, explicit: str | None) -> tuple[str, dict[str, Any]]:
    profiles = legacy._load_profiles().get("profiles") or {}
    profile_name = str(explicit or legacy._default_profile(mode, deep_stats))
    profile_cfg = profiles.get(profile_name)
    if not isinstance(profile_cfg, dict):
        raise RuntimeError(f"unknown execution profile: {profile_name}")
    return profile_name, profile_cfg


def _implementation_seed_paths(service: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    paths = {"latest.json", "incremental_reuse_state.json"}
    paths.update(str(value) for value in service.get("declared_inputs") or [])
    paths.update(str(value) for value in service.get("declared_outputs") or [])
    legacy_services = catalog.get("services") or {}
    for step_id in service.get("implementation_steps") or []:
        spec = legacy_services[str(step_id)]
        paths.update(str(value) for value in spec.get("inputs") or [])
        paths.update(str(value) for value in spec.get("artifacts") or [])
    return sorted(paths)


def _seed_isolated_service(
    service_id: str,
    service: dict[str, Any],
    catalog: dict[str, Any],
    temp_root: Path
) -> Path:
    workspace = temp_root / f"isolated-{service_id}"
    workspace.mkdir(parents=True, exist_ok=True)
    for relative in _implementation_seed_paths(service, catalog):
        source = DATA / relative
        if not source.is_file():
            continue
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return workspace


def _run_service_process(
    service_id: str,
    service: dict[str, Any],
    *,
    mode: str,
    stats: bool,
    deep_stats: bool,
    profile_name: str,
    cache_dir: Path,
    cache_ttl: int,
    timeout: int,
    data_dir: Path
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        str(service["entrypoint"]),
        "--service",
        service_id,
        "--mode",
        mode,
        "--profile",
        profile_name,
        "--stats" if stats else "--no-stats"
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
        check=False
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    if proc.returncode != 0:
        raise RuntimeError(
            f"coarse service {service_id} failed rc={proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '')[-4000:]}"
        )
    marker = next(
        (line for line in reversed((proc.stdout or "").splitlines()) if line.startswith(_RESULT_PREFIX)),
        None
    )
    if marker is None:
        raise RuntimeError(f"coarse service {service_id} emitted no result marker")
    payload = json.loads(marker[len(_RESULT_PREFIX):])
    if payload.get("status") != "SUCCESS":
        raise RuntimeError(f"coarse service {service_id} returned {payload.get('status')}")
    payload["process_elapsed_ms"] = elapsed_ms
    payload["process_stdout_tail"] = (proc.stdout or "")[-4000:]
    payload["process_stderr_tail"] = (proc.stderr or "")[-4000:]
    return payload


def _promote_isolated_service(
    service_id: str,
    service: dict[str, Any],
    catalog: dict[str, Any],
    workspace: Path
) -> dict[str, Any]:
    canonical_latest = read_json(DATA / "latest.json", {})
    workspace_latest = read_json(workspace / "latest.json", {})
    if not isinstance(canonical_latest, dict) or not isinstance(workspace_latest, dict):
        raise RuntimeError(f"{service_id} latest.json fan-in requires object payloads")

    legacy_services = catalog.get("services") or {}
    artifact_names: set[str] = set()
    merged_latest_keys: list[str] = []
    merged_file_keys: list[str] = []
    workspace_files = workspace_latest.get("files") if isinstance(workspace_latest.get("files"), dict) else {}
    canonical_files = canonical_latest.setdefault("files", {})

    for step_id in service.get("implementation_steps") or []:
        spec = legacy_services[str(step_id)]
        artifact_names.update(str(value) for value in spec.get("artifacts") or [])
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

    copied: list[str] = []
    copied_bytes = 0
    for relative in sorted(artifact_names):
        source = workspace / relative
        if not source.is_file():
            raise RuntimeError(f"{service_id} validated artifact missing before fan-in: {relative}")
        target = DATA / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_suffix(target.suffix + f".{service_id}.fan-in.tmp")
        shutil.copy2(source, staging)
        os.replace(staging, target)
        copied.append(relative)
        copied_bytes += target.stat().st_size

    workspace_state = read_json(workspace / "incremental_reuse_state.json", {})
    canonical_state = read_json(DATA / "incremental_reuse_state.json", {})
    if not isinstance(canonical_state, dict):
        canonical_state = {}
    if isinstance(workspace_state, dict) and isinstance(workspace_state.get("services"), dict):
        canonical_state.setdefault("schema_version", workspace_state.get("schema_version", 1))
        canonical_state.setdefault("registry", workspace_state.get("registry", "V3_INCREMENTAL_REUSE_STATE_V1"))
        canonical_services = canonical_state.setdefault("services", {})
        for step_id in service.get("implementation_steps") or []:
            if str(step_id) in workspace_state["services"]:
                canonical_services[str(step_id)] = workspace_state["services"][str(step_id)]

    atomic_json(DATA / "latest.json", canonical_latest)
    if canonical_state:
        atomic_json(DATA / "incremental_reuse_state.json", canonical_state)
    return {
        "service_id": service_id,
        "workspace_isolated": True,
        "promoted_artifacts": copied,
        "promoted_bytes": copied_bytes,
        "merged_latest_keys": sorted(set(merged_latest_keys)),
        "merged_latest_file_keys": sorted(set(merged_file_keys))
    }


def _accept_service_result(
    service_id: str,
    payload: dict[str, Any],
    service: dict[str, Any],
    implementation_results: dict[str, dict[str, Any]],
    service_results: dict[str, dict[str, Any]],
    *,
    fan_in: dict[str, Any] | None = None
) -> None:
    steps = [str(value) for value in service.get("implementation_steps") or []]
    results = payload.get("results") or {}
    for step_id in steps:
        result = results.get(step_id)
        if not isinstance(result, dict):
            raise RuntimeError(f"coarse service {service_id} omitted implementation result {step_id}")
        result["execution_domain"] = service_id
        result["coarse_runtime_owner"] = service_id
        implementation_results[step_id] = result
    service_results[service_id] = {
        "status": "SUCCESS",
        "phase": service.get("phase"),
        "stage": service.get("stage"),
        "elapsed_ms": payload.get("elapsed_ms"),
        "process_elapsed_ms": payload.get("process_elapsed_ms"),
        "implementation_steps": steps,
        "workspace_isolated": bool(fan_in),
        "fan_in": fan_in
    }


def _reuse_diagnostics(implementation_results: dict[str, dict[str, Any]], profile_name: str) -> dict[str, Any]:
    registry = incremental_reuse._registry().get("services") or {}
    out: dict[str, Any] = {}
    for step_id in registry:
        result = implementation_results.get(step_id) or {}
        before = result.get("reuse_diagnostic_before")
        if isinstance(before, dict):
            out[step_id] = {
                **before,
                "decision_time": True,
                "execution_status": result.get("status"),
                "reuse_mode": result.get("reuse_mode")
            }
        else:
            out[step_id] = {
                **incremental_reuse.diagnose(step_id, profile_name),
                "decision_time": False,
                "execution_status": result.get("status"),
                "reuse_mode": result.get("reuse_mode")
            }
    return out


def run(mode: str = "daily", stats: bool = True, deep_stats: bool = False, profile: str | None = None) -> dict[str, Any]:
    plan = compile_execution_plan(write=True)
    catalog = legacy._load_registry()
    legacy._validate_dag(catalog)
    profile_name, profile_cfg = _profile(mode, deep_stats, profile)
    services = plan["services"]
    runtime = catalog.get("runtime") or {}
    timeout = max(1, int(runtime.get("service_timeout_seconds") or 1))
    cache_ttl = max(1, int(runtime.get("http_cache_ttl_seconds") or 1))

    wall_started = time.perf_counter()
    implementation_results: dict[str, dict[str, Any]] = {}
    service_results: dict[str, dict[str, Any]] = {}
    execution_order: list[str] = []
    parallel_groups: list[list[str]] = []

    with tempfile.TemporaryDirectory(prefix="fpl-v3-control-plane-") as tmp:
        temp_root = Path(tmp)
        configured_cache = os.getenv("FPL_RUNTIME_CACHE_DIR", "").strip()
        cache_dir = Path(configured_cache).expanduser().resolve() / "official" if configured_cache else temp_root / "official-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        for wave in plan["waves"]:
            isolated = [
                service_id for service_id in wave
                if services[service_id].get("isolation_policy") == "ISOLATED_FAN_IN"
            ]
            shared = [service_id for service_id in wave if service_id not in isolated]

            if len(isolated) > 1:
                workspaces = {
                    service_id: _seed_isolated_service(service_id, services[service_id], catalog, temp_root)
                    for service_id in isolated
                }
                group_started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=len(isolated), thread_name_prefix="v3-coarse") as pool:
                    futures = {
                        service_id: pool.submit(
                            _run_service_process,
                            service_id,
                            services[service_id],
                            mode=mode,
                            stats=stats,
                            deep_stats=deep_stats,
                            profile_name=profile_name,
                            cache_dir=cache_dir,
                            cache_ttl=cache_ttl,
                            timeout=timeout,
                            data_dir=workspaces[service_id]
                        )
                        for service_id in isolated
                    }
                    payloads = {service_id: futures[service_id].result() for service_id in isolated}
                group_wall_ms = round((time.perf_counter() - group_started) * 1000.0, 3)
                for service_id in isolated:
                    fan_in = _promote_isolated_service(service_id, services[service_id], catalog, workspaces[service_id])
                    fan_in["parallel_group_wall_ms"] = group_wall_ms
                    _accept_service_result(
                        service_id,
                        payloads[service_id],
                        services[service_id],
                        implementation_results,
                        service_results,
                        fan_in=fan_in
                    )
                    execution_order.append(service_id)
                parallel_groups.append(list(isolated))
            else:
                for service_id in isolated:
                    workspace = _seed_isolated_service(service_id, services[service_id], catalog, temp_root)
                    payload = _run_service_process(
                        service_id,
                        services[service_id],
                        mode=mode,
                        stats=stats,
                        deep_stats=deep_stats,
                        profile_name=profile_name,
                        cache_dir=cache_dir,
                        cache_ttl=cache_ttl,
                        timeout=timeout,
                        data_dir=workspace
                    )
                    fan_in = _promote_isolated_service(service_id, services[service_id], catalog, workspace)
                    _accept_service_result(
                        service_id,
                        payload,
                        services[service_id],
                        implementation_results,
                        service_results,
                        fan_in=fan_in
                    )
                    execution_order.append(service_id)

            for service_id in shared:
                payload = _run_service_process(
                    service_id,
                    services[service_id],
                    mode=mode,
                    stats=stats,
                    deep_stats=deep_stats,
                    profile_name=profile_name,
                    cache_dir=cache_dir,
                    cache_ttl=cache_ttl,
                    timeout=timeout,
                    data_dir=DATA
                )
                _accept_service_result(
                    service_id,
                    payload,
                    services[service_id],
                    implementation_results,
                    service_results
                )
                execution_order.append(service_id)

        expected_steps = set(plan["implementation_owner_map"])
        if set(implementation_results) != expected_steps:
            missing = sorted(expected_steps - set(implementation_results))
            extra = sorted(set(implementation_results) - expected_steps)
            raise RuntimeError(f"implementation result coverage drift: missing={missing} extra={extra}")

        total_ms = (time.perf_counter() - wall_started) * 1000.0
        performance = legacy._write_runtime_metadata(
            catalog,
            implementation_results,
            total_ms,
            cache_dir,
            profile_name,
            profile_cfg,
            temp_root
        )
        reuse_active = incremental_reuse.active(profile_name)
        performance["content_addressed_reuse"] = {
            "enabled": reuse_active,
            "inactive_reason": incremental_reuse.inactive_reason(profile_name),
            "reused_services": sorted(
                name for name, row in implementation_results.items()
                if row.get("reuse_mode") == "CONTENT_ADDRESSED"
            ),
            "diagnostics_semantics": "PRE_EXECUTION_DECISION_STATE_WHEN_AVAILABLE",
            "diagnostics": _reuse_diagnostics(implementation_results, profile_name)
        }
        performance["module_batching"] = {
            "runtime_authority": False,
            "registry": "config/runtime/module_batches.json",
            "status": "COMPATIBILITY_METADATA_ONLY"
        }
        performance["domain_process_execution"] = {
            "enabled": True,
            "process_count": len(service_results),
            "phase_count": int(plan["phase_count"]),
            "one_process_per_execution_domain": True,
            "business_ownership_unchanged": False,
            "isolated_parallel_domains": sorted(
                service_id for service_id, spec in services.items()
                if spec.get("isolation_policy") == "ISOLATED_FAN_IN"
            ),
            "parallel_pairs_executed": parallel_groups,
            "deterministic_fan_in": True
        }
        performance["runtime_id"] = RUNTIME_ID
        performance["control_plane_id"] = CONTROL_PLANE_ID
        performance["architecture"] = "V3_CANONICAL_DOMAIN_PIPELINE"
        performance["control_plane_architecture"] = plan["architecture"]
        performance["execution_registry"] = plan["source_registry"]
        performance["execution_registry_hash"] = plan["registry_hash"]
        performance["execution_plan_hash"] = plan["plan_hash"]
        performance["execution_domain_count"] = len(service_results)
        performance["active_runtime_service_count"] = len(service_results)
        performance["execution_phase_count"] = int(plan["phase_count"])
        performance["execution_phases"] = plan["phases"]
        performance["canonical_domain_order"] = plan["service_order"]
        performance["execution_order"] = execution_order
        performance["execution_waves"] = plan["waves"]
        performance["execution_phase_results"] = {
            phase: {"status": "SUCCESS", "domains": list(names)}
            for phase, names in plan["phases"].items()
        }
        performance["capability_owner_count"] = int(plan["implementation_step_count"])
        performance["implementation_step_count"] = int(plan["implementation_step_count"])
        performance["execution_domains"] = service_results
        performance["coarse_runtime_services"] = service_results
        performance["cross_capability_copy_promotion"] = False
        performance["isolated_domain_fan_in_promotion"] = bool(parallel_groups)
        performance["ephemeral_artifacts_removed"] = legacy._cleanup_ephemeral(catalog, DATA)
        atomic_json(PERFORMANCE_PATH, performance)

        latest = read_json(DATA / "latest.json", {})
        runtime_meta = latest.setdefault("runtime_architecture", {})
        runtime_meta.update({
            "id": RUNTIME_ID,
            "control_plane_id": CONTROL_PLANE_ID,
            "architecture": "V3_CANONICAL_DOMAIN_PIPELINE",
            "control_plane_architecture": plan["architecture"],
            "service_count": len(service_results),
            "active_runtime_service_count": len(service_results),
            "implementation_step_count": int(plan["implementation_step_count"]),
            "capability_owner_count": int(plan["implementation_step_count"]),
            "execution_domain_count": len(service_results),
            "execution_phase_count": int(plan["phase_count"]),
            "execution_phases": plan["phases"],
            "canonical_domain_order": plan["service_order"],
            "execution_order": execution_order,
            "execution_waves": plan["waves"],
            "dependency_aware_scheduling": True,
            "shared_official_cache": True,
            "shared_canonical_domain_workspace": True,
            "one_process_per_execution_domain": True,
            "deterministic_fan_in": True,
            "execution_registry": plan["source_registry"],
            "execution_registry_hash": plan["registry_hash"],
            "execution_plan_hash": plan["plan_hash"],
            "module_batches_runtime_authority": False,
            "cross_capability_copy_promotion": False,
            "isolated_domain_fan_in_promotion": bool(parallel_groups),
            "total_wall_ms": round(total_ms, 3)
        })
        atomic_json(DATA / "latest.json", latest)

    print(json.dumps({
        "runtime": RUNTIME_ID,
        "control_plane": CONTROL_PLANE_ID,
        "architecture": plan["architecture"],
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "execution_profile": profile_name,
        "total_wall_ms": performance["total_wall_ms"],
        "target_wall_ms": performance.get("target_wall_ms"),
        "within_target_slo": performance.get("within_target_slo"),
        "within_target_budget": performance.get("within_target_budget"),
        "active_runtime_service_count": len(service_results),
        "implementation_step_count": int(plan["implementation_step_count"]),
        "execution_phase_count": int(plan["phase_count"]),
        "execution_plan_hash": plan["plan_hash"],
        "services": service_results,
        "resources": performance.get("resources")
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
