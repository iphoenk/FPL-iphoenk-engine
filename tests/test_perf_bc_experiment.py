
from __future__ import annotations

import json
from pathlib import Path

from src.engines import v12_perf_bc as perf

ROOT = Path(__file__).resolve().parents[1]


def test_perf_a_frozen_threshold_is_not_relaxed():
    cfg = json.loads(
        (ROOT / "config/performance/v12_perf_bc.json").read_text(encoding="utf-8")
    )
    assert cfg["perf_a_frozen"]["native_material_speedup_ratio_lte"] == 0.90
    assert cfg["perf_a_frozen"]["result"] == "KEEP_NORMALIZED_RUNTIME"
    assert cfg["perf_a_frozen"]["threshold_immutable"] is True


def test_perf_bc_safety_contract_preserves_canonical_quality():
    cfg = json.loads(
        (ROOT / "config/performance/v12_perf_bc.json").read_text(encoding="utf-8")
    )
    safety = cfg["safety"]
    assert safety["mc_paths_reduced"] is False
    assert safety["universe_pruned"] is False
    assert safety["search_completeness_reduced"] is False
    assert safety["qa_skipped"] is False
    assert safety["production_runtime_selection_changed"] is False
    assert safety["private_publish_performed"] is False
    assert safety["paid_infrastructure"] is False
    assert safety["second_scheduler"] is False
    assert safety["thresholds_change_after_observation"] is False


def test_perf_b_order_and_material_gate_are_frozen_before_measurement():
    cfg = json.loads(
        (ROOT / "config/performance/v12_perf_bc.json").read_text(encoding="utf-8")
    )
    assert cfg["perf_b"]["order"] == [
        "NORMALIZED",
        "NATIVE_MC_SUBPROCESS",
        "NORMALIZED",
        "NATIVE_MC_SUBPROCESS",
    ]
    assert cfg["perf_b"]["actual_paths"] == 500_000
    assert cfg["perf_b"]["material_e2e_ratio_lte"] == 0.90
    assert cfg["perf_b"]["minimum_e2e_seconds_saved"] == 5.0


def test_stage2_worker_matrix_is_exactly_1_2_4_and_repeated():
    cfg = json.loads(
        (ROOT / "config/performance/v12_perf_bc.json").read_text(encoding="utf-8")
    )
    assert cfg["perf_c_stage2"]["workers"] == [1, 2, 4]
    assert cfg["perf_c_stage2"]["repetitions"] >= 2
    assert cfg["perf_c_stage2"]["cache_class"] == "COLD_DIRECT_NO_CACHE"


def test_semantic_strip_removes_timing_but_preserves_decision_content():
    value = {
        "generated_at": "x",
        "wall_seconds": 10.0,
        "decision": {"selected_route_id": "R1", "elapsed_seconds": 3.0},
    }
    stripped = perf._semantic_strip(value)
    assert stripped == {"decision": {"selected_route_id": "R1"}}


def test_native_env_keeps_one_thread_and_removes_numeric_normalization(monkeypatch):
    monkeypatch.setenv("OPENBLAS_CORETYPE", "Haswell")
    monkeypatch.setenv("NPY_DISABLE_CPU_FEATURES", "X86_V4")
    monkeypatch.setenv("V12_MC_SIM_CACHE_DIR", "/tmp/equal-cold-mc-cache")
    env = perf._native_mc_env()
    assert "OPENBLAS_CORETYPE" not in env
    assert "NPY_DISABLE_CPU_FEATURES" not in env
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["OMP_NUM_THREADS"] == "1"
    assert env["V12_MC_SIM_CACHE_DIR"] == "/tmp/equal-cold-mc-cache"
