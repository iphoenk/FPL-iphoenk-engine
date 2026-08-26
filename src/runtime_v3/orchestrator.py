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

from src.runtime_v3 import RUNTIME_ID
from src.utils import DATA, ROOT, atomic_json, read_json
from src.version import ENGINE_VERSION, SCHEMA_VERSION

REGISTRY_PATH = ROOT / "config" / "v3_service_registry.json"
PERFORMANCE_PATH = DATA / "runtime_performance.json"


def _load_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    services = payload.get("services")
    if not isinstance(services, dict) or "collector" not in services or "governance" not in services:
        raise RuntimeError("invalid V3 service registry")
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


def _run_command(command: dict[str, Any], *, data_dir: Path, cache_dir: Path, context: dict[str, str], timeout: int) -> dict[str, Any]:
    if command.get("copy"):
        source_name, target_name = [str(x) for x in command["copy"]]
        source = data_dir / source_name
        target = data_dir / target_name
        if not source.exists():
            raise RuntimeError(f"copy source missing: {source}")
        shutil.copy2(source, target)
        return {"type": "copy", "source": source_name, "target": target_name, "elapsed_ms": 0.0}

    if command.get("module"):
        cmd = [sys.executable, "-m", str(command["module"]), *_expand_args(list(command.get("args") or []), context)]
        descriptor = str(command["module"])
    elif command.get("code"):
        cmd = [sys.executable, "-c", str(command["code"])]
        descriptor = "python-code"
    else:
        raise RuntimeError(f"unsupported service command: {command}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["FPL_DATA_DIR"] = str(data_dir)
    env["FPL_HTTP_CACHE_DIR"] = str(cache_dir)
    env["FPL_HTTP_CACHE_TTL_SECONDS"] = context["http_cache_ttl"]
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


def _seed_service_data(service_name: str, spec: dict[str, Any], canonical: Path, service_root: Path) -> Path:
    target = service_root / service_name
    target.mkdir(parents=True, exist_ok=True)
    for name in spec.get("inputs") or []:
        source = canonical / str(name)
        if source.exists():
            destination = target / str(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    return target


def _run_service(service_name: str, spec: dict[str, Any], *, canonical: Path, services_root: Path, cache_dir: Path, context: dict[str, str], timeout: int) -> dict[str, Any]:
    isolated = bool(spec.get("isolated", True))
    data_dir = _seed_service_data(service_name, spec, canonical, services_root) if isolated else canonical
    started = time.perf_counter()
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
            "commands": commands,
        }
    except Exception as exc:
        return {
            "service": service_name,
            "status": "FAILED",
            "isolated": isolated,
            "data_dir": str(data_dir),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
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


def _promote(service_name: str, result: dict[str, Any], spec: dict[str, Any], canonical: Path) -> None:
    if not result.get("isolated"):
        return
    service_dir = Path(str(result["data_dir"]))
    for name in spec.get("artifacts") or []:
        source = service_dir / str(name)
        if not source.exists():
            raise RuntimeError(f"service {service_name} did not produce required artifact {name}")
        destination = canonical / str(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    _merge_latest(canonical, service_dir, spec)


def _write_runtime_metadata(registry: dict[str, Any], service_results: dict[str, dict[str, Any]], total_ms: float, cache_dir: Path) -> dict[str, Any]:
    cache_entries = len(list(cache_dir.glob("*.json"))) if cache_dir.exists() else 0
    runtime = registry.get("runtime") or {}
    budget_ms = float(runtime.get("performance_budget_seconds") or 0) * 1000.0
    performance = {
        "runtime_id": RUNTIME_ID,
        "architecture": registry.get("architecture"),
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "total_wall_ms": round(total_ms, 3),
        "performance_budget_ms": round(budget_ms, 3) if budget_ms else None,
        "within_target_budget": total_ms <= budget_ms if budget_ms else None,
        "shared_official_cache_entries": cache_entries,
        "services": service_results,
        "policy": registry.get("policy") or {},
    }
    atomic_json(PERFORMANCE_PATH, performance)
    latest = read_json(DATA / "latest.json", {})
    latest["runtime_architecture"] = {
        "id": RUNTIME_ID,
        "architecture": registry.get("architecture"),
        "transport": registry.get("transport"),
        "service_count": len(registry.get("services") or {}),
        "dependency_aware_scheduling": True,
        "shared_official_cache": True,
        "total_wall_ms": round(total_ms, 3),
        "performance_target_ms": round(budget_ms, 3) if budget_ms else None,
        "within_target_budget": performance["within_target_budget"],
    }
    latest.setdefault("files", {})["runtime_performance"] = "data/runtime_performance.json"
    atomic_json(DATA / "latest.json", latest)
    return performance


def run(mode: str = "daily", stats: bool = True, deep_stats: bool = False) -> dict[str, Any]:
    registry = _load_registry()
    _validate_dag(registry)
    services = registry["services"]
    runtime = registry.get("runtime") or {}
    max_workers = int(runtime.get("max_parallel_services") or 4)
    timeout = int(runtime.get("service_timeout_seconds") or 180)
    context = {
        "mode": mode,
        "stats": "--stats" if stats else "",
        "deep_stats": "--deep-stats" if deep_stats else "",
        "http_cache_ttl": str(int(runtime.get("http_cache_ttl_seconds") or 180)),
    }
    wall_started = time.perf_counter()
    service_results: dict[str, dict[str, Any]] = {}
    completed: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="fpl-v3-services-") as tmp:
        temp_root = Path(tmp)
        services_root = temp_root / "services"
        cache_dir = temp_root / "official-cache"
        services_root.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        collector = _run_service("collector", services["collector"], canonical=DATA, services_root=services_root, cache_dir=cache_dir, context=context, timeout=timeout)
        service_results["collector"] = collector
        if collector["status"] != "SUCCESS":
            raise RuntimeError(f"critical collector service failed: {collector.get('error')}")
        completed.add("collector")

        pending = {name for name in services if name != "collector"}
        running: dict[Any, str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            while pending or running:
                ready = [
                    name for name in sorted(pending)
                    if set(str(x) for x in services[name].get("depends_on") or []).issubset(completed)
                ]
                for name in ready:
                    if len(running) >= max_workers:
                        break
                    pending.remove(name)
                    future = pool.submit(
                        _run_service,
                        name,
                        services[name],
                        canonical=DATA,
                        services_root=services_root,
                        cache_dir=cache_dir,
                        context=context,
                        timeout=timeout,
                    )
                    running[future] = name

                if not running:
                    if pending:
                        blocked = {name: services[name].get("depends_on") for name in pending}
                        raise RuntimeError(f"service DAG stalled: {blocked}")
                    break

                done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                for future in done:
                    name = running.pop(future)
                    result = future.result()
                    service_results[name] = result
                    spec = services[name]
                    if result["status"] == "SUCCESS":
                        _promote(name, result, spec, DATA)
                        completed.add(name)
                    elif bool(spec.get("critical", True)):
                        for pending_future in running:
                            pending_future.cancel()
                        raise RuntimeError(f"critical service {name} failed: {result.get('error')}")
                    else:
                        completed.add(name)

        total_ms = (time.perf_counter() - wall_started) * 1000.0
        performance = _write_runtime_metadata(registry, service_results, total_ms, cache_dir)

    print(json.dumps({
        "runtime": RUNTIME_ID,
        "architecture": registry.get("architecture"),
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "total_wall_ms": performance["total_wall_ms"],
        "within_target_budget": performance["within_target_budget"],
        "services": {name: {"status": row.get("status"), "elapsed_ms": row.get("elapsed_ms")} for name, row in service_results.items()},
        "shared_official_cache_entries": performance["shared_official_cache_entries"],
    }, ensure_ascii=False))
    return performance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "deadline", "live"], default="daily")
    parser.add_argument("--stats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--deep-stats", action="store_true")
    args = parser.parse_args()
    run(mode=args.mode, stats=args.stats, deep_stats=args.deep_stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
