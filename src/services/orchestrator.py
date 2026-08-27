from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from src.services.contracts import file_digest, validate_contracts
from src.utils import CONFIG, DATA, ROOT, atomic_json, iso_now, read_json

SERVICE_REGISTRY = CONFIG / "service_registry.json"
CONTRACT_REGISTRY = CONFIG / "service_contract_registry.json"
OUTFILE = DATA / "service_orchestration_v4.json"


def _ordered_services(registry: dict) -> list[dict]:
    services = list(registry.get("services") or [])
    ids = [str(service.get("id") or "") for service in services]
    if not ids or len(ids) != len(set(ids)) or any(not service_id for service_id in ids):
        raise RuntimeError("invalid or duplicate service ids")
    completed: set[str] = set()
    ordered: list[dict] = []
    remaining = services[:]
    while remaining:
        ready = [service for service in remaining if set(service.get("depends_on") or []) <= completed]
        if not ready:
            raise RuntimeError("service dependency cycle or unknown dependency")
        for service in ready:
            ordered.append(service)
            completed.add(service["id"])
            remaining.remove(service)
    return ordered


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
    services = _ordered_services(registry)
    started = time.perf_counter()
    report = {
        "schema_version": 491,
        "engine": "v4.9.1-service-orchestrator",
        "started_at": iso_now(),
        "completed_at": None,
        "status": "RUNNING",
        "mode": mode,
        "simulated": as_of is not None,
        "service_registry": registry.get("registry"),
        "contract_registry": contracts.get("registry"),
        "execution_model": registry.get("execution_model"),
        "snapshot_identity": None,
        "services": [],
        "guardrails": dict(registry.get("guardrails") or {}),
    }
    atomic_json(outfile, report)
    locked_artifacts: dict[str, str] = {}
    lock_targets = {"raw_snapshot": root / "data/runtime/snapshot.v1.json", "enrichment": root / "data/runtime/enrichment.v1.json", "prediction": root / "data/latest.json"}
    service_states: dict[str, str] = {}

    try:
        for service in services:
            service_id = service["id"]
            dependencies = service.get("depends_on") or []
            if any(service_states.get(dep) != "PASS" for dep in dependencies):
                raise RuntimeError(f"dependency not successful for {service_id}")
            for locked_path, digest in locked_artifacts.items():
                if file_digest(Path(locked_path)) != digest:
                    raise RuntimeError(f"immutable artifact changed before {service_id}: {locked_path}")

            command = _render_command(service, mode, stats, deep_stats, as_of)
            service_started = time.perf_counter()
            env = os.environ.copy()
            env["PYTHONPATH"] = str(root)
            if str(root / "data/runtime/snapshot.v1.json") in locked_artifacts:
                env["FPL_SNAPSHOT_SHA256"] = locked_artifacts[str(root / "data/runtime/snapshot.v1.json")]
            row = {
                "id": service_id,
                "name": service.get("name"),
                "boundary_state": service.get("boundary_state"),
                "status": "RUNNING",
                "depends_on": dependencies,
                "contracts": [],
            }
            report["services"].append(row)
            atomic_json(outfile, report)
            try:
                result = runner(
                    command,
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=int(service.get("timeout_seconds") or 60),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                row.update({"status": "FAIL", "error": "timeout", "stdout_tail": _tail(exc.stdout or ""), "stderr_tail": _tail(exc.stderr or "")})
                service_states[service_id] = "FAIL"
                raise RuntimeError(f"service timeout: {service_id}") from exc

            row["duration_ms"] = round((time.perf_counter() - service_started) * 1000, 2)
            row["exit_code"] = result.returncode
            row["stdout_tail"] = _tail(result.stdout)
            row["stderr_tail"] = _tail(result.stderr)
            if result.returncode != 0:
                row["status"] = "FAIL"
                service_states[service_id] = "FAIL"
                raise RuntimeError(f"service failed: {service_id} exit={result.returncode}")

            for locked_path, digest in locked_artifacts.items():
                if file_digest(Path(locked_path)) != digest:
                    raise RuntimeError(f"immutable snapshot changed during {service_id}: {locked_path}")

            validation = validate_contracts(list(service.get("produces") or []), contracts, root=root)
            row["contracts"] = validation
            if not all(item.get("valid") for item in validation):
                row["status"] = "FAIL"
                service_states[service_id] = "FAIL"
                raise RuntimeError(f"contract validation failed: {service_id}")

            # Backward-compatible custom registries lock their first latest snapshot.
            if not locked_artifacts and "latest" in (service.get("produces") or []):
                target = root / "data/latest.json"
                digest = file_digest(target)
                locked_artifacts[str(target)] = digest
                report["snapshot_identity"] = {"sha256": digest, "generated_at": read_json(target, {}).get("generated_at")}

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
            atomic_json(outfile, report)

        report["status"] = "PASS"
        report["completed_at"] = iso_now()
        report["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        report["summary"] = {"services_passed": len(services), "services_total": len(services), "fail_closed": True}
        atomic_json(outfile, report)
        report["locked_artifacts"] = {str(Path(path).relative_to(root)): digest for path, digest in locked_artifacts.items()}
        atomic_json(outfile, report)
        print(json.dumps({"orchestrator": "PASS", "services": len(services), "duration_ms": report["duration_ms"], "snapshot": (report.get("snapshot_identity") or {}).get("sha256"), "simulated": report["simulated"]}, ensure_ascii=False))
        return report
    except Exception as exc:
        report["status"] = "FAIL"
        report["completed_at"] = iso_now()
        report["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        report["error"] = str(exc)
        report["summary"] = {"services_passed": sum(state == "PASS" for state in service_states.values()), "services_total": len(services), "fail_closed": True}
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
