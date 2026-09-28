from __future__ import annotations

"""PERF-F warm-latency acceptance contract.

T0 is acceptance of a material event/owner command by an already-running warm
worker. T1 is completion of validated private publication. Queue/provisioning are
outside this metric by construction.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Mapping, Sequence

from .v12_cache_operational import CachePlan, LAYERS, validate_actual_behavior

REQUIRED_CASES = (
    "NO_CHANGE",
    "MINI_LEAGUE_ONLY",
    "PRICE_ONLY",
    "OUR15_AVAILABILITY",
    "CAPTAIN_CHANGE",
    "VICE_CAPTAIN_CHANGE",
    "MATERIAL_PROJECTION",
    "P4_SCENARIO_HIT",
    "P4_SCENARIO_MISS",
)
REQUIRED_TIMINGS = (
    "classification",
    "cache_lookup",
    "Stage2",
    "P1.7",
    "MC",
    "scenario",
    "Stage3",
    "render",
    "QA",
    "private_publish",
)
REQUIRED_LINEAGE = (
    "production_sha",
    "runtime_data_sha",
    "runtime_class",
    "model_version",
    "schema_version",
    "gw_fixture_fingerprint",
    "projection_lineage_fingerprint",
    "current15_fingerprint",
    "mc_authority",
)


class PerfFError(RuntimeError):
    pass


@dataclass(frozen=True)
class PerfFSample:
    case: str
    t0: float
    t1: float
    lineage: Mapping[str, Any]
    change_class: str
    expected_cache_state: Mapping[str, str]
    actual_cache_state: Mapping[str, str]
    invalidated_dependency_keys: Sequence[str]
    timings: Mapping[str, float]
    cold_semantic_fingerprint: str
    warm_semantic_fingerprint: str
    owner_context_fingerprint: str = ""
    reused_dependency_keys: Mapping[str, Sequence[str]] = field(default_factory=dict)
    private_delivery_status: str = ""
    private_remote_sha: str = ""

    @property
    def total_seconds(self) -> float:
        return float(self.t1) - float(self.t0)


def validate_sample(sample: PerfFSample, *, target_seconds: float = 15.0) -> dict[str, Any]:
    case = str(sample.case).upper()
    if case not in REQUIRED_CASES:
        raise PerfFError(f"unsupported PERF-F case: {case}")
    missing_lineage = [key for key in REQUIRED_LINEAGE if not str(sample.lineage.get(key) or "").strip()]
    if missing_lineage:
        raise PerfFError(f"missing PERF-F lineage: {missing_lineage}")
    if not str(sample.owner_context_fingerprint or "").strip():
        raise PerfFError("missing PERF-F owner-context fingerprint")
    if sample.t1 < sample.t0:
        raise PerfFError("T1 precedes T0")
    missing_timings = [key for key in REQUIRED_TIMINGS if key not in sample.timings]
    if missing_timings:
        raise PerfFError(f"missing PERF-F stage timings: {missing_timings}")
    if any(float(sample.timings[key]) < 0 for key in REQUIRED_TIMINGS):
        raise PerfFError("negative PERF-F timing")

    expected = {layer: str(sample.expected_cache_state.get(layer) or "").upper() for layer in LAYERS}
    actual = {layer: str(sample.actual_cache_state.get(layer) or "").upper() for layer in LAYERS}
    if any(not expected[layer] for layer in LAYERS):
        raise PerfFError("incomplete PERF-F expected cache state")
    if any(not actual[layer] for layer in LAYERS):
        raise PerfFError("incomplete PERF-F actual cache state")
    cache_plan = CachePlan(
        change_class=str(sample.change_class or case).upper(),
        matrix_class=str(sample.change_class or case).upper(),
        scope_certain=True,
        affected_dependency_keys=tuple(str(x) for x in sample.invalidated_dependency_keys),
        expected=expected,
        recompute_layers=tuple(
            layer for layer in LAYERS
            if expected[layer] in {"MISS", "PARTIAL_INVALIDATION"}
        ),
        reusable_layers=tuple(layer for layer in LAYERS if expected[layer] == "HIT"),
        partial_layers=tuple(
            layer for layer in LAYERS if expected[layer] == "PARTIAL_INVALIDATION"
        ),
    )
    cache_validation = validate_actual_behavior(
        cache_plan,
        actual_states=actual,
        reused_dependency_keys=sample.reused_dependency_keys,
    )
    cache_correctness_pass = cache_validation.correctness == "PASS"
    private_publish_pass = (
        str(sample.private_delivery_status or "").upper() == "PASS"
        and bool(str(sample.private_remote_sha or "").strip())
    )
    semantic_equal = (
        bool(sample.warm_semantic_fingerprint)
        and sample.warm_semantic_fingerprint == sample.cold_semantic_fingerprint
    )
    latency_pass = sample.total_seconds <= target_seconds
    passed = (
        semantic_equal
        and latency_pass
        and cache_correctness_pass
        and private_publish_pass
    )
    return {
        "case": case,
        "total_seconds": sample.total_seconds,
        "semantic_equal": semantic_equal,
        "latency_pass": latency_pass,
        "cache_correctness_pass": cache_correctness_pass,
        "cache_performance": cache_validation.performance,
        "private_publish_pass": private_publish_pass,
        "status": "PASS" if passed else "FAIL",
        "reason": (
            "PASS"
            if passed
            else "SEMANTIC_INEQUALITY"
            if not semantic_equal
            else "CACHE_CORRECTNESS_FAIL"
            if not cache_correctness_pass
            else "PRIVATE_PUBLISH_FAIL"
            if not private_publish_pass
            else "LATENCY_OVER_TARGET"
        ),
    }


def summarize_samples(
    samples: Sequence[PerfFSample],
    *,
    target_seconds: float = 15.0,
) -> dict[str, Any]:
    grouped: dict[str, list[PerfFSample]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample.case).upper()].append(sample)

    cases: dict[str, Any] = {}
    all_green = True
    for case in REQUIRED_CASES:
        rows = grouped.get(case, [])
        if not rows:
            cases[case] = {"status": "MISSING", "samples": 0}
            all_green = False
            continue
        validations = [validate_sample(row, target_seconds=target_seconds) for row in rows]
        totals = [row.total_seconds for row in rows]
        status = "PASS" if all(v["status"] == "PASS" for v in validations) else "FAIL"
        if status != "PASS":
            all_green = False
        cases[case] = {
            "status": status,
            "samples": len(rows),
            "median_seconds": median(totals),
            "max_seconds": max(totals),
            "exact_seconds": totals,
            "validations": validations,
        }
    return {
        "authority": "FPL_V12_PERF_F",
        "target_seconds": target_seconds,
        "all_required_cases_green": all_green,
        "cases": cases,
    }
