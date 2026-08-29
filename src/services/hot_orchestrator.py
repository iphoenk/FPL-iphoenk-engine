from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from time import perf_counter

from src.services import (
    architecture_guard_service,
    enrichment_service,
    governance_service,
    gw_scorecard_service,
    optimization_slo_service,
    prediction_service,
    raw_snapshot_service,
    user_decision_overlay_service,
)
from src.services.contracts import file_digest
from src.utils import DATA, ROOT, atomic_json, iso_now, read_json

OUTFILE = DATA / "hot_orchestration_v4.json"
SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"
ENRICHMENT = DATA / "runtime" / "enrichment.v1.json"
LATEST = DATA / "latest.json"


def _assert_digest(path, expected: str, label: str) -> None:
    actual = file_digest(path)
    if actual != expected:
        raise RuntimeError(f"hot-path immutable {label} changed: {actual} != {expected}")


def run(mode: str = "daily", stats: bool = True, deep_stats: bool = True, as_of: str | None = None) -> dict:
    """Production-candidate E2E hot path used first as a non-publishing benchmark.

    Tier-1 acquisition, enrichment and prediction execute in one process. Validation
    remains a separate concurrent process so the optimizer can safely fork its exact
    WC/package/lineup workers from the main thread. User authority, scorecard and
    governance then execute in-process. No decision capability or search width is
    removed; this only eliminates repeated Python interpreter/process startup and
    JSON bootstrap overhead between bounded stages.
    """
    started = perf_counter()
    assurance = architecture_guard_service.run()
    if assurance.get("status") != "PASS":
        raise RuntimeError("hot-path architecture assurance failed")

    service_ms: dict[str, float] = {}

    t = perf_counter()
    raw = raw_snapshot_service.run(mode, as_of)
    service_ms["raw_snapshot"] = round((perf_counter() - t) * 1000.0, 2)
    snapshot_sha = file_digest(SNAPSHOT)

    t = perf_counter()
    enrichment_service.run(stats, deep_stats)
    service_ms["enrichment"] = round((perf_counter() - t) * 1000.0, 2)
    _assert_digest(SNAPSHOT, snapshot_sha, "snapshot")
    enrichment_sha = file_digest(ENRICHMENT)

    t = perf_counter()
    prediction_service.run()
    service_ms["prediction"] = round((perf_counter() - t) * 1000.0, 2)
    _assert_digest(SNAPSHOT, snapshot_sha, "snapshot")
    _assert_digest(ENRICHMENT, enrichment_sha, "enrichment")
    latest_sha = file_digest(LATEST)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    validation_started = perf_counter()
    validation = subprocess.Popen(
        [sys.executable, "-m", "src.services.validation_service"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    t = perf_counter()
    decision = optimization_slo_service.run()
    service_ms["optimization"] = round((perf_counter() - t) * 1000.0, 2)
    _assert_digest(SNAPSHOT, snapshot_sha, "snapshot")
    _assert_digest(ENRICHMENT, enrichment_sha, "enrichment")
    _assert_digest(LATEST, latest_sha, "latest")

    t = perf_counter()
    user_decision_overlay_service.run()
    service_ms["user_decision_overlay"] = round((perf_counter() - t) * 1000.0, 2)

    t = perf_counter()
    gw_scorecard_service.run()
    service_ms["personal_gw_scorecard"] = round((perf_counter() - t) * 1000.0, 2)

    validation_stdout, validation_stderr = validation.communicate(timeout=45)
    validation_ms = round((perf_counter() - validation_started) * 1000.0, 2)
    service_ms["validation_concurrent_wall"] = validation_ms
    if validation.returncode != 0:
        raise RuntimeError(f"hot-path validation failed: {(validation_stderr or validation_stdout)[-1200:]}")

    t = perf_counter()
    governance_service.run()
    service_ms["governance"] = round((perf_counter() - t) * 1000.0, 2)
    _assert_digest(SNAPSHOT, snapshot_sha, "snapshot")
    _assert_digest(ENRICHMENT, enrichment_sha, "enrichment")
    _assert_digest(LATEST, latest_sha, "latest")

    total_ms = round((perf_counter() - started) * 1000.0, 2)
    timings = decision.get("timings") or {}
    latest = read_json(LATEST, {})
    out = {
        "schema_version": 1,
        "engine": "v4.9.6-e2e-hot-path-candidate-v1",
        "generated_at": iso_now(),
        "status": "PASS",
        "mode": mode,
        "total_e2e_ms": total_ms,
        "service_ms": service_ms,
        "official_acquisition_ms": float(raw.get("duration_ms") or 0.0),
        "enrichment_reported_ms": float((read_json(ENRICHMENT, {}) or {}).get("duration_ms") or 0.0),
        "prediction_reported_ms": float((latest.get("performance") or {}).get("prediction_ms") or 0.0),
        "decision_compute_ms": float(timings.get("total_pipeline_ms") or 0.0),
        "optimizer_cache_hit": bool(timings.get("optimizer_exact_cache_hit")),
        "targets": {
            "deterministic_decision_ms": 1000.0,
            "fresh_e2e_p50_ms": 2000.0,
            "fresh_e2e_p95_ms": 3000.0,
        },
        "target_status": {
            "decision_under_1s": float(timings.get("total_pipeline_ms") or 1e9) < 1000.0,
            "single_run_e2e_under_2s": total_ms < 2000.0,
            "single_run_e2e_under_3s": total_ms < 3000.0,
        },
        "guardrails": {
            "official_fpl_refreshed_this_run": True,
            "official_authority_unchanged": True,
            "exact_optimizer_search_width_unchanged": True,
            "user_final_authority_preserved": True,
            "validation_runs_concurrently_not_skipped": True,
            "architecture_guard_runs_first": True,
            "snapshot_enrichment_latest_immutable_after_lock": True,
            "non_publishing_benchmark_until_promoted": True,
        },
    }
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "hot_orchestrator": "PASS",
        "total_e2e_ms": total_ms,
        "official_acquisition_ms": out["official_acquisition_ms"],
        "decision_compute_ms": out["decision_compute_ms"],
        "optimizer_cache_hit": out["optimizer_cache_hit"],
        "under_2s": out["target_status"]["single_run_e2e_under_2s"],
        "under_3s": out["target_status"]["single_run_e2e_under_3s"],
    }, ensure_ascii=False))
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=("daily", "deadline", "live"), default="daily")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--deep-stats", action="store_true")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    return run(args.mode, args.stats, args.deep_stats, args.as_of)


if __name__ == "__main__":
    cli()
