from __future__ import annotations

import json
from time import perf_counter

from src.engines.v4_decision_pipeline import OUTFILE, run as run_decision_pipeline
from src.engines.v4_weather_tactical_overlay import apply_weather_overlay
from src.utils import atomic_json

DECISION_COMPUTE_SLO_MS = 5000.0


def run() -> dict:
    wall_started = perf_counter()
    runtime_context: dict = {}
    out = run_decision_pipeline(runtime_context=runtime_context)

    weather_started = perf_counter()
    tactical = apply_weather_overlay(
        predictions=runtime_context.get("predictions"),
        universe=runtime_context.get("universe"),
    )
    weather_ms = round((perf_counter() - weather_started) * 1000.0, 2)

    base_compute_ms = float((out.get("timings") or {}).get("total_pipeline_ms") or float("inf"))
    compute_ms = base_compute_ms + weather_ms
    wall_ms = round((perf_counter() - wall_started) * 1000.0, 2)
    status = "PASS" if compute_ms < DECISION_COMPUTE_SLO_MS else "FAIL"

    out.setdefault("timings", {})["weather_tactical_overlay_ms"] = weather_ms
    out["timings"]["total_pipeline_ms"] = round(compute_ms, 2)
    out["weather_context"] = {
        **(tactical.get("weather_context") or {}),
        "decision_chain_effect": "UNCERTAINTY_AND_TACTICAL_ADVISORY_ONLY",
        "expected_xpts_mean_adjustment": 0.0,
    }
    out["performance_slo"] = {
        "scope": "deterministic_decision_compute_excludes_external_source_network_io",
        "limit_ms": DECISION_COMPUTE_SLO_MS,
        "actual_ms": round(compute_ms, 2),
        "service_wall_ms": wall_ms,
        "status": status,
    }
    out.setdefault("performance_guardrails", {})["decision_compute_hard_slo_lt_5s"] = True
    out["performance_guardrails"]["external_network_latency_reported_separately"] = True
    out["performance_guardrails"]["weather_network_io_occurs_in_enrichment_not_decision_compute"] = True
    out["performance_guardrails"]["weather_mean_xpts_mutation"] = False
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "service": "optimization",
        "status": status,
        "decision_compute_ms": round(compute_ms, 2),
        "weather_overlay_ms": weather_ms,
        "weather_context": (tactical.get("weather_context") or {}).get("status"),
        "limit_ms": DECISION_COMPUTE_SLO_MS,
    }, ensure_ascii=False))
    if status != "PASS":
        raise RuntimeError(f"decision compute SLO exceeded: {compute_ms:.1f}ms >= {DECISION_COMPUTE_SLO_MS:.0f}ms")
    return out


if __name__ == "__main__":
    run()
