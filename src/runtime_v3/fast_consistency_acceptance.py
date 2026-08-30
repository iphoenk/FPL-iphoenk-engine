from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

from src.utils import DATA, ROOT, read_json

POLICY_PATH = ROOT / "config" / "runtime" / "fast_lane_policy.json"
PERFORMANCE_PATH = DATA / "runtime_performance.json"


def run() -> dict:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    repetitions = int(policy.get("consecutive_candidate_runs") or 3)
    hard_ms = float(policy.get("hard_wall_ms") or 3000.0)
    values: list[float] = []
    for index in range(repetitions):
        proc = subprocess.run(
            [sys.executable, "-m", "src.runtime_v3.domain_orchestrator", "--mode", "daily", "--stats", "--profile", "fast_decision"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"FAST consistency run {index + 1} failed: {(proc.stderr or proc.stdout)[-3000:]}")
        perf = read_json(PERFORMANCE_PATH, {})
        value = float(perf.get("total_wall_ms") or 1e12)
        values.append(value)
        execution = perf.get("domain_process_execution") or {}
        if not execution.get("coalesced_fast_lane"):
            raise RuntimeError("FAST consistency acceptance requires coalesced fast lane")
        if execution.get("execution_boundary") != "IN_PROCESS_COALESCED":
            raise RuntimeError("FAST lane execution-boundary drift")
        if execution.get("fallback_to_multi_process_allowed"):
            raise RuntimeError("FAST lane may not silently fall back after partial execution")
        if value > hard_ms:
            raise RuntimeError(f"FAST run {index + 1} exceeded hard SLO: {value:.3f}ms > {hard_ms:.3f}ms")
    result = {
        "status": "PASS",
        "contract": "V3_FAST_CONSISTENCY_V1",
        "repetitions": repetitions,
        "hard_wall_ms": hard_ms,
        "runs_ms": [round(v, 3) for v in values],
        "min_ms": round(min(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "max_ms": round(max(values), 3),
        "all_under_hard_slo": all(v <= hard_ms for v in values),
        "fresh_process_each_run": True,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
