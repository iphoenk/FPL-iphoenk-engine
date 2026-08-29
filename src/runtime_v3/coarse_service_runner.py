from __future__ import annotations

import argparse
import contextlib
import io
import json
import runpy
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from src.runtime_v3 import incremental_reuse
from src.runtime_v3 import orchestrator as legacy
from src.runtime_v3.registry_compiler import EXECUTION_REGISTRY, IMPLEMENTATION_CATALOG
from src.utils import DATA

_RESULT_PREFIX = "V3_COARSE_SERVICE_RESULT="


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid registry: {path}")
    return payload


def _expand_args(values: list[Any], context: dict[str, str]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value)
        for key, replacement in context.items():
            text = text.replace("{" + key + "}", replacement)
        if text:
            out.append(text)
    return out


def _run_module(module: str, args: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    original_argv = list(sys.argv)
    stdout = io.StringIO()
    stderr = io.StringIO()
    rc = 0
    try:
        sys.argv = [module, *args]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                runpy.run_module(module, run_name="__main__", alter_sys=False)
            except SystemExit as exc:
                code = exc.code
                rc = int(code) if isinstance(code, int) else (0 if code in {None, ""} else 1)
    finally:
        sys.argv = original_argv
    result = {
        "type": "in_process_module",
        "descriptor": module,
        "argv": [module, *args],
        "returncode": rc,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "stdout_tail": stdout.getvalue()[-4000:],
        "stderr_tail": stderr.getvalue()[-4000:]
    }
    if rc != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def _run_command(command: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    if command.get("copy"):
        source_name, target_name = [str(value) for value in command["copy"]]
        source = DATA / source_name
        target = DATA / target_name
        if not source.exists():
            raise RuntimeError(f"copy source missing: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        shutil.copy2(source, target)
        return {
            "type": "copy",
            "source": source_name,
            "target": target_name,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "bytes": target.stat().st_size
        }
    module = str(command.get("module") or "").strip()
    if not module:
        raise RuntimeError(f"unsupported implementation command: {command}")
    return _run_module(module, _expand_args(list(command.get("args") or []), context))


def _run_implementation_step(
    step_id: str,
    spec: dict[str, Any],
    context: dict[str, str],
    profile_name: str,
    profile_cfg: dict[str, Any]
) -> dict[str, Any]:
    reuse_active = incremental_reuse.active(profile_name, step_id)
    reuse_diagnostic_before = (
        incremental_reuse.diagnose(step_id, profile_name)
        if step_id in (incremental_reuse._registry().get("services") or {})
        else None
    )
    reused = legacy._reuse_service(step_id, spec, DATA, profile_cfg)
    if reused is None and reuse_active:
        reused = incremental_reuse.try_reuse(step_id, spec, profile_name)
    if reused is not None:
        reused["runtime_owner"] = False
        reused["implementation_step"] = True
        reused["execution_boundary"] = "COARSE_CAPABILITY_PROCESS"
        if reuse_diagnostic_before is not None:
            reused["reuse_diagnostic_before"] = reuse_diagnostic_before
        return reused

    input_fingerprint = incremental_reuse.fingerprint(step_id) if reuse_active else None
    started = time.perf_counter()
    commands: list[dict[str, Any]] = []
    try:
        for command in spec.get("commands") or []:
            commands.append(_run_command(command, context))
        result = {
            "service": step_id,
            "status": "SUCCESS",
            "isolated": False,
            "data_dir": str(DATA),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "queue_wait_ms": 0.0,
            "seed_input_ms": 0.0,
            "seed_input_bytes": 0,
            "commands": commands,
            "runtime_owner": False,
            "implementation_step": True,
            "execution_boundary": "COARSE_CAPABILITY_PROCESS"
        }
        if reuse_diagnostic_before is not None:
            result["reuse_diagnostic_before"] = reuse_diagnostic_before
        if input_fingerprint:
            result["input_fingerprint_before"] = input_fingerprint
        validation_started = time.perf_counter()
        result["artifact_validation"] = legacy._validate_service_outputs(
            step_id, result, {**spec, "isolated": False}
        )
        result["validation_ms"] = round((time.perf_counter() - validation_started) * 1000.0, 3)
        result["promotion_ms"] = 0.0
        result["promoted_output_bytes"] = 0
        if reuse_active:
            incremental_reuse.record(step_id, profile_name, input_fingerprint)
        return result
    except Exception as exc:
        result = {
            "service": step_id,
            "status": "FAILED",
            "isolated": False,
            "data_dir": str(DATA),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "queue_wait_ms": 0.0,
            "seed_input_ms": 0.0,
            "seed_input_bytes": 0,
            "commands": commands,
            "runtime_owner": False,
            "implementation_step": True,
            "execution_boundary": "COARSE_CAPABILITY_PROCESS",
            "error": f"{type(exc).__name__}: {exc}"
        }
        if reuse_diagnostic_before is not None:
            result["reuse_diagnostic_before"] = reuse_diagnostic_before
        return result


def run_service(service_id: str, mode: str, stats: bool, deep_stats: bool, profile_name: str) -> dict[str, Any]:
    execution = _load(EXECUTION_REGISTRY)
    implementation = _load(IMPLEMENTATION_CATALOG)
    service = (execution.get("services") or {}).get(service_id)
    if not isinstance(service, dict):
        raise RuntimeError(f"unknown coarse runtime service: {service_id}")
    profile_cfg = (legacy._load_profiles().get("profiles") or {}).get(profile_name)
    if not isinstance(profile_cfg, dict):
        raise RuntimeError(f"unknown execution profile: {profile_name}")
    legacy_services = implementation.get("services") or {}
    steps = [str(value) for value in service.get("implementation_steps") or []]
    context = {
        "mode": mode,
        "stats": "--stats" if stats else "--no-stats",
        "deep_stats": "--deep-stats" if deep_stats else "",
        "http_cache_ttl": str((implementation.get("runtime") or {}).get("http_cache_ttl_seconds") or 180),
        "profile": profile_name
    }
    results: dict[str, dict[str, Any]] = {}
    completed: set[str] = set()
    started = time.perf_counter()
    for step_id in steps:
        spec = legacy_services.get(step_id)
        if not isinstance(spec, dict):
            raise RuntimeError(f"missing implementation catalog row: {service_id}:{step_id}")
        internal_dependencies = {
            str(dep) for dep in spec.get("depends_on") or [] if str(dep) in steps
        }
        missing = sorted(internal_dependencies - completed)
        if missing:
            raise RuntimeError(
                f"coarse service internal dependency violation: {service_id}:{step_id} missing={missing}"
            )
        result = _run_implementation_step(step_id, spec, context, profile_name, profile_cfg)
        results[step_id] = result
        if result.get("status") not in {"SUCCESS", "REUSED"}:
            if bool(spec.get("critical", True)):
                raise RuntimeError(f"critical implementation step {step_id} failed: {result.get('error')}")
            result["discarded_stale_outputs"] = legacy._clear_failed_service_outputs(DATA, spec)
        completed.add(step_id)
    return {
        "service_id": service_id,
        "status": "SUCCESS",
        "phase": service.get("phase"),
        "stage": service.get("stage"),
        "runtime_owner": True,
        "implementation_steps": steps,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "results": results
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--mode", choices=["daily", "deadline", "live"], default="daily")
    parser.add_argument("--stats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--deep-stats", action="store_true")
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    out = run_service(args.service, args.mode, args.stats, args.deep_stats, args.profile)
    print(_RESULT_PREFIX + json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
