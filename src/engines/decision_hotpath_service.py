from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from src.engines.lineup_governance import build_lineup_decision, build_package_decision
from src.rules import LINEUP_RULES
from src.runtime_v3.instant_serving import _config as serving_config
from src.runtime_v3.instant_serving import _require_files, _validate_contract
from src.utils import CONFIG, DATA, ROOT, read_json

REGISTRY_PATH = ROOT / "config" / "runtime" / "interactive_service_registry.json"


def _registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_INTERACTIVE_SERVICES_V1":
        raise RuntimeError("unexpected interactive service registry")
    return payload


def regenerate(data_dir: str | Path | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    root = Path(data_dir or os.getenv("FPL_DATA_DIR") or DATA)
    registry = _registry()
    cfg = serving_config()
    _require_files(cfg, root)

    required = [
        "projections.json",
        "package_optimizer.json",
        "team.json",
        "chips.json",
        "latest.json",
        "framework_health.json",
        "dss_watchlist_summary.json",
        "decision_brief.json",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise RuntimeError(f"REFRESH_REQUIRED: missing decision-hotpath artifacts: {missing}")

    latest = read_json(root / "latest.json", {})
    brief = read_json(root / "decision_brief.json", {})
    framework = read_json(root / "framework_health.json", {})
    watchlist = read_json(root / "dss_watchlist_summary.json", {})
    freshness = _validate_contract(cfg, latest, brief, framework, watchlist)

    projections = read_json(root / "projections.json", {})
    package_optimizer = read_json(root / "package_optimizer.json", {})
    team = read_json(root / "team.json", {})
    chips = read_json(root / "chips.json", {})
    lock = json.loads((CONFIG / "locked_squad.json").read_text(encoding="utf-8"))

    lineup = build_lineup_decision(projections, lock, chips)
    package = build_package_decision(package_optimizer, projections, lock, team)
    expected_xi = int(LINEUP_RULES.get("starting_xi_size") or 11)
    if not lineup.get("formation") or len(lineup.get("starting_xi") or []) != expected_xi:
        raise RuntimeError("DECISION_HOTPATH_FAIL: governed XI is not legal")
    if package.get("gate0_revalidated") is not True:
        raise RuntimeError("DECISION_HOTPATH_FAIL: package Gate0 revalidation failed")

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    hard_ceiling = float((registry.get("policy") or {}).get("hard_end_to_end_ceiling_ms") or 1000)
    if elapsed_ms > hard_ceiling:
        raise RuntimeError(f"DECISION_HOTPATH_SLO_BREACH: {elapsed_ms}ms > {hard_ceiling}ms")

    return {
        "schema_version": 1,
        "service": "decision_hotpath",
        "mode": "REGENERATED_FROM_FRESH_CANONICAL_PROJECTIONS",
        "refresh_required": False,
        "performance": {
            "elapsed_ms": elapsed_ms,
            "hard_ceiling_ms": hard_ceiling,
            "within_hard_ceiling": True,
        },
        "freshness": freshness,
        "planning_gw": projections.get("planning_gw"),
        "lineup": lineup,
        "package": package,
        "authority": {
            "official_fpl_native_authority_preserved": True,
            "locked_squad_authority_preserved": True,
            "canonical_projection_reused": True,
            "network_fetches": 0,
            "prediction_formula_recomputation": False,
            "governed_decision_recomputed": True,
        },
    }


def benchmark(data_dir: str | Path | None = None, repetitions: int = 5) -> dict[str, Any]:
    times: list[float] = []
    last: dict[str, Any] | None = None
    for _ in range(max(1, int(repetitions))):
        last = regenerate(data_dir)
        times.append(float((last.get("performance") or {}).get("elapsed_ms") or 0.0))
    ceiling = float(((_registry().get("policy") or {}).get("hard_end_to_end_ceiling_ms") or 1000))
    result = {
        "repetitions": len(times),
        "min_ms": round(min(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "max_ms": round(max(times), 3),
        "hard_ceiling_ms": ceiling,
        "pass": max(times) <= ceiling,
        "decision_recomputed": bool(last and (last.get("authority") or {}).get("governed_decision_recomputed")),
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
