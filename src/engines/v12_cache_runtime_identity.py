from __future__ import annotations

"""Stable numeric-runtime identity for deterministic V12 persistent caches.

Warm-cache equivalence is only claimed when this identity matches exactly.
The identity deliberately captures host/runtime traits that can affect floating
point execution: Python/NumPy, CPU model and active SIMD feature set, logical
core count, and the NumPy BLAS/OpenBLAS build/thread configuration.
"""

from functools import lru_cache
import os
import platform
import sys
from typing import Any

import numpy as np


def _cpu_model() -> str:
    path = "/proc/cpuinfo"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if ":" not in raw:
                    continue
                key, value = raw.split(":", 1)
                if key.strip().lower() in {
                    "model name",
                    "hardware",
                    "processor",
                }:
                    candidate = value.strip()
                    if candidate:
                        return candidate
    except OSError:
        pass
    return str(platform.processor() or platform.machine() or "UNKNOWN")


def _active_numpy_simd() -> tuple[str, ...]:
    core = getattr(np, "_core", None)
    multiarray = getattr(core, "_multiarray_umath", None)
    features = getattr(multiarray, "__cpu_features__", {})
    if not isinstance(features, dict):
        return ()
    return tuple(
        sorted(
            str(name)
            for name, enabled in features.items()
            if bool(enabled)
        )
    )


def _blas_identity() -> dict[str, Any]:
    config = getattr(np.__config__, "CONFIG", {})
    build_dependencies = (
        config.get("Build Dependencies", {})
        if isinstance(config, dict)
        else {}
    )
    blas = (
        build_dependencies.get("blas", {})
        if isinstance(build_dependencies, dict)
        else {}
    )
    if not isinstance(blas, dict):
        blas = {}
    return {
        "name": str(blas.get("name") or "UNKNOWN"),
        "version": str(blas.get("version") or "UNKNOWN"),
        "openblas_configuration": str(
            blas.get("openblas configuration") or ""
        ),
        "openblas_coretype": str(
            os.environ.get("OPENBLAS_CORETYPE") or ""
        ),
        "openblas_num_threads": str(
            os.environ.get("OPENBLAS_NUM_THREADS") or ""
        ),
        "omp_num_threads": str(
            os.environ.get("OMP_NUM_THREADS") or ""
        ),
    }


@lru_cache(maxsize=1)
def runtime_cache_identity() -> dict[str, Any]:
    return {
        "python_major_minor": (
            f"{sys.version_info.major}.{sys.version_info.minor}"
        ),
        "numpy_version": np.__version__,
        "platform_machine": str(platform.machine() or "UNKNOWN"),
        "cpu_model": _cpu_model(),
        "cpu_count": max(1, int(os.cpu_count() or 1)),
        "numpy_simd_active": _active_numpy_simd(),
        "blas": _blas_identity(),
    }
