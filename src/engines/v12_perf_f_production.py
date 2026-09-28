from __future__ import annotations

"""Production PERF-F sample collector.

No phase timing is inferred from an unrelated wall-clock stage. Cache HIT and
NOT_APPLICABLE mean the governed layer did not execute in the warm path and
therefore contribute zero seconds. MISS timings come from canonical owner
telemetry. PARTIAL_INVALIDATION must provide explicit warm-layer timing rather
than borrowing the canonical cold duration.
"""

from collections.abc import Mapping
from typing import Any

from .v12_perf_f import PerfFError, PerfFSample, validate_sample


class PerfFProductionError(PerfFError):
    pass


CANONICAL_STAGE_MAP = {
    "Stage2": "P1_1_P1_3_FULL_UNIVERSE",
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


def _proof_seconds(proof: Mapping[str, Any], label: str) -> float:
    if not proof:
        raise PerfFProductionError(f"missing exact P1.7 owner proof: {label}")
    raw = proof.get("elapsed_seconds")
    if raw is None:
        raise PerfFProductionError(
            f"exact P1.7 owner proof missing elapsed_seconds: {label}"
        )
    seconds = float(raw)
    if seconds < 0:
        raise PerfFProductionError(f"negative exact P1.7 owner timing: {label}")
    return seconds


def canonical_p17_timings(execution_proof: Mapping[str, Any]) -> dict[str, float]:
    p17 = dict(execution_proof.get("p1_7_execution") or {})
    lineup = dict(p17.get("lineup") or {})
    if str(lineup.get("status") or "").upper() != "PASS":
        raise PerfFProductionError("exact P1.7 lineup stage did not PASS")
    lineup_seconds = float(lineup.get("elapsed_seconds"))
    if lineup_seconds < 0:
        raise PerfFProductionError("negative exact P1.7 lineup timing")
    direct_seconds = _proof_seconds(
        dict(p17.get("direct_package") or {}),
        "direct_package",
    )
    funded_seconds = _proof_seconds(
        dict(p17.get("funded_package") or {}),
        "funded_package",
    )
    return {
        "lineup": lineup_seconds,
        "direct_package": direct_seconds,
        "funded_package": funded_seconds,
        "total": lineup_seconds + direct_seconds + funded_seconds,
    }


def canonical_required_timings(
    execution_proof: Mapping[str, Any],
) -> dict[str, float]:
    mc = dict(execution_proof.get("monte_carlo") or {})
    if int(mc.get("actual_paths") or 0) < 500_000:
        raise PerfFProductionError("canonical MC timing is not backed by 500k paths")
    if mc.get("canonical_pass") is not True:
        raise PerfFProductionError("canonical MC timing is not backed by canonical PASS")
    return {
        "Stage2": _stage_seconds(
            execution_proof,
            CANONICAL_STAGE_MAP["Stage2"],
        ),
        "P1.7": canonical_p17_timings(execution_proof)["total"],
        "MC": _stage_seconds(
            execution_proof,
            CANONICAL_STAGE_MAP["MC"],
        ),
    }


def _governed_warm_layer_seconds(
    *,
    layer: str,
    actual_state: str,
    canonical_seconds: float,
    worker_result: Mapping[str, Any],
) -> float:
    state = str(actual_state or "").upper()
    if state in {"HIT", "NOT_APPLICABLE"}:
        return 0.0
    if state == "MISS":
        return float(canonical_seconds)
    if state == "PARTIAL_INVALIDATION":
        phase = dict(worker_result.get("layer_timings") or {})
        if layer not in phase:
            raise PerfFProductionError(
                f"partial invalidation requires exact warm timing: {layer}"
            )
        seconds = float(phase[layer])
        if seconds < 0:
            raise PerfFProductionError(
                f"partial invalidation timing is negative: {layer}"
            )
        return seconds
    raise PerfFProductionError(f"unsupported actual cache state for {layer}: {state}")


def build_production_sample(
    *,
    case: str,
    worker_result: Mapping[str, Any],
    execution_proof: Mapping[str, Any],
    cold_semantic_fingerprint: str,
) -> PerfFSample:
    identity = dict(worker_result.get("final_identity") or {})
    warm_timings = dict(worker_result.get("timings") or {})
    required_warm = (
        "classification",
        "cache_lookup",
        "scenario",
        "Stage3",
        "render",
        "QA",
        "private_publish",
    )
    missing = [key for key in required_warm if key not in warm_timings]
    if missing:
        raise PerfFProductionError(f"warm worker timing missing: {missing}")

    actual = {
        str(key): str(value).upper()
        for key, value in dict(
            worker_result.get("actual_cache_state") or {}
        ).items()
    }
    canonical = canonical_required_timings(execution_proof)
    timings = {
        "classification": float(warm_timings["classification"]),
        "cache_lookup": float(warm_timings["cache_lookup"]),
        "Stage2": _governed_warm_layer_seconds(
            layer="Stage2",
            actual_state=actual.get("Stage2", ""),
            canonical_seconds=canonical["Stage2"],
            worker_result=worker_result,
        ),
        "P1.7": _governed_warm_layer_seconds(
            layer="P1.7",
            actual_state=actual.get("P1.7", ""),
            canonical_seconds=canonical["P1.7"],
            worker_result=worker_result,
        ),
        "MC": _governed_warm_layer_seconds(
            layer="MC",
            actual_state=actual.get("MC", ""),
            canonical_seconds=canonical["MC"],
            worker_result=worker_result,
        ),
        "scenario": float(warm_timings["scenario"]),
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
        actual_cache_state=actual,
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
    target_seconds: float = 15.0,
) -> dict[str, Any]:
    sample = build_production_sample(
        case=case,
        worker_result=worker_result,
        execution_proof=execution_proof,
        cold_semantic_fingerprint=cold_semantic_fingerprint,
    )
    return validate_sample(sample, target_seconds=target_seconds)
