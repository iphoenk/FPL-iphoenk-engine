from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import runpy
import shutil
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.runtime_v3 import incremental_reuse
from src.runtime_v3 import module_batch_runner
from src.runtime_v3 import orchestrator as legacy
from src.utils import DATA, ROOT

DOMAIN_PATH = ROOT / "config" / "runtime" / "execution_domains.json"


@lru_cache(maxsize=1)
def _domains() -> dict[str, Any]:
    payload = json.loads(DOMAIN_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_EXECUTION_DOMAINS_V2":
        raise RuntimeError("unexpected execution domain registry")
    return payload.get("domains") or {}


@lru_cache(maxsize=1)
def _service_registry() -> dict[str, Any]:
    return legacy._load_registry()


@lru_cache(maxsize=1)
def _profiles() -> dict[str, Any]:
    return legacy._load_profiles()


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
        "stderr_tail": stderr.getvalue()[-4000:],
    }
    if rc != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def _run_command(command: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    if command.get("copy"):
        source_name, target_name = [str(x) for x in command["copy"]]
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
            "bytes": target.stat().st_size,
        }
    module = str(command.get("module") or "").strip()
    if not module:
        raise RuntimeError(f"unsupported service command: {command}")
    return _run_module(module, _expand_args(list(command.get("args") or []), context))


