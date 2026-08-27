from __future__ import annotations

import json
from time import perf_counter

from src.engines.v4_decision_pipeline import OUTFILE, run as run_decision_pipeline
from src.utils import atomic_json

DECISION_COMPUTE_SLO_MS = 5000.0


def run() -> dict:
    wall_started = perf_counter()
    out = run_decision_pipeline()
    compute_ms = float((out.get("timings") or {}).get("total_pipeline_ms") or float("inf"))
    wall_ms = round((perf_counter() - wall_started) * 1000.0, 2)
    status = "PASS" if compute_ms < DECISION_COMPUTE_SLO_MS else "FAIL"
    out["performance_slo"] = {
        "scope": "deterministic_decision_compute_excludes_external_source_network_io",
        "limit_ms": DECISION_COMPUTE_SLO_MS,
        "actual_ms": compute_ms,
        "service_wall_ms": wall_ms,
        "status": status,
    }
    out.setdefault("performance_guardrails", {})["decision_compute_hard_slo_lt_5s"] = True
    out["performance_guardrails"]["external_network_latency_reported_separately"] = True
    atomic_json(OUTFILE, out)
    print(json.dumps({"service": "optimization", "status": status, "decision_compute_ms": compute_ms, "limit_ms": DECISION_COMPUTE_SLO_MS}, ensure_ascii=False))
    if status != "PASS":
        raise RuntimeError(f"decision compute SLO exceeded: {compute_ms:.1f}ms >= {DECISION_COMPUTE_SLO_MS:.0f}ms")
    return out


if __name__ == "__main__":
    run()
