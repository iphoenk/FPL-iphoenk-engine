from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - GitHub production runs on Linux
    resource = None

from src.runtime_v3 import RUNTIME_ID
from src.runtime_v3.artifact_contracts import validate_artifact, validate_latest_sidecar
from src.utils import DATA, ROOT, atomic_json, read_json
from src.version import ENGINE_VERSION, SCHEMA_VERSION

REGISTRY_PATH = ROOT / "config" / "v3_service_registry.json"
PROFILE_PATH = ROOT / "config" / "runtime" / "execution_profiles.json"
SLO_PATH = ROOT / "config" / "runtime" / "performance_slo.json"
PERFORMANCE_PATH = DATA / "runtime_performance.json"


def _load_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    services = payload.get("services")
    if not isinstance(services, dict) or not services:
        raise RuntimeError("invalid V3 service registry: services must be non-empty")
    roots = [name for name, spec in services.items() if not (spec.get("depends_on") or [])]
    if not roots:
        raise RuntimeError("invalid V3 service registry: at least one root service is required")
    for name, spec in services.items():
        if not isinstance(spec, dict):
            raise RuntimeError(f"invalid V3 service registry: service {name} must be an object")
        commands = spec.get("commands") or []
        if not commands:
            raise RuntimeError(f"invalid V3 service registry: service {name} has no commands")
        for command in commands:
            if "code" in command:
                raise RuntimeError(f"inline Python service command forbidden: {name}")
            if not (command.get("module") or command.get("copy")):
                raise RuntimeError(f"unsupported service command contract: {name}: {command}")
    return payload


def _load_profiles() -> dict[str, Any]:
    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "RUNTIME_EXECUTION_PROFILES_V1":
        raise RuntimeError("unexpected runtime execution profile registry")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise RuntimeError("runtime execution profile registry has no profiles")
    return payload


