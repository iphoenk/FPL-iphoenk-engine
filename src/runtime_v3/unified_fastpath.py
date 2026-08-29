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


def run(data_dir: str | Path | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    root = Path(data_dir or os.getenv("FPL_DATA_DIR") or DATA)
    registry = _registry()
    cfg = serving_config()
    _require_files(cfg, root)

    # Single-pass canonical artifact load. The old decision-hotpath and gateway
    # both loaded overlapping state separately; V3.27 validates once and serves once.
    names = (
        "latest.json",
        "decision_brief.json",
        "user_report.json",
        "framework_health.json",
        "dss_watchlist_summary.json",
        "projections.json",
        "package_optimizer.json",
        "team.json",
        "chips.json",
    )
    payloads = {name: read_json(root / name, {}) for name in names}
    missing = [name for name, payload in payloads.items() if not payload]
    if missing:
        raise RuntimeError(f"REFRESH_REQUIRED: missing/empty unified-fastpath artifacts: {missing}")

    latest = payloads["latest.json"]
    brief = payloads["decision_brief.json"]
    user_report = payloads["user_report.json"]
    framework = payloads["framework_health.json"]
    watchlist = payloads["dss_watchlist_summary.json"]
    freshness = _validate_contract(cfg, latest, brief, framework, watchlist)

    projections = payloads["projections.json"]
    package_optimizer = payloads["package_optimizer.json"]
    team = payloads["team.json"]
    chips = payloads["chips.json"]
    lock = json.loads((CONFIG / "locked_squad.json").read_text(encoding="utf-8"))

    lineup = build_lineup_decision(projections, lock, chips)
    package = build_package_decision(package_optimizer, projections, lock, team)
    expected_xi = int(LINEUP_RULES.get("starting_xi_size") or 11)
    if not lineup.get("formation") or len(lineup.get("starting_xi") or []) != expected_xi:
        raise RuntimeError("UNIFIED_FASTPATH_FAIL: governed XI is not legal")
    if package.get("gate0_revalidated") is not True:
        raise RuntimeError("UNIFIED_FASTPATH_FAIL: package Gate0 revalidation failed")

    policy = registry.get("policy") or {}
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    target_ms = float(policy.get("preferred_end_to_end_target_ms") or 1000)
    hard_ceiling_ms = float(policy.get("hard_end_to_end_ceiling_ms") or 2000)
    if elapsed_ms > hard_ceiling_ms:
        raise RuntimeError(f"UNIFIED_FASTPATH_SLO_BREACH: {elapsed_ms}ms > {hard_ceiling_ms}ms")

    return {
        "schema_version": 1,
        "service": "unified_fastpath",
        "serving_mode": "VALIDATED_REGENERATED_FROM_FRESH_CANONICAL_STATE",
        "refresh_required": False,
        "performance": {
            "elapsed_ms": elapsed_ms,
            "preferred_target_ms": target_ms,
            "hard_ceiling_ms": hard_ceiling_ms,
            "within_preferred_target": elapsed_ms <= target_ms,
            "within_hard_ceiling": True,
        },
        "freshness": freshness,
        "planning_gw": brief.get("planning_gw"),
        "decision": brief.get("decision"),
        "lineup": lineup,
        "package": package,
        "gameweek_context": brief.get("gameweek_context"),
        "finance": brief.get("finance"),
        "owned_15": brief.get("owned_15"),
        "main_starting_xi_battle": brief.get("main_starting_xi_battle"),
        "captaincy": brief.get("captaincy"),
        "chip": brief.get("chip"),
        "price_radar": brief.get("price_radar"),
        "watchlist_20": brief.get("watchlist_20"),
        "action_board": brief.get("action_board"),
        "report_time_intelligence": brief.get("report_time_intelligence"),
        "engine": brief.get("engine"),
        "authority": {
            "official_fpl_native_authority": True,
            "user_decision_authority_preserved": True,
            "canonical_projection_reused": True,
            "governed_decision_recomputed": True,
            "network_fetches": 0,
            "prediction_formula_recomputation": False,
            "framework_green": framework.get("overall") == "GREEN",
            "gate0_pass": int(((framework.get("gate0") or {}).get("counts") or {}).get("PASS") or 0),
            "materialized_user_report_present": bool(user_report),
        },
    }


def benchmark(data_dir: str | Path | None = None, repetitions: int = 7) -> dict[str, Any]:
    times: list[float] = []
    last: dict[str, Any] | None = None
    for _ in range(max(1, int(repetitions))):
        last = run(data_dir)
        times.append(float((last.get("performance") or {}).get("elapsed_ms") or 0.0))
    policy = _registry().get("policy") or {}
    preferred = float(policy.get("preferred_end_to_end_target_ms") or 1000)
    ceiling = float(policy.get("hard_end_to_end_ceiling_ms") or 2000)
    result = {
        "repetitions": len(times),
        "min_ms": round(min(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "max_ms": round(max(times), 3),
        "preferred_target_ms": preferred,
        "hard_ceiling_ms": ceiling,
        "preferred_pass": max(times) <= preferred,
        "hard_pass": max(times) <= ceiling,
        "freshness": (last or {}).get("freshness"),
    }
    if not result["hard_pass"]:
        raise RuntimeError(f"UNIFIED_FASTPATH_BENCHMARK_FAIL: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--repetitions", type=int, default=7)
    args = parser.parse_args()
    out = benchmark(args.data_dir, args.repetitions) if args.benchmark else run(args.data_dir)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
