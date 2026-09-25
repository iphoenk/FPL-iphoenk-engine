from __future__ import annotations

"""Canonical numeric runtime class for deterministic V12 persistent caches.

Physical CPU model and host core count are observability only. Persistent cache
reuse is keyed on the normalized numerical runtime configured before NumPy is
imported: Python/NumPy, OpenBLAS core class, effective active NumPy SIMD set,
and OpenBLAS thread count.
"""

import argparse
from functools import lru_cache
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
    "X86_V4",
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


def _active_numpy_simd() -> tuple[str, ...]:
    multiarray = np._core._multiarray_umath
    baseline = tuple(
        str(value)
        for value in getattr(multiarray, "__cpu_baseline__", ())
    )
    dispatch = tuple(
        str(value)
        for value in getattr(multiarray, "__cpu_dispatch__", ())
    )
    features = getattr(multiarray, "__cpu_features__", {})
    found = tuple(
        feature
        for feature in dispatch
        if isinstance(features, dict) and bool(features.get(feature))
    )
    return tuple(sorted(set(baseline + found)))


def _normalized_openblas_coretype() -> str:
    return str(os.environ.get("OPENBLAS_CORETYPE") or "UNSET")


def _normalized_openblas_threads() -> int | None:
    raw = str(os.environ.get("OPENBLAS_NUM_THREADS") or "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def runtime_cache_identity() -> dict[str, Any]:
    """Exact cache runtime key; physical host identity is deliberately absent."""
    return {
        "python_major_minor": (
            f"{sys.version_info.major}.{sys.version_info.minor}"
        ),
        "numpy_version": np.__version__,
        "openblas_coretype": _normalized_openblas_coretype(),
        "numpy_simd_active": _active_numpy_simd(),
        "openblas_num_threads": _normalized_openblas_threads(),
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
            "NORMALIZED_OPENBLAS_CORETYPE_NOT_HASWELL:"
            + str(identity["openblas_coretype"])
        )
    if identity["openblas_num_threads"] != (
        CANONICAL_OPENBLAS_NUM_THREADS
    ):
        failures.append(
            "NORMALIZED_OPENBLAS_NUM_THREADS_NOT_ONE:"
            + str(identity["openblas_num_threads"])
        )
    forbidden_active = [
        feature
        for feature in identity["numpy_simd_active"]
        if (
            str(feature).upper() == "X86_V4"
            or str(feature).upper().startswith("AVX512")
        )
    ]
    if forbidden_active:
        failures.append(
            "ACTIVE_SIMD_ABOVE_HASWELL_NOT_ALLOWED:"
            + ",".join(forbidden_active)
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