def _load_slo() -> dict[str, Any]:
    payload = json.loads(SLO_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "RUNTIME_PERFORMANCE_SLO_V1":
        raise RuntimeError("unexpected runtime performance SLO registry")
    return payload


def _validate_dag(registry: dict[str, Any]) -> None:
    services = registry["services"]
    for name, spec in services.items():
        for dep in spec.get("depends_on") or []:
            if dep not in services:
                raise RuntimeError(f"service {name} depends on unknown service {dep}")
            if dep == name:
                raise RuntimeError(f"service {name} has self dependency")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise RuntimeError(f"service dependency cycle detected at {name}")
        if name in visited:
            return
        visiting.add(name)
        for dep in services[name].get("depends_on") or []:
            visit(str(dep))
        visiting.remove(name)
        visited.add(name)

    for name in services:
        visit(name)


def _tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if len(text) > limit else text


def _expand_args(args: list[str], context: dict[str, str]) -> list[str]:
    out: list[str] = []
    for value in args:
        expanded = str(value)
        for key, replacement in context.items():
            expanded = expanded.replace("{" + key + "}", replacement)
        if expanded:
            out.append(expanded)
    return out


def _path_bytes(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += _path_bytes(item)
    return total


def _rss_kb(kind: int) -> int | None:
    if resource is None:
        return None
    try:
        value = int(resource.getrusage(kind).ru_maxrss)
        if sys.platform == "darwin":
            value //= 1024
        return value
    except Exception:
        return None


def _run_command(command: dict[str, Any], *, data_dir: Path, cache_dir: Path, context: dict[str, str], timeout: int) -> dict[str, Any]:
    if command.get("copy"):
        source_name, target_name = [str(x) for x in command["copy"]]
        source = data_dir / source_name
        target = data_dir / target_name
        if not source.exists():
            raise RuntimeError(f"copy source missing: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        shutil.copy2(source, target)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return {
            "type": "copy",
            "source": source_name,
            "target": target_name,
            "elapsed_ms": elapsed_ms,
            "bytes": _path_bytes(target),
        }
    if not command.get("module"):
        raise RuntimeError(f"unsupported service command: {command}")
    cmd = [sys.executable, "-m", str(command["module"]), *_expand_args(list(command.get("args") or []), context)]
    descriptor = str(command["module"])
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["FPL_DATA_DIR"] = str(data_dir)
    env["FPL_HTTP_CACHE_DIR"] = str(cache_dir)
    env["FPL_HTTP_CACHE_TTL_SECONDS"] = context["http_cache_ttl"]
    env["FPL_EXECUTION_PROFILE"] = context["profile"]
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout, check=False)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    result = {
        "type": "process",
        "descriptor": descriptor,
        "argv": cmd[2:] if len(cmd) > 2 else cmd,
        "returncode": proc.returncode,
        "elapsed_ms": elapsed_ms,
        "stdout_tail": _tail(proc.stdout or ""),
        "stderr_tail": _tail(proc.stderr or ""),
    }
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def _seed_service_data(service_name: str, spec: dict[str, Any], canonical: Path, service_root: Path) -> tuple[Path, int, float]:
    target = service_root / service_name
    target.mkdir(parents=True, exist_ok=True)
    copied_bytes = 0
    started = time.perf_counter()
    for name in spec.get("inputs") or []:
        source = canonical / str(name)
        if source.exists():
            destination = target / str(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied_bytes += _path_bytes(destination)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return target, copied_bytes, elapsed_ms


def _run_service(
    service_name: str,
    spec: dict[str, Any],
    *,
    canonical: Path,
    services_root: Path,
    cache_dir: Path,
    context: dict[str, str],
    timeout: int,
    submitted_at: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    queue_wait_ms = round((started - submitted_at) * 1000.0, 3)
    isolated = bool(spec.get("isolated", True))
    seed_bytes = 0
    seed_ms = 0.0
    if isolated:
        data_dir, seed_bytes, seed_ms = _seed_service_data(service_name, spec, canonical, services_root)
    else:
        data_dir = canonical
    commands = []
    try:
        for command in spec.get("commands") or []:
            commands.append(_run_command(command, data_dir=data_dir, cache_dir=cache_dir, context=context, timeout=timeout))
        return {
            "service": service_name,
            "status": "SUCCESS",
            "isolated": isolated,
            "data_dir": str(data_dir),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "queue_wait_ms": queue_wait_ms,
            "seed_input_ms": seed_ms,
            "seed_input_bytes": seed_bytes,
            "commands": commands,
        }
    except Exception as exc:
        return {
            "service": service_name,
            "status": "FAILED",
            "isolated": isolated,
            "data_dir": str(data_dir),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "queue_wait_ms": queue_wait_ms,
            "seed_input_ms": seed_ms,
            "seed_input_bytes": seed_bytes,
            "commands": commands,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _merge_latest(canonical: Path, service_dir: Path, spec: dict[str, Any]) -> None:
    if not (service_dir / "latest.json").exists():
        return
    current = read_json(canonical / "latest.json", {})
    source = read_json(service_dir / "latest.json", {})
    for key in spec.get("latest_keys") or []:
        if key in source:
            current[str(key)] = source[key]
    source_files = source.get("files") if isinstance(source.get("files"), dict) else {}
    if source_files:
        current.setdefault("files", {})
        for key in spec.get("latest_file_keys") or []:
            if key in source_files:
                current["files"][str(key)] = source_files[key]
    atomic_json(canonical / "latest.json", current)


def _validate_service_outputs(service_name: str, result: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    data_dir = Path(str(result["data_dir"]))
    validations: list[dict[str, Any]] = []
    isolated = bool(result.get("isolated"))
    for name in spec.get("artifacts") or []:
        artifact = str(name)
        path = data_dir / artifact
        if not path.exists():
            if isolated:
                continue
            raise RuntimeError(f"service {service_name} did not produce required artifact {artifact}")
        validations.append(validate_artifact(path, artifact))
    sidecar = validate_latest_sidecar(data_dir / "latest.json")
    if sidecar:
        validations.append(sidecar)
    return validations


def _promote(service_name: str, result: dict[str, Any], spec: dict[str, Any], canonical: Path) -> int:
    if not result.get("isolated"):
        return 0
    service_dir = Path(str(result["data_dir"]))
    copied_bytes = 0
    for name in spec.get("artifacts") or []:
        source = service_dir / str(name)
        if not source.exists():
            raise RuntimeError(f"service {service_name} did not produce required artifact {name}")
        destination = canonical / str(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied_bytes += _path_bytes(destination)
    _merge_latest(canonical, service_dir, spec)
    return copied_bytes


def _attempt_promotion(service_name: str, result: dict[str, Any], spec: dict[str, Any], canonical: Path) -> dict[str, Any]:
    validation_started = time.perf_counter()
    try:
        validated = _validate_service_outputs(service_name, result, spec)
    except Exception as exc:
        failed = dict(result)
        failed["status"] = "FAILED"
        failed["failure_stage"] = "artifact_validation"
        failed["validation_ms"] = round((time.perf_counter() - validation_started) * 1000.0, 3)
        failed["error"] = f"{type(exc).__name__}: {exc}"
        return failed
    validation_ms = round((time.perf_counter() - validation_started) * 1000.0, 3)
    promotion_started = time.perf_counter()
    try:
        promoted_bytes = _promote(service_name, result, spec, canonical)
        accepted = dict(result)
        accepted["artifact_validation"] = validated
        accepted["validation_ms"] = validation_ms
        accepted["promotion_ms"] = round((time.perf_counter() - promotion_started) * 1000.0, 3)
        accepted["promoted_output_bytes"] = promoted_bytes
        return accepted
    except Exception as exc:
        failed = dict(result)
        failed["status"] = "FAILED"
        failed["failure_stage"] = "promotion"
        failed["validation_ms"] = validation_ms
        failed["promotion_ms"] = round((time.perf_counter() - promotion_started) * 1000.0, 3)
        failed["error"] = f"{type(exc).__name__}: {exc}"
        return failed


def _reuse_service(
    service_name: str,
    spec: dict[str, Any],
    canonical: Path,
    profile_cfg: dict[str, Any],
) -> dict[str, Any] | None:
    reuse_cfg = (profile_cfg.get("reuse_services") or {}).get(service_name)
    if not isinstance(reuse_cfg, dict):
        return None
    max_age = max(1.0, float(reuse_cfg.get("max_age_seconds") or 0))
    artifacts = [str(name) for name in spec.get("artifacts") or []]
    if not artifacts:
        return None
    paths = [canonical / name for name in artifacts]
    if not all(path.exists() and path.is_file() for path in paths):
        return None
    oldest_mtime = min(path.stat().st_mtime for path in paths)
    age_seconds = max(0.0, time.time() - oldest_mtime)
    if age_seconds > max_age:
        return None
    started = time.perf_counter()
    validations = [validate_artifact(path, name) for path, name in zip(paths, artifacts)]
    return {
        "service": service_name,
        "status": "REUSED",
        "isolated": False,
        "data_dir": str(canonical),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "queue_wait_ms": 0.0,
        "seed_input_ms": 0.0,
        "seed_input_bytes": 0,
        "validation_ms": 0.0,
        "promotion_ms": 0.0,
        "promoted_output_bytes": 0,
        "reuse_age_seconds": round(age_seconds, 3),
        "reuse_max_age_seconds": max_age,
        "artifact_validation": validations,
        "commands": [],
    }


def _clear_failed_service_outputs(canonical: Path, spec: dict[str, Any]) -> list[str]:
    """Remove stale owned outputs before a noncritical failed service is treated as completed."""
    inputs = {str(name) for name in spec.get("inputs") or []}
    removed: list[str] = []
    for name in spec.get("artifacts") or []:
        artifact = str(name)
        if artifact in inputs:
            continue
        path = canonical / artifact
        if path.exists() and path.is_file():
            path.unlink()
            removed.append(artifact)
    latest_path = canonical / "latest.json"
    latest = read_json(latest_path, {})
    changed = False
    for key in spec.get("latest_keys") or []:
        if str(key) in latest:
            latest.pop(str(key), None)
            changed = True
    files = latest.get("files") if isinstance(latest.get("files"), dict) else None
    if files is not None:
        for key in spec.get("latest_file_keys") or []:
            if str(key) in files:
                files.pop(str(key), None)
                changed = True
    if changed:
        atomic_json(latest_path, latest)
    return sorted(removed)


def _cleanup_ephemeral(registry: dict[str, Any], canonical: Path) -> list[str]:
    removed: list[str] = []
    for spec in (registry.get("services") or {}).values():
        for name in spec.get("ephemeral_artifacts") or []:
            path = canonical / str(name)
            if path.exists() and path.is_file():
                path.unlink()
                removed.append(str(name))
    return sorted(set(removed))


def _write_runtime_metadata(
    registry: dict[str, Any],
    service_results: dict[str, dict[str, Any]],
    total_ms: float,
    cache_dir: Path,
    profile: str,
    profile_cfg: dict[str, Any],
    temp_root: Path,
) -> dict[str, Any]:
    cache_entries = len(list(cache_dir.glob("*.json"))) if cache_dir.exists() else 0
    slo = (_load_slo().get("profiles") or {}).get(profile) or {}
    target_ms = float(slo.get("target_wall_ms") or 0)
    warning_ms = float(slo.get("warning_wall_ms") or target_ms)
    ceiling_ms = float(slo.get("legacy_ceiling_ms") or target_ms)
    seed_bytes = sum(int(row.get("seed_input_bytes") or 0) for row in service_results.values())
    promoted_bytes = sum(int(row.get("promoted_output_bytes") or 0) for row in service_results.values())
    resources = {
        "peak_rss_kb": _rss_kb(resource.RUSAGE_SELF) if resource is not None else None,
        "child_peak_rss_kb": _rss_kb(resource.RUSAGE_CHILDREN) if resource is not None else None,
        "temporary_bytes": _dir_bytes(temp_root),
        "seed_input_bytes": seed_bytes,
        "promoted_output_bytes": promoted_bytes,
    }
    performance = {
        "runtime_id": RUNTIME_ID,
        "architecture": registry.get("architecture"),
        "production_contract": registry.get("production_contract"),
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "execution_profile": profile,
        "profile_config": profile_cfg,
        "total_wall_ms": round(total_ms, 3),
        "target_wall_ms": round(target_ms, 3) if target_ms else None,
        "warning_wall_ms": round(warning_ms, 3) if warning_ms else None,
        "legacy_ceiling_ms": round(ceiling_ms, 3) if ceiling_ms else None,
        "within_target_slo": total_ms <= target_ms if target_ms else None,
        "within_warning_slo": total_ms <= warning_ms if warning_ms else None,
        "within_legacy_ceiling": total_ms <= ceiling_ms if ceiling_ms else None,
        "performance_budget_ms": round(ceiling_ms, 3) if ceiling_ms else None,
        "within_target_budget": total_ms <= ceiling_ms if ceiling_ms else None,
        "shared_official_cache_entries": cache_entries,
        "resources": resources,
        "services": service_results,
        "policy": registry.get("policy") or {},
    }
    atomic_json(PERFORMANCE_PATH, performance)
    latest = read_json(DATA / "latest.json", {})
    latest["runtime_architecture"] = {
        "id": RUNTIME_ID,
        "architecture": registry.get("architecture"),
        "production_contract": registry.get("production_contract"),
        "transport": registry.get("transport"),
        "service_count": len(registry.get("services") or {}),
        "execution_profile": profile,
        "dependency_aware_scheduling": True,
        "generic_root_scheduling": True,
        "shared_official_cache": True,
        "artifact_contract_validation": True,
        "service_reuse_enabled": bool(profile_cfg.get("reuse_services")),
        "total_wall_ms": round(total_ms, 3),
        "performance_target_ms": round(target_ms, 3) if target_ms else None,
        "legacy_ceiling_ms": round(ceiling_ms, 3) if ceiling_ms else None,
        "within_target_slo": performance["within_target_slo"],
        "within_target_budget": performance["within_target_budget"],
        "resources": resources,
    }
    latest.setdefault("files", {})["runtime_performance"] = "data/runtime_performance.json"
    atomic_json(DATA / "latest.json", latest)
    return performance


def _default_profile(mode: str, deep_stats: bool) -> str:
    explicit = os.getenv("FPL_EXECUTION_PROFILE", "").strip()
    if explicit:
        return explicit
    if deep_stats:
        return "deep_stats"
    if mode == "live":
        return "live"
    return "full_refresh"


def run(mode: str = "daily", stats: bool = True, deep_stats: bool = False, profile: str | None = None) -> dict[str, Any]:
    registry = _load_registry()
    _validate_dag(registry)
    profiles = _load_profiles().get("profiles") or {}
    profile_name = str(profile or _default_profile(mode, deep_stats))
    profile_cfg = profiles.get(profile_name)
    if not isinstance(profile_cfg, dict):
        raise RuntimeError(f"unknown execution profile: {profile_name}")

    services = registry["services"]
    runtime = registry.get("runtime") or {}
    max_workers = max(1, int(profile_cfg.get("max_parallel_services") or runtime.get("max_parallel_services") or 1))
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
    service_results: dict[str, dict[str, Any]] = {}
    completed: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="fpl-v3-services-") as tmp:
        temp_root = Path(tmp)
        services_root = temp_root / "services"
        configured_cache = os.getenv("FPL_RUNTIME_CACHE_DIR", "").strip()
        cache_dir = Path(configured_cache).expanduser().resolve() / "official" if configured_cache else temp_root / "official-cache"
        services_root.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        pending = set(services)
        running: dict[Any, str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            while pending or running:
                ready = [
                    name for name in sorted(pending)
                    if set(str(dep) for dep in services[name].get("depends_on") or []).issubset(completed)
                ]

                reused_any = False
                for name in list(ready):
                    reused = _reuse_service(name, services[name], DATA, profile_cfg)
                    if reused is not None:
                        pending.remove(name)
                        service_results[name] = reused
                        completed.add(name)
                        reused_any = True
                if reused_any:
                    continue

                for name in ready:
                    if name not in pending:
                        continue
                    if len(running) >= max_workers:
                        break
                    pending.remove(name)
                    submitted_at = time.perf_counter()
                    running[
                        pool.submit(
                            _run_service,
                            name,
                            services[name],
                            canonical=DATA,
                            services_root=services_root,
                            cache_dir=cache_dir,
                            context=context,
                            timeout=timeout,
                            submitted_at=submitted_at,
                        )
                    ] = name
                if not running:
                    if pending:
                        blocked = {name: services[name].get("depends_on") for name in pending}
                        raise RuntimeError(f"service DAG stalled: {blocked}")
                    break
                done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                for future in done:
                    name = running.pop(future)
                    result = future.result()
                    spec = services[name]
                    if result["status"] == "SUCCESS":
                        result = _attempt_promotion(name, result, spec, DATA)
                    service_results[name] = result
                    if result["status"] == "SUCCESS":
                        completed.add(name)
                    elif bool(spec.get("critical", True)):
                        for pending_future in running:
                            pending_future.cancel()
                        raise RuntimeError(f"critical service {name} failed: {result.get('error')}")
                    else:
                        result["discarded_stale_outputs"] = _clear_failed_service_outputs(DATA, spec)
                        service_results[name] = result
                        completed.add(name)

        total_ms = (time.perf_counter() - wall_started) * 1000.0
        performance = _write_runtime_metadata(
            registry,
            service_results,
            total_ms,
            cache_dir,
            profile_name,
            profile_cfg,
            temp_root,
        )
        performance["ephemeral_artifacts_removed"] = _cleanup_ephemeral(registry, DATA)
        atomic_json(PERFORMANCE_PATH, performance)

    print(json.dumps({
        "runtime": RUNTIME_ID,
        "architecture": registry.get("architecture"),
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "execution_profile": profile_name,
        "total_wall_ms": performance["total_wall_ms"],
        "target_wall_ms": performance.get("target_wall_ms"),
        "within_target_slo": performance.get("within_target_slo"),
        "within_target_budget": performance["within_target_budget"],
        "services": {
            name: {
                "status": row.get("status"),
                "elapsed_ms": row.get("elapsed_ms"),
                "reuse_age_seconds": row.get("reuse_age_seconds"),
            }
            for name, row in service_results.items()
        },
        "resources": performance.get("resources"),
        "shared_official_cache_entries": performance["shared_official_cache_entries"],
        "ephemeral_artifacts_removed": performance.get("ephemeral_artifacts_removed"),
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