def _reuse_candidate(
    mode: str,
    loader: Any,
    service_name: str,
    spec: dict[str, Any],
    profile_name: str,
    profile_cfg: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Load reusable state, converting schema/contract drift into a cache miss.

    Reuse is an optimization only. A stale artifact that no longer satisfies the
    current artifact contract must never be accepted, but it also must not block
    the owning capability from refreshing the artifact under the new contract.
    """
    try:
        if mode == "TTL":
            return loader(service_name, spec, DATA, profile_cfg), None
        return loader(service_name, spec, profile_name), None
    except Exception as exc:
        return None, {
            "mode": mode,
            "reason": "ARTIFACT_CONTRACT_REJECTED",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _run_service(name: str, spec: dict[str, Any], context: dict[str, str], profile_name: str, profile_cfg: dict[str, Any]) -> dict[str, Any]:
    reuse_active = incremental_reuse.active(profile_name, name)
    reuse_diagnostic_before = incremental_reuse.diagnose(name, profile_name) if name in (incremental_reuse._registry().get("services") or {}) else None
    reuse_rejections: list[dict[str, Any]] = []

    reused, rejected = _reuse_candidate("TTL", legacy._reuse_service, name, spec, profile_name, profile_cfg)
    if rejected is not None:
        reuse_rejections.append(rejected)
    if reused is None and reuse_active:
        reused, rejected = _reuse_candidate("CONTENT_ADDRESSED", incremental_reuse.try_reuse, name, spec, profile_name, profile_cfg)
        if rejected is not None:
            reuse_rejections.append(rejected)
    if reused is not None:
        reused["execution_boundary"] = "DOMAIN_PROCESS"
        if reuse_diagnostic_before is not None:
            reused["reuse_diagnostic_before"] = reuse_diagnostic_before
        if reuse_rejections:
            reused["reuse_rejections"] = reuse_rejections
        return reused

    input_fingerprint = incremental_reuse.fingerprint(name) if reuse_active else None
    started = time.perf_counter()
    commands: list[dict[str, Any]] = []
    try:
        batches = module_batch_runner._registry().get("batches") or {}
        if name in batches:
            batch_started = time.perf_counter()
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                batch = module_batch_runner.run_batch(name, context)
            commands.append({
                "type": "in_process_batch",
                "descriptor": name,
                "returncode": 0,
                "elapsed_ms": round((time.perf_counter() - batch_started) * 1000.0, 3),
                "stdout_tail": captured.getvalue()[-4000:],
                "executed": batch.get("executed") or [],
            })
            batched = True
        else:
            for command in spec.get("commands") or []:
                commands.append(_run_command(command, context))
            batched = False
        result = {
            "service": name,
            "status": "SUCCESS",
            "isolated": False,
            "data_dir": str(DATA),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "queue_wait_ms": 0.0,
            "seed_input_ms": 0.0,
            "seed_input_bytes": 0,
            "commands": commands,
            "execution_boundary": "DOMAIN_PROCESS",
        }
        if reuse_diagnostic_before is not None:
            result["reuse_diagnostic_before"] = reuse_diagnostic_before
        if reuse_rejections:
            result["reuse_rejections"] = reuse_rejections
        if batched:
            result["single_process_module_batch"] = True
        if input_fingerprint:
            result["input_fingerprint_before"] = input_fingerprint
        validation_started = time.perf_counter()
        result["artifact_validation"] = legacy._validate_service_outputs(name, result, {**spec, "isolated": False})
        result["validation_ms"] = round((time.perf_counter() - validation_started) * 1000.0, 3)
        result["promotion_ms"] = 0.0
        result["promoted_output_bytes"] = 0
        if reuse_active:
            incremental_reuse.record(name, profile_name, input_fingerprint)
        return result
    except Exception as exc:
        result = {
            "service": name,
            "status": "FAILED",
            "isolated": False,
            "data_dir": str(DATA),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "queue_wait_ms": 0.0,
            "seed_input_ms": 0.0,
            "seed_input_bytes": 0,
            "commands": commands,
            "execution_boundary": "DOMAIN_PROCESS",
            "error": f"{type(exc).__name__}: {exc}",
        }
        if reuse_diagnostic_before is not None:
            result["reuse_diagnostic_before"] = reuse_diagnostic_before
        if reuse_rejections:
            result["reuse_rejections"] = reuse_rejections
        return result


def run_domain(domain_name: str, mode: str, stats: bool, deep_stats: bool, profile_name: str) -> dict[str, Any]:
    registry = _service_registry()
    profile_cfg = (_profiles().get("profiles") or {}).get(profile_name)
    if not isinstance(profile_cfg, dict):
        raise RuntimeError(f"unknown execution profile: {profile_name}")
    domain = _domains().get(domain_name)
    if not isinstance(domain, dict):
        raise RuntimeError(f"unknown execution domain: {domain_name}")
    context = {
        "mode": mode,
        "stats": "--stats" if stats else "--no-stats",
        "deep_stats": "--deep-stats" if deep_stats else "",
        "http_cache_ttl": str((registry.get("runtime") or {}).get("http_cache_ttl_seconds") or 180),
        "profile": profile_name,
    }
    services = registry.get("services") or {}
    results: dict[str, dict[str, Any]] = {}
    completed: set[str] = set()
    capabilities = [str(x) for x in domain.get("capabilities") or []]
    domain_started = time.perf_counter()
    for name in capabilities:
        spec = services[name]
        internal_deps = {str(dep) for dep in spec.get("depends_on") or [] if str(dep) in capabilities}
        missing = sorted(internal_deps - completed)
        if missing:
            raise RuntimeError(f"domain internal dependency violation: {domain_name}:{name} missing={missing}")
        result = _run_service(name, spec, context, profile_name, profile_cfg)
        results[name] = result
        if result.get("status") not in {"SUCCESS", "REUSED"} and bool(spec.get("critical", True)):
            raise RuntimeError(f"critical capability {name} failed: {result.get('error')}")
        if result.get("status") not in {"SUCCESS", "REUSED"}:
            result["discarded_stale_outputs"] = legacy._clear_failed_service_outputs(DATA, spec)
        completed.add(name)
    return {
        "domain": domain_name,
        "status": "SUCCESS",
        "elapsed_ms": round((time.perf_counter() - domain_started) * 1000.0, 3),
        "capabilities": capabilities,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--mode", choices=["daily", "deadline", "live"], default="daily")
    parser.add_argument("--stats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--deep-stats", action="store_true")
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    out = run_domain(args.domain, args.mode, args.stats, args.deep_stats, args.profile)
    print("V3_DOMAIN_RESULT=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
