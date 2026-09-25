from __future__ import annotations

"""Canonical numeric runtime class for deterministic V12 persistent caches.

Physical CPU model and host core count are observability only. Persistent cache
reuse is keyed on the effective numerical runtime after normalization:
Python/NumPy, OpenBLAS core, active NumPy SIMD dispatch set, and BLAS thread
count.
"""

import argparse
import ast
from contextlib import redirect_stdout
from functools import lru_cache
import io
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any

import numpy as np


CANONICAL_OPENBLAS_CORETYPE = "Haswell"
CANONICAL_OPENBLAS_NUM_THREADS = 1
CANONICAL_NPY_DISABLE_CPU_FEATURES = (
    "AVX512F",
    "AVX512CD",
    "AVX512_KNL",
    "AVX512_KNM",
    "AVX512_SKX",
    "AVX512_CLX",
    "AVX512_CNL",
    "AVX512_ICL",
    "AVX512_SPR",
)


def physical_cpu_model() -> str:
    """Return host CPU model for evidence only; never include it in cache keys."""
    path = "/proc/cpuinfo"
    processor_fallback = ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if ":" not in raw:
                    continue
                key, value = raw.split(":", 1)
                normalized = key.strip().lower()
                candidate = value.strip()
                if not candidate:
                    continue
                if normalized in {"model name", "hardware"}:
                    return candidate
                if (
                    normalized == "processor"
                    and not candidate.isdigit()
                    and not processor_fallback
                ):
                    processor_fallback = candidate
    except OSError:
        pass
    if processor_fallback:
        return processor_fallback
    return str(platform.processor() or platform.machine() or "UNKNOWN")


@lru_cache(maxsize=1)
def _numpy_runtime_rows() -> list[dict[str, Any]]:
    show_runtime = getattr(np, "show_runtime", None)
    if not callable(show_runtime):
        return []
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            show_runtime()
        value = ast.literal_eval(buf.getvalue().strip())
    except (ValueError, SyntaxError, TypeError):
        return []
    return [
        dict(row)
        for row in value
        if isinstance(row, dict)
    ] if isinstance(value, list) else []


def _active_numpy_simd() -> tuple[str, ...]:
    for row in _numpy_runtime_rows():
        simd = row.get("simd_extensions")
        if isinstance(simd, dict):
            baseline = [
                str(value)
                for value in simd.get("baseline") or []
            ]
            found = [
                str(value)
                for value in simd.get("found") or []
            ]
            return tuple(sorted(set(baseline + found)))
    return ()


def _openblas_runtime() -> dict[str, Any]:
    for row in _numpy_runtime_rows():
        if str(row.get("internal_api") or "").lower() == "openblas":
            return {
                "coretype": str(row.get("architecture") or "UNKNOWN"),
                "num_threads": (
                    int(row["num_threads"])
                    if row.get("num_threads") is not None
                    else None
                ),
            }
    return {
        "coretype": "UNKNOWN",
        "num_threads": None,
    }


@lru_cache(maxsize=1)
def runtime_cache_identity() -> dict[str, Any]:
    """Exact persistent-cache runtime key. No physical host identity allowed."""
    openblas = _openblas_runtime()
    return {
        "python_major_minor": (
            f"{sys.version_info.major}.{sys.version_info.minor}"
        ),
        "numpy_version": np.__version__,
        "openblas_coretype": openblas["coretype"],
        "numpy_simd_active": _active_numpy_simd(),
        "openblas_num_threads": openblas["num_threads"],
    }


def runtime_normalization_evidence() -> dict[str, Any]:
    return {
        "physical_cpu_model": physical_cpu_model(),
        "physical_cpu_model_in_cache_key": False,
        "logical_cpu_count": max(1, int(os.cpu_count() or 1)),
        "logical_cpu_count_in_cache_key": False,
        "environment": {
            "OPENBLAS_CORETYPE": str(
                os.environ.get("OPENBLAS_CORETYPE") or ""
            ),
            "OPENBLAS_NUM_THREADS": str(
                os.environ.get("OPENBLAS_NUM_THREADS") or ""
            ),
            "OMP_NUM_THREADS": str(
                os.environ.get("OMP_NUM_THREADS") or ""
            ),
            "NPY_DISABLE_CPU_FEATURES": str(
                os.environ.get("NPY_DISABLE_CPU_FEATURES") or ""
            ),
        },
        "cache_identity": runtime_cache_identity(),
    }


def validate_canonical_runtime_class() -> dict[str, Any]:
    evidence = runtime_normalization_evidence()
    env = evidence["environment"]
    identity = evidence["cache_identity"]
    failures: list[str] = []

    if env["OPENBLAS_CORETYPE"].lower() != (
        CANONICAL_OPENBLAS_CORETYPE.lower()
    ):
        failures.append("OPENBLAS_CORETYPE_NOT_HASWELL")
    if env["OPENBLAS_NUM_THREADS"] != str(
        CANONICAL_OPENBLAS_NUM_THREADS
    ):
        failures.append("OPENBLAS_NUM_THREADS_NOT_ONE")
    if env["OMP_NUM_THREADS"] != "1":
        failures.append("OMP_NUM_THREADS_NOT_ONE")

    disabled = {
        token.strip()
        for token in env["NPY_DISABLE_CPU_FEATURES"].split(",")
        if token.strip()
    }
    missing_disabled = (
        set(CANONICAL_NPY_DISABLE_CPU_FEATURES) - disabled
    )
    if missing_disabled:
        failures.append(
            "NPY_DISABLE_CPU_FEATURES_INCOMPLETE:"
            + ",".join(sorted(missing_disabled))
        )

    if str(identity["openblas_coretype"]).lower() != (
        CANONICAL_OPENBLAS_CORETYPE.lower()
    ):
        failures.append(
            "EFFECTIVE_OPENBLAS_CORETYPE_NOT_HASWELL:"
            + str(identity["openblas_coretype"])
        )
    if identity["openblas_num_threads"] != (
        CANONICAL_OPENBLAS_NUM_THREADS
    ):
        failures.append(
            "EFFECTIVE_OPENBLAS_NUM_THREADS_NOT_ONE:"
            + str(identity["openblas_num_threads"])
        )
    active_avx512 = [
        feature
        for feature in identity["numpy_simd_active"]
        if str(feature).upper().startswith("AVX512")
    ]
    if active_avx512:
        failures.append(
            "ACTIVE_AVX512_NOT_ALLOWED:"
            + ",".join(active_avx512)
        )

    evidence["canonical_runtime_class"] = (
        "PASS" if not failures else "FAIL"
    )
    evidence["failures"] = failures
    if failures:
        raise RuntimeError(
            "V12 canonical numeric runtime class violation: "
            + "; ".join(failures)
        )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    evidence = validate_canonical_runtime_class()
    payload = json.dumps(
        evidence,
        indent=2,
        sort_keys=True,
    )
    print(payload)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
