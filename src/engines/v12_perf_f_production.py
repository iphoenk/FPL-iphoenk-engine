from __future__ import annotations

"""Production PERF-F sample collector.

This module never invents phase timings. Required canonical timings are read
from the occurrence-bound integrated-runner execution proof; warm orchestration
timings come from the already-running P6 worker result.
"""

from collections.abc import Mapping
from typing import Any

from .v12_perf_f import PerfFError, PerfFSample, validate_sample


class PerfFProductionError(PerfFError):
    pass


CANONICAL_STAGE_MAP = {
    "Stage2": "P1_1_P1_3_FULL_UNIVERSE",
    "P1.7": "P1_7_LINEUP",
    "MC": "P1_4_MONTE_CARLO",
}


def _stage_seconds(execution_proof: Mapping[str, Any], stage: str) -> float:
    rows = [
        row for row in execution_proof.get("stages") or ()
        if isinstance(row, Mapping) and str(row.get("stage") or "") == stage
    ]
    if len(rows) != 1:
        raise PerfFProductionError(
            f"canonical timing stage is not uniquely available: {stage}"
        )
    row = rows[0]
    if str(row.get("status") or "").upper() != "PASS":
        raise PerfFProductionError(f"canonical timing stage did not PASS: {stage}")
    raw = row.get("elapsed_seconds")
    if raw is None:
        raise PerfFProductionError(f"canonical timing missing elapsed_seconds: {stage}")
    seconds = float(raw)
    if seconds < 0:
        raise PerfFProductionError(f"canonical timing is negative: {stage}")
    return seconds


def canonical_required_timings(
    execution_proof: Mapping[str, Any],
) -> dict[str, float]:
    mc = dict(execution_proof.get("monte_carlo") or {})
    if int(mc.get("actual_paths") or 0) < 500_000:
        raise PerfFProductionError("canonical MC timing is not backed by 500k paths")
    if mc.get("canonical_pass") is not True:
        raise PerfFProductionError("canonical MC timing is not backed by canonical PASS")
    return {
        name: _stage_seconds(execution_proof, stage)
        for name, stage in CANONICAL_STAGE_MAP.items()
    }


def build_production_sample(
    *,
    case: str,
    worker_result: Mapping[str, Any],
    execution_proof: Mapping[str, Any],
    cold_semantic_fingerprint: str,
    scenario_seconds: float,
) -> PerfFSample:
    identity = dict(worker_result.get("final_identity") or {})
    warm_timings = dict(worker_result.get("timings") or {})
    required_warm = (
        "classification",
        "cache_lookup",
        "Stage3",
        "render",
        "QA",
        "private_publish",
    )
    missing = [key for key in required_warm if key not in warm_timings]
    if missing:
        raise PerfFProductionError(f"warm worker timing missing: {missing}")
    if float(scenario_seconds) < 0:
        raise PerfFProductionError("scenario timing is negative")

    canonical = canonical_required_timings(execution_proof)
    timings = {
        "classification": float(warm_timings["classification"]),
        "cache_lookup": float(warm_timings["cache_lookup"]),
        "Stage2": canonical["Stage2"],
        "P1.7": canonical["P1.7"],
        "MC": canonical["MC"],
        "scenario": float(scenario_seconds),
        "Stage3": float(warm_timings["Stage3"]),
        "render": float(warm_timings["render"]),
        "QA": float(warm_timings["QA"]),
        "private_publish": float(warm_timings["private_publish"]),
    }
    return PerfFSample(
        case=str(case).upper(),
        t0=float(worker_result["t0"]),
        t1=float(worker_result["t1"]),
        lineage=identity,
        change_class=str(worker_result.get("change_class") or case).upper(),
        expected_cache_state=dict(worker_result.get("expected_cache_state") or {}),
        actual_cache_state=dict(worker_result.get("actual_cache_state") or {}),
        invalidated_dependency_keys=list(
            worker_result.get("invalidated_dependency_keys") or ()
        ),
        timings=timings,
        cold_semantic_fingerprint=str(cold_semantic_fingerprint or ""),
        warm_semantic_fingerprint=str(
            worker_result.get("warm_semantic_fingerprint") or ""
        ),
        owner_context_fingerprint=str(
            identity.get("owner_context_fingerprint") or ""
        ),
        reused_dependency_keys=dict(
            worker_result.get("reused_dependency_keys") or {}
        ),
        private_delivery_status=str(
            worker_result.get("private_delivery_status") or ""
        ),
        private_remote_sha=str(worker_result.get("private_remote_sha") or ""),
    )


def validate_production_sample(
    *,
    case: str,
    worker_result: Mapping[str, Any],
    execution_proof: Mapping[str, Any],
    cold_semantic_fingerprint: str,
    scenario_seconds: float,
    target_seconds: float = 15.0,
) -> dict[str, Any]:
    sample = build_production_sample(
        case=case,
        worker_result=worker_result,
        execution_proof=execution_proof,
        cold_semantic_fingerprint=cold_semantic_fingerprint,
        scenario_seconds=scenario_seconds,
    )
    return validate_sample(sample, target_seconds=target_seconds)
