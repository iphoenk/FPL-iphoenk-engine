from __future__ import annotations

import json
from pathlib import Path

from src.engines import v12_perf_a


ROOT = Path(__file__).resolve().parents[1]


def test_perf_a_contract_is_frozen_abab_same_state():
    cfg = json.loads(
        (ROOT / "config/performance/v12_perf_a.json").read_text(encoding="utf-8")
    )
    assert cfg["order"] == ["NORMALIZED", "NATIVE", "NORMALIZED", "NATIVE"]
    assert cfg["actual_paths"] == 500000
    assert cfg["same_host_required"] is True
    assert cfg["same_sha_required"] is True
    assert cfg["same_snapshot_required"] is True
    assert cfg["same_routes_required"] is True
    assert cfg["same_seed_required"] is True
    assert cfg["semantic_output_fingerprint_equal_required"] is True
    assert 0 < cfg["native_material_speedup_ratio_lte"] < 1


def test_perf_a_runtime_env_keeps_thread_count_constant(monkeypatch):
    monkeypatch.setenv("OPENBLAS_CORETYPE", "junk")
    monkeypatch.setenv("NPY_DISABLE_CPU_FEATURES", "junk")
    native = v12_perf_a._env("NATIVE")
    normalized = v12_perf_a._env("NORMALIZED")
    assert native["OPENBLAS_NUM_THREADS"] == normalized["OPENBLAS_NUM_THREADS"] == "1"
    assert native["OMP_NUM_THREADS"] == normalized["OMP_NUM_THREADS"] == "1"
    assert "OPENBLAS_CORETYPE" not in native
    assert "NPY_DISABLE_CPU_FEATURES" not in native
    assert normalized["OPENBLAS_CORETYPE"] == "Haswell"
    assert normalized["NPY_DISABLE_CPU_FEATURES"]
    assert native["V12_PRIVATE_CACHE_PROFILE"] == "SECURE_NO_PERSONAL_CACHE"
    assert normalized["V12_PRIVATE_CACHE_PROFILE"] == "SECURE_NO_PERSONAL_CACHE"
