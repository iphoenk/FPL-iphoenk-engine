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
from src.runtime_v3.instant_serving import _performance_contract, _require_files, _validate_contract
from src.utils import DATA, ROOT, read_json

REGISTRY_PATH = ROOT / "config" / "runtime" / "interactive_service_registry.json"
SERVICE_NAME = "unified_fastpath"
SERVICE_MODULE = "src.runtime_v3.unified_fastpath"


def _registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_INTERACTIVE_SERVICES_V1":
        raise RuntimeError("unexpected interactive service registry")
    policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
    if policy.get("performance_slo_registry") != "config/runtime/performance_slo.json":
        raise RuntimeError("interactive performance SLO registry drift")
    if policy.get("performance_slo_profile") != "instant_serving":
        raise RuntimeError("interactive performance SLO profile drift")
    services = payload.get("services") if isinstance(payload.get("services"), dict) else {}
    service = services.get(SERVICE_NAME)
    if not isinstance(service, dict):
        raise RuntimeError(f"interactive service registry missing {SERVICE_NAME}")
    if service.get("module") != SERVICE_MODULE:
        raise RuntimeError(f"interactive service module drift: {service.get('module')}")
    consumes = service.get("consumes")
    if not isinstance(consumes, list) or not consumes:
        raise RuntimeError(f"interactive service {SERVICE_NAME} has no declared inputs")
    return payload


def _service_inputs(registry: dict[str, Any]) -> tuple[tuple[str, ...], tuple[Path, ...]]:
    service = ((registry.get("services") or {}).get(SERVICE_NAME) or {})
    consumes = [str(value) for value in service.get("consumes") or []]
    data_names: list[str] = []
    config_paths: list[Path] = []
    for value in consumes:
        if value.startswith("config/"):
            config_paths.append(ROOT / value)
        else:
            data_names.append(value.removeprefix("data/"))
    if len(data_names) != len(set(data_names)) or len(config_paths) != len(set(config_paths)):
        raise RuntimeError(f"interactive service {SERVICE_NAME} has duplicate declared inputs")
    return tuple(data_names), tuple(config_paths)


def _locked_squad(config_paths: tuple[Path, ...]) -> dict[str, Any]:
    matches = [path for path in config_paths if path.name == "locked_squad.json"]
    if len(matches) != 1:
        raise RuntimeError(f"interactive service {SERVICE_NAME} must declare exactly one locked_squad config input")
    path = matches[0]
    if not path.is_file():
        raise RuntimeError(f"REFRESH_REQUIRED: missing unified-fastpath config artifact: {path.relative_to(ROOT)}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError("REFRESH_REQUIRED: locked_squad config is missing/empty")
    return payload


def run(data_dir: str | Path | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    root = Path(data_dir or os.getenv("FPL_DATA_DIR") or DATA)
    registry = _registry()
    cfg = serving_config()
    performance = _performance_contract(cfg)
    _require_files(cfg, root)
    data_names, config_paths = _service_inputs(registry)
    payloads = {name: read_json(root / name, {}) for name in data_names}
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
    lock = _locked_squad(config_paths)
    lineup = build_lineup_decision(projections, lock, chips)
    package = build_package_decision(package_optimizer, projections, lock, team)
    expected_xi = int(LINEUP_RULES.get("starting_xi_size") or 11)
    if not lineup.get("formation") or len(lineup.get("starting_xi") or []) != expected_xi:
        raise RuntimeError("UNIFIED_FASTPATH_FAIL: governed XI is not legal")
    if package.get("gate0_revalidated") is not True:
        raise RuntimeError("UNIFIED_FASTPATH_FAIL: package Gate0 revalidation failed")
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    target_ms = float(performance["target_wall_ms"])
    hard_ceiling_ms = float(performance["hard_ceiling_ms"])
    if elapsed_ms > hard_ceiling_ms:
        raise RuntimeError(f"UNIFIED_FASTPATH_SLO_BREACH: {elapsed_ms}ms > {hard_ceiling_ms}ms")
    return {
        "schema_version": 1,
        "service": SERVICE_NAME,
        "serving_mode": "VALIDATED_REGENERATED_FROM_FRESH_CANONICAL_STATE",
        "refresh_required": False,
        "performance": {"elapsed_ms": elapsed_ms, "preferred_target_ms": target_ms, "hard_ceiling_ms": hard_ceiling_ms, "within_preferred_target": elapsed_ms <= target_ms, "within_hard_ceiling": True, "slo_profile": performance["profile"]},
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
        "authority": {"official_fpl_native_authority": True, "user_decision_authority_preserved": True, "canonical_projection_reused": True, "governed_decision_recomputed": True, "network_fetches": 0, "prediction_formula_recomputation": False, "framework_green": framework.get("overall") == "GREEN", "gate0_pass": int(((framework.get("gate0") or {}).get("counts") or {}).get("PASS") or 0), "materialized_user_report_present": bool(user_report)},
    }


def benchmark(data_dir: str | Path | None = None, repetitions: int = 7) -> dict[str, Any]:
    cfg = serving_config()
    performance = _performance_contract(cfg)
    times: list[float] = []
    last: dict[str, Any] | None = None
    for _ in range(max(1, int(repetitions))):
        last = run(data_dir)
        times.append(float((last.get("performance") or {}).get("elapsed_ms") or 0.0))
    preferred = float(performance["target_wall_ms"])
    ceiling = float(performance["hard_ceiling_ms"])
    result = {"repetitions": len(times), "min_ms": round(min(times), 3), "median_ms": round(statistics.median(times), 3), "max_ms": round(max(times), 3), "preferred_target_ms": preferred, "hard_ceiling_ms": ceiling, "slo_profile": performance["profile"], "preferred_pass": max(times) <= preferred, "hard_pass": max(times) <= ceiling, "freshness": (last or {}).get("freshness")}
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
