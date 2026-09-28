from __future__ import annotations

"""Non-authoritative PERF-B / PERF-C exploratory harness.

This module is deliberately isolated from production runtime selection.  It
benchmarks exact canonical code paths and emits public-safe timing/fingerprint
evidence only.  It never publishes a decision or writes to the private repo.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from copy import deepcopy
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import pickle
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "performance" / "v12_perf_bc.json"

NORMALIZED_DISABLE = (
    "X86_V4,AVX512F,AVX512CD,AVX512_KNL,AVX512_KNM,"
    "AVX512_SKX,AVX512_CLX,AVX512_CNL,AVX512_ICL,AVX512_SPR"
)
EPHEMERAL_KEYS = {
    "elapsed_seconds",
    "wall_seconds",
    "path_throughput_per_second",
    "load_or_build_seconds",
    "generated_at",
    "observed_at",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
}


def _config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    elif isinstance(value, bytes):
        payload = value
    else:
        payload = _canonical_json(value)
    return hashlib.sha256(payload).hexdigest()


def _semantic_strip(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _semantic_strip(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            if str(k) not in EPHEMERAL_KEYS
            and not str(k).endswith("_seconds")
            and "timing" not in str(k).lower()
        }
    if isinstance(value, list):
        return [_semantic_strip(v) for v in value]
    return value


def _runtime_identity() -> dict[str, Any]:
    from src.engines.v12_cache_runtime_identity import runtime_cache_identity
    ident = dict(runtime_cache_identity())
    cpu_model = "UNKNOWN"
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "cpu_model": cpu_model,
        "runner_os": os.getenv("RUNNER_OS"),
        "runner_arch": os.getenv("RUNNER_ARCH"),
        "runner_image_os": os.getenv("ImageOS"),
        "runner_image_version": os.getenv("ImageVersion"),
        "numeric_runtime": ident,
    }


def _peak_memory_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return value / (1024.0 * 1024.0)
    return value / 1024.0


def _normalized_env() -> dict[str, str]:
    env = dict(os.environ)
    env["OPENBLAS_CORETYPE"] = "Haswell"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["NPY_DISABLE_CPU_FEATURES"] = NORMALIZED_DISABLE
    env["V12_PRIVATE_CACHE_PROFILE"] = "SECURE_NO_PERSONAL_CACHE"
    env.pop("FPL_V12_PRIVATE_CACHE_KEY_B64", None)
    return env


def _native_mc_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("OPENBLAS_CORETYPE", None)
    env.pop("NPY_DISABLE_CPU_FEATURES", None)
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["V12_PRIVATE_CACHE_PROFILE"] = "SECURE_NO_PERSONAL_CACHE"
    env.pop("FPL_V12_PRIVATE_CACHE_KEY_B64", None)
    env.pop("V12_MC_SIM_CACHE_DIR", None)
    return env


def _median(rows: Sequence[float]) -> float:
    return float(statistics.median(float(v) for v in rows))


def select_occurrence(private_root: Path, output: Path) -> int:
    rows: list[tuple[str, Path, dict[str, Any]]] = []
    for path in private_root.glob("reports/**/delivery_receipt.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("report_mode") or "").upper() != "DEEP":
            continue
        slot = str(payload.get("report_slot") or "")
        runtime_sha = str(payload.get("runtime_sha") or "")
        if slot and len(runtime_sha) == 40:
            rows.append((slot, path.parent, payload))
    if not rows:
        raise RuntimeError("no private DEEP delivery receipt found")
    rows.sort(key=lambda item: item[0])
    slot, report_dir, payload = rows[-1]
    previous_dir = rows[-2][1] if len(rows) > 1 else None
    result = {
        "report_slot": slot,
        "runtime_sha": str(payload["runtime_sha"]),
        "source_receipt_sha256": _sha((report_dir / "delivery_receipt.json").read_bytes()),
        "previous_deep_dir": str(previous_dir.resolve()) if previous_dir is not None else None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("PERF_BC_OCCURRENCE=" + json.dumps(result, sort_keys=True))
    return 0


def _decision_fingerprint(bundle: Mapping[str, Any]) -> str:
    watched = {
        "selected_route_id", "final_captain", "captain", "vice", "vice_captain",
        "xi", "bench_order", "bench_gk", "decision_state", "stage3_action",
        "action_contract",
    }
    found: list[tuple[str, Any]] = []
    def walk(value: Any, prefix: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in sorted(value.items(), key=lambda item: str(item[0])):
                key_s = str(key)
                path = f"{prefix}.{key_s}" if prefix else key_s
                if key_s in watched:
                    found.append((path, _semantic_strip(child)))
                walk(child, path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{prefix}[{index}]")
    walk(bundle.get("report") or {})
    walk(bundle.get("execution_proof") or {})
    return _sha(found)


def _stage_seconds(bundle: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in bundle.get("stage_ledger") or []:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("stage") or "")
        elapsed = row.get("elapsed_seconds")
        if name and elapsed is not None:
            try:
                out[name] = float(elapsed)
            except (TypeError, ValueError):
                pass
    return out

