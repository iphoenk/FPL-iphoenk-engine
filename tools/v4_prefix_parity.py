from __future__ import annotations

import json
from itertools import accumulate
from time import perf_counter

from src.engines import v4_wc_package_audit_fast as fast
from src.engines.v4_decision_pipeline import effective_planning_squad
from src.engines.v4_wc_optimizer import build_candidates
from src.utils import CONFIG, DATA, read_json


def reference_prefix(values):
    out = [0.0]
    for value in values:
        out.append(out[-1] + value)
    return out


def optimized_prefix(values):
    return list(accumulate(values, initial=0.0))


def main() -> None:
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    team = read_json(DATA / "team.json", {})
    latest = read_json(DATA / "latest.json", {})
    configured = read_json(CONFIG / "locked_squad.json", {})
    locked = effective_planning_squad(team, configured, latest)
    candidates = build_candidates(predictions, universe)

    original = fast._prefix
    try:
        fast._prefix = reference_prefix
        t0 = perf_counter()
        reference = fast.audit_packages_from_candidates_fast(candidates, locked)
        reference_ms = (perf_counter() - t0) * 1000.0

        fast._prefix = optimized_prefix
        t0 = perf_counter()
        optimized = fast.audit_packages_from_candidates_fast(candidates, locked)
        optimized_ms = (perf_counter() - t0) * 1000.0
    finally:
        fast._prefix = original

    if reference != optimized:
        raise SystemExit("prefix optimization changed exact package output")
    print(json.dumps({
        "exact_package_parity": True,
        "reference_ms": round(reference_ms, 3),
        "optimized_ms": round(optimized_ms, 3),
        "speedup_ms": round(reference_ms - optimized_ms, 3),
        "speedup_ratio": round(reference_ms / max(optimized_ms, 1e-9), 4),
        "evaluated_packages": (optimized.get("performance") or {}).get("evaluated_packages"),
        "beam_size": (optimized.get("performance") or {}).get("beam_size"),
        "frontier_per_position": (optimized.get("performance") or {}).get("frontier_per_position"),
        "search_quality_reduction": (optimized.get("performance") or {}).get("search_quality_reduction"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
