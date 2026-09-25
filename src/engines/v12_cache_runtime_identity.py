from __future__ import annotations

"""Stable numeric-runtime identity for deterministic V12 persistent caches.

Warm-cache equivalence is only claimed when this identity matches exactly.
The identity deliberately captures host/runtime traits that can affect floating
point execution: Python/NumPy, CPU model and active SIMD feature set, logical
core count, and the NumPy BLAS/OpenBLAS build/thread configuration.
"""

from contextlib import redirect_stdout
from functools import lru_cache
import io
import os
import platform
import re
import sys
from typing import Any

import numpy as np


def _cpu_model() -> str:
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


def _numpy_runtime_blas_identity() -> dict[str, Any]:
    show_runtime = getattr(np, "show_runtime", None)
    if not callable(show_runtime):
        return {
            "runtime_architecture": "UNKNOWN",
            "runtime_internal_api": "UNKNOWN",
            "runtime_num_threads": None,
            "runtime_threading_layer": "UNKNOWN",
            "runtime_version": "UNKNOWN",
        }
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            show_runtime()
    except Exception:
        return {
            "runtime_architecture": "UNKNOWN",
            "runtime_internal_api": "UNKNOWN",
            "runtime_num_threads": None,
            "runtime_threading_layer": "UNKNOWN",
            "runtime_version": "UNKNOWN",
        }
    text = buf.getvalue()

    def _text_field(name: str) -> str:
        match = re.search(
            rf"['\"]{re.escape(name)}['\"]\s*:\s*['\"]([^'\"]+)['\"]",
            text,
        )
        return match.group(1) if match else "UNKNOWN"

    threads = re.search(
        r"['\"]num_threads['\"]\s*:\s*(\d+)",
        text,
    )
    return {
        "runtime_architecture": _text_field("architecture"),
        "runtime_internal_api": _text_field("internal_api"),
        "runtime_num_threads": (
            int(threads.group(1)) if threads else None
        ),
        "runtime_threading_layer": _text_field("threading_layer"),
        "runtime_version": _text_field("version"),
    }


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
        **_numpy_runtime_blas_identity(),
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
