"""Compatibility facade for the retired decision-hotpath entrypoint.

Canonical interactive decision regeneration and validation is owned by
``src.runtime_v3.unified_fastpath``.  This module preserves the historical CLI and
Python-call surface without retaining a second implementation of the same logic.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from src.runtime_v3.unified_fastpath import run as run_unified_fastpath
from src.utils import ROOT

REGISTRY_PATH = ROOT / "config" / "runtime" / "interactive_service_registry.json"


def _registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_INTERACTIVE_SERVICES_V1":
        raise RuntimeError("unexpected interactive service registry")
    return payload


def regenerate(data_dir: str | Path | None = None) -> dict[str, Any]:
    canonical = run_unified_fastpath(data_dir)
    performance = canonical.get("performance") or {}
    authority = canonical.get("authority") or {}
    return {
        "schema_version": 1,
        "service": "decision_hotpath",
        "mode": "COMPATIBILITY_FACADE_TO_UNIFIED_FASTPATH",
        "refresh_required": bool(canonical.get("refresh_required", False)),
        "performance": {
            "elapsed_ms": performance.get("elapsed_ms"),
            "hard_ceiling_ms": performance.get("hard_ceiling_ms"),
            "within_hard_ceiling": performance.get("within_hard_ceiling"),
        },
        "freshness": canonical.get("freshness"),
        "planning_gw": canonical.get("planning_gw"),
        "lineup": canonical.get("lineup"),
        "package": canonical.get("package"),
        "authority": {
            "official_fpl_native_authority_preserved": bool(authority.get("official_fpl_native_authority")),
            "locked_squad_authority_preserved": bool(authority.get("user_decision_authority_preserved")),
            "canonical_projection_reused": bool(authority.get("canonical_projection_reused")),
            "network_fetches": int(authority.get("network_fetches") or 0),
            "prediction_formula_recomputation": bool(authority.get("prediction_formula_recomputation")),
            "governed_decision_recomputed": bool(authority.get("governed_decision_recomputed")),
            "canonical_interactive_owner": "unified_fastpath",
        },
    }


def benchmark(data_dir: str | Path | None = None, repetitions: int = 5) -> dict[str, Any]:
    times: list[float] = []
    last: dict[str, Any] | None = None
    for _ in range(max(1, int(repetitions))):
        last = regenerate(data_dir)
        times.append(float((last.get("performance") or {}).get("elapsed_ms") or 0.0))
    ceiling = float(((_registry().get("policy") or {}).get("hard_end_to_end_ceiling_ms") or 2000))
    result = {
        "repetitions": len(times),
        "min_ms": round(min(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "max_ms": round(max(times), 3),
        "hard_ceiling_ms": ceiling,
        "pass": max(times) <= ceiling,
        "decision_recomputed": bool(last and (last.get("authority") or {}).get("governed_decision_recomputed")),
        "compatibility_facade": True,
        "canonical_owner": "unified_fastpath",
    }
    if not result["pass"]:
        raise RuntimeError(f"DECISION_HOTPATH_BENCHMARK_FAIL: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    out = benchmark(args.data_dir, args.repetitions) if args.benchmark else regenerate(args.data_dir)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
