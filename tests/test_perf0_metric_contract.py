from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "performance" / "v12_perf0_metrics.json"
EVIDENCE = (
    ROOT
    / "docs"
    / "audits"
    / "FPL_V12_PERF0_BASELINE_EVIDENCE_20260927.json"
)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_perf0_contract_covers_required_metadata_and_stages():
    payload = _read(CONTRACT)
    required = payload["required_sample_metadata"]
    for key in (
        "main_sha",
        "runtime_data_sha",
        "run_id",
        "logical_cpu_count",
        "physical_core_estimate",
        "cpu_model",
        "runtime_class",
        "python_version",
        "numpy_version",
        "openblas_version",
        "simd_features",
        "thread_count",
        "cache_profile",
        "cache_state",
    ):
        assert key in required

    metrics = payload["metrics"]
    for key in (
        "github_queue_seconds",
        "runner_provisioning_startup_seconds",
        "setup_seconds",
        "factual_acquisition_seconds",
        "stage2_seconds",
        "p1_2a_seconds",
        "p1_2b_seconds",
        "p1_7_seconds",
        "mc_seconds",
        "render_seconds",
        "qa_seconds",
        "private_publish_seconds",
        "cold_total_seconds",
        "warm_t0_t1_seconds",
    ):
        assert key in metrics


def test_perf0_never_infers_missing_timing_or_physical_cores():
    payload = _read(CONTRACT)
    assert payload["summary_rules"]["never_infer_missing_phase_timing"] is True
    assert (
        payload["physical_cpu_rule"]["logical_cpu_is_not_physical_core_count"]
        is True
    )
    assert (
        payload["physical_cpu_rule"]["unsupported_physical_core_estimate"]
        == "UNAVAILABLE"
    )


def test_diagnostic_runs_do_not_pollute_primary_distribution():
    evidence = _read(EVIDENCE)
    assert evidence["primary_comparable_sample_count"] == 0
    assert evidence["primary_sample_target"] == 6
    assert evidence["closure_status"] == "PENDING"
    assert len(evidence["diagnostic_samples"]) == 3
    assert all(
        sample["primary_eligible"] is False
        for sample in evidence["diagnostic_samples"]
    )
    assert all(
        sample["exclusion_reason"]
        == "REQUIRED_CORE_SLOT_BINDING_PARTIAL_CORE_SLOT_MISMATCH"
        for sample in evidence["diagnostic_samples"]
    )
    assert (
        evidence["statistics"]["primary_p90"]
        == "UNAVAILABLE_N_EQ_0"
    )


def test_diagnostic_samples_preserve_500k_mc_without_claiming_natural_acceptance():
    evidence = _read(EVIDENCE)
    for sample in evidence["diagnostic_samples"]:
        assert sample["mc_actual_paths"] == 500000
        assert sample["mc_convergence"] == "PASS"
        assert sample["private_delivery"] == "PASS"


def test_perf0_six_run_closure_keeps_p90_separate():
    contract = _read(CONTRACT)
    assert contract["sample_target"] == 6
    assert contract["comparability"]["production_natural_only_for_primary_baseline"] is False
    assert contract["comparability"]["allow_controlled_production_equivalent_main_runs"] is True
    assert contract["comparability"]["require_production_main_sha"] is True
    assert contract["comparability"]["controlled_runs_do_not_count_as_scheduler_proof"] is True
    assert contract["summary_rules"]["closure_min_samples"] == 6
    assert contract["summary_rules"]["perf0_closure_requires_p90"] is False
    assert contract["summary_rules"]["p90_min_samples"] == 10
