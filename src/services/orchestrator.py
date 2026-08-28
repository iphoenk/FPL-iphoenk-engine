from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from src.services.contracts import file_digest, validate_contracts
from src.utils import CONFIG, DATA, ROOT, atomic_json, iso_now, read_json

SERVICE_REGISTRY = CONFIG / "service_registry.json"
CONTRACT_REGISTRY = CONFIG / "service_contract_registry.json"
OUTFILE = DATA / "service_orchestration_v4.json"


def _service_levels(registry: dict) -> list[list[dict]]:
    services = list(registry.get("services") or [])
    ids = [str(service.get("id") or "") for service in services]
    if not ids or len(ids) != len(set(ids)) or any(not service_id for service_id in ids):
        raise RuntimeError("invalid or duplicate service ids")
    known = set(ids)
    for service in services:
        unknown = set(service.get("depends_on") or []) - known
        if unknown:
            raise RuntimeError(f"unknown service dependency for {service['id']}: {sorted(unknown)}")

    completed: set[str] = set()
    levels: list[list[dict]] = []
    remaining = services[:]
    while remaining:
        ready = [service for service in remaining if set(service.get("depends_on") or []) <= completed]
        if not ready:
            raise RuntimeError("service dependency cycle")
        levels.append(ready)
        completed.update(service["id"] for service in ready)
        remaining = [service for service in remaining if service not in ready]
    return levels


def _ordered_services(registry: dict) -> list[dict]:
    return [service for level in _service_levels(registry) for service in level]


def _render_command(service: dict, mode: str, stats: bool, deep_stats: bool, as_of: str | None) -> list[str]:
    values = {"python": sys.executable, "mode": mode}
    command = [str(part).format(**values) for part in service.get("command") or []]
    flags = service.get("runtime_flags") or {}
    if stats and flags.get("stats"):
        command.append(flags["stats"])
    if deep_stats and flags.get("deep_stats"):
        command.append(flags["deep_stats"])
    if as_of and flags.get("as_of"):
        command.extend([flags["as_of"], as_of])
    if not command:
        raise RuntimeError(f"service command missing: {service.get('id')}")
    return command


def _tail(value: str, limit: int = 1200) -> str:
    value = (value or "").strip()
    return value[-limit:]


def _assert_locked_artifacts(locked_artifacts: dict[str, str], stage: str) -> None:
    for locked_path, digest in locked_artifacts.items():
        if file_digest(Path(locked_path)) != digest:
            raise RuntimeError(f"immutable snapshot changed {stage}: {locked_path}")


def _service_env(root: Path, locked_artifacts: dict[str, str]) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    snapshot_path = str(root / "data/runtime/snapshot.v1.json")
    if snapshot_path in locked_artifacts:
        env["FPL_SNAPSHOT_SHA256"] = locked_artifacts[snapshot_path]
    return env


def orchestrate(
    mode: str = "daily",
    stats: bool = False,
    deep_stats: bool = False,
    as_of: str | None = None,
    service_registry: dict | None = None,
    contract_registry: dict | None = None,
    runner: Callable = subprocess.run,
    root: Path = ROOT,
    outfile: Path = OUTFILE,
) -> dict:
    registry = service_registry or read_json(SERVICE_REGISTRY, {})
    contracts = contract_registry or read_json(CONTRACT_REGISTRY, {})
    levels = _service_levels(registry)
    services = [service for level in levels for service in level]
    level_by_id = {
        service["id"]: level_index
        for level_index, level in enumerate(levels)
        for service in level
    }
    order_index = {service["id"]: index for index, service in enumerate(services)}
    started = time.perf_counter()
    report = {
        "schema_version": 495,
        "engine": "v4.9.5-service-orchestrator-dag-parallel",
        "started_at": iso_now(),
        "completed_at": None,
        "status": "RUNNING",
        "mode": mode,
        "simulated": as_of is not None,
        "stats_enabled": stats,
        "deep_stats_enabled": deep_stats,
        "service_registry": registry.get("registry"),
        "contract_registry": contracts.get("registry"),
        "execution_model": registry.get("execution_model"),
        "scheduler": "dependency_ready_no_level_barrier",
        "execution_levels": [[service["id"] for service in level] for level in levels],
        "launch_order": [],
        "completion_order": [],
        "snapshot_identity": None,
        "services": [],
        "guardrails": dict(registry.get("guardrails") or {}),
    }
    atomic_json(outfile, report)

    locked_artifacts: dict[str, str] = {}
    lock_targets = {
        "raw_snapshot": root / "data/runtime/snapshot.v1.json",
        "enrichment": root / "data/runtime/enrichment.v1.json",
        "prediction": root / "data/latest.json",
    }
    service_states: dict[str, str] = {}
    pending = {service["id"]: service for service in services}
    max_workers = max(1, max(len(level) for level in levels))

    try:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="v4-dag") as pool:
            running: dict[Future, tuple[dict, dict, float]] = {}
            while pending or running:
                launched = False
                for service in services:
                    service_id = service["id"]
                    if service_id not in pending:
                        continue
                    dependencies = service.get("depends_on") or []
                    failed_dependencies = [dep for dep in dependencies if service_states.get(dep) == "FAIL"]
                    if failed_dependencies:
                        raise RuntimeError(f"dependency not successful for {service_id}: {failed_dependencies}")
                    if not all(service_states.get(dep) == "PASS" for dep in dependencies):
                        continue

                    _assert_locked_artifacts(locked_artifacts, f"before service {service_id}")
                    row = {
                        "id": service_id,
                        "name": service.get("name"),
                        "boundary_state": service.get("boundary_state"),
                        "status": "RUNNING",
                        "depends_on": dependencies,
                        "contracts": [],
                        "execution_level": level_by_id[service_id],
                    }
                    report["services"].append(row)
                    report["launch_order"].append(service_id)
                    command = _render_command(service, mode, stats, deep_stats, as_of)
                    service_started = time.perf_counter()
                    future = pool.submit(
                        runner,
                        command,
                        cwd=root,
                        env=_service_env(root, locked_artifacts),
                        capture_output=True,
                        text=True,
                        timeout=int(service.get("timeout_seconds") or 60),
                        check=False,
                    )
                    running[future] = (service, row, service_started)
                    del pending[service_id]
                    launched = True

                if not running:
                    if pending:
                        unresolved = sorted(pending)
                        raise RuntimeError(f"no dependency-ready services: {unresolved}")
                    break

                done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda item: order_index[running[item][0]["id"]]):
                    service, row, service_started = running.pop(future)
                    service_id = service["id"]
                    row["duration_ms"] = round((time.perf_counter() - service_started) * 1000, 2)
                    try:
                        result = future.result()
                    except subprocess.TimeoutExpired as exc:
                        _assert_locked_artifacts(locked_artifacts, f"after timed-out service {service_id}")
                        row.update({
                            "status": "FAIL",
                            "error": "timeout",
                            "stdout_tail": _tail(exc.stdout or ""),
                            "stderr_tail": _tail(exc.stderr or ""),
                        })
                        service_states[service_id] = "FAIL"
                        raise RuntimeError(f"service timeout: {service_id}")
                    except Exception as exc:
                        _assert_locked_artifacts(locked_artifacts, f"after failed service {service_id}")
                        row.update({"status": "FAIL", "error": str(exc)})
                        service_states[service_id] = "FAIL"
                        raise RuntimeError(f"service runner failed: {service_id}: {exc}") from exc

                    row["exit_code"] = result.returncode
                    row["stdout_tail"] = _tail(result.stdout)
                    row["stderr_tail"] = _tail(result.stderr)
                    _assert_locked_artifacts(locked_artifacts, f"after service {service_id}")
                    if result.returncode != 0:
                        row["status"] = "FAIL"
                        service_states[service_id] = "FAIL"
                        detail = row["stderr_tail"] or row["stdout_tail"] or "no service output"
                        raise RuntimeError(
                            f"service failed: {service_id} exit={result.returncode}: {detail}"
                        )

                    row["status"] = "PROCESS_PASS"
                    validation = validate_contracts(list(service.get("produces") or []), contracts, root=root)
                    row["contracts"] = validation
                    if not all(item.get("valid") for item in validation):
                        row["status"] = "FAIL"
                        service_states[service_id] = "FAIL"
                        raise RuntimeError(f"contract validation failed: {service_id}")

                    if not locked_artifacts and "latest" in (service.get("produces") or []):
                        target = root / "data/latest.json"
                        digest = file_digest(target)
                        locked_artifacts[str(target)] = digest
                        report["snapshot_identity"] = {
                            "sha256": digest,
                            "generated_at": read_json(target, {}).get("generated_at"),
                        }

                    if service_id in lock_targets:
                        target = lock_targets[service_id]
                        digest = file_digest(target)
                        locked_artifacts[str(target)] = digest
                        row["locked_artifact"] = {"path": str(target.relative_to(root)), "sha256": digest}
                    if service_id == "raw_snapshot":
                        latest = read_json(lock_targets[service_id], {})
                        report["snapshot_identity"] = {
                            "sha256": locked_artifacts[str(lock_targets[service_id])],
                            "generated_at": latest.get("generated_at"),
                            "checkpoint_policy_id": (latest.get("checkpoint_context") or {}).get("policy_id"),
                        }

                    row["status"] = "PASS"
                    service_states[service_id] = "PASS"
                    report["completion_order"].append(service_id)

        report["status"] = "PASS"
        report["completed_at"] = iso_now()
        report["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        report["runtime_target"] = {
            "target_ms": 5000.0,
            "actual_ms": report["duration_ms"],
            "status": "PASS" if report["duration_ms"] < 5000 else "ABOVE_TARGET",
            "hard_gate": False,
            "reason": "full orchestration includes Official/community network latency; deterministic decision compute remains the hard <5s gate",
        }
        report["summary"] = {
            "services_passed": len(services),
            "services_total": len(services),
            "levels": len(levels),
            "parallel_levels": sum(len(level) > 1 for level in levels),
            "max_workers": max_workers,
            "scheduler_barrier_free": True,
            "fail_closed": True,
        }
        report["locked_artifacts"] = {
            str(Path(path).relative_to(root)): digest for path, digest in locked_artifacts.items()
        }
        atomic_json(outfile, report)
        print(json.dumps({
            "orchestrator": "PASS",
            "services": len(services),
            "levels": len(levels),
            "parallel_levels": report["summary"]["parallel_levels"],
            "scheduler": report["scheduler"],
            "duration_ms": report["duration_ms"],
            "runtime_target": report["runtime_target"]["status"],
            "snapshot": (report.get("snapshot_identity") or {}).get("sha256"),
            "simulated": report["simulated"],
            "stats": stats,
            "deep_stats": deep_stats,
        }, ensure_ascii=False))
        return report
    except Exception as exc:
        report["status"] = "FAIL"
        report["completed_at"] = iso_now()
        report["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        report["error"] = str(exc)
        report["summary"] = {
            "services_passed": sum(state == "PASS" for state in service_states.values()),
            "services_total": len(services),
            "levels": len(levels),
            "scheduler_barrier_free": True,
            "fail_closed": True,
        }
        atomic_json(outfile, report)
        raise


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=("daily", "deadline", "live"), default="daily")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--deep-stats", action="store_true")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    return orchestrate(args.mode, args.stats, args.deep_stats, args.as_of)


if __name__ == "__main__":
    cli()
