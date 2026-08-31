from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT, read_json

CONFIG_PATH = ROOT / "config" / "runtime" / "instant_serving.json"
CANONICAL_SLO_PATH = "config/runtime/performance_slo.json"


def _config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_INSTANT_SERVING_V1":
        raise RuntimeError("unexpected instant-serving registry")
    return payload


def _performance_contract(cfg: dict[str, Any]) -> dict[str, Any]:
    performance = cfg.get("performance") if isinstance(cfg.get("performance"), dict) else {}
    registry_path = str(performance.get("slo_registry") or "")
    profile = str(performance.get("slo_profile") or "")
    if registry_path != CANONICAL_SLO_PATH or profile != "instant_serving":
        raise RuntimeError(f"INSTANT_SERVING_SLO_AUTHORITY_DRIFT registry={registry_path!r} profile={profile!r}")
    slo = json.loads((ROOT / registry_path).read_text(encoding="utf-8"))
    if slo.get("registry") != "RUNTIME_PERFORMANCE_SLO_V1":
        raise RuntimeError("unexpected canonical performance SLO registry")
    contract = (slo.get("profiles") or {}).get(profile)
    if not isinstance(contract, dict):
        raise RuntimeError(f"missing canonical performance SLO profile: {profile}")
    target = float(contract.get("target_wall_ms") or 0)
    ceiling = float(contract.get("legacy_ceiling_ms") or 0)
    if target <= 0 or ceiling <= 0 or target > ceiling:
        raise RuntimeError(f"invalid canonical performance SLO profile: {profile}")
    return {**contract, "profile": profile, "target_wall_ms": target, "hard_ceiling_ms": ceiling}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _phase_freshness_seconds(cfg: dict[str, Any], latest: dict[str, Any]) -> tuple[str, int]:
    phase = latest.get("phase") if isinstance(latest.get("phase"), dict) else {}
    windows = cfg.get("freshness_seconds") or {}
    if phase.get("is_live_event"):
        return "live", int(windows.get("live") or 90)
    deadline = _parse_dt(phase.get("deadline_time"))
    if deadline is not None:
        delta = (deadline - datetime.now(timezone.utc)).total_seconds()
        if 0 <= delta <= 24 * 3600:
            return "deadline_day", int(windows.get("deadline_day") or 120)
    return "normal", int(windows.get("normal") or 300)


def _require_files(cfg: dict[str, Any], data_dir: Path) -> None:
    missing = [str(name) for name in cfg.get("required_artifacts") or [] if not (data_dir / str(name)).is_file()]
    if missing:
        raise RuntimeError(f"REFRESH_REQUIRED: missing instant-serving artifacts: {missing}")


def _validate_contract(cfg: dict[str, Any], latest: dict[str, Any], brief: dict[str, Any], framework: dict[str, Any], watchlist: dict[str, Any]) -> dict[str, Any]:
    contract = cfg.get("contract") or {}
    serving = brief.get("serving_contract") if isinstance(brief.get("serving_contract"), dict) else {}
    expected_owned = int(contract.get("owned_count") or 15)
    expected_watch = int(contract.get("watchlist_count") or 20)
    if int(serving.get("owned") or 0) != expected_owned:
        raise RuntimeError(f"REFRESH_REQUIRED: owned contract {serving.get('owned')} != {expected_owned}")
    if int(serving.get("watchlist") or 0) != expected_watch:
        raise RuntimeError(f"REFRESH_REQUIRED: watchlist contract {serving.get('watchlist')} != {expected_watch}")
    gate0 = framework.get("gate0") if isinstance(framework.get("gate0"), dict) else {}
    counts = gate0.get("counts") if isinstance(gate0.get("counts"), dict) else {}
    expected_gate0 = int(contract.get("gate0_pass") or 16)
    if framework.get("overall") != "GREEN" or framework.get("decision_engine") != "HEALTHY":
        raise RuntimeError("REFRESH_REQUIRED: framework is not GREEN/HEALTHY")
    if gate0.get("pass") is not True or int(counts.get("PASS") or 0) != expected_gate0:
        raise RuntimeError("REFRESH_REQUIRED: Gate0 is not fully passing")
    watch_count = watchlist.get("count")
    if watch_count is not None and int(watch_count) != expected_watch:
        raise RuntimeError(f"REFRESH_REQUIRED: public watchlist count {watch_count} != {expected_watch}")
    generated_at = _parse_dt(brief.get("generated_at"))
    if generated_at is None:
        raise RuntimeError("REFRESH_REQUIRED: decision_brief.generated_at is missing or invalid")
    phase_name, max_age = _phase_freshness_seconds(cfg, latest)
    age_seconds = max(0.0, (datetime.now(timezone.utc) - generated_at).total_seconds())
    if age_seconds > max_age:
        raise RuntimeError(f"REFRESH_REQUIRED: materialized decision is stale ({age_seconds:.1f}s > {max_age}s for {phase_name})")
    return {"phase_freshness_policy": phase_name, "age_seconds": round(age_seconds, 3), "max_age_seconds": max_age, "generated_at": generated_at.isoformat()}


def serve(data_dir: str | Path | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    root = Path(data_dir or os.getenv("FPL_DATA_DIR") or DATA)
    cfg = _config()
    performance = _performance_contract(cfg)
    _require_files(cfg, root)
    latest = read_json(root / "latest.json", {})
    user_report = read_json(root / "user_report.json", {})
    brief = read_json(root / "decision_brief.json", {})
    framework = read_json(root / "framework_health.json", {})
    watchlist = read_json(root / "dss_watchlist_summary.json", {})
    freshness = _validate_contract(cfg, latest, brief, framework, watchlist)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    hard_ceiling = float(performance["hard_ceiling_ms"])
    if elapsed_ms > hard_ceiling:
        raise RuntimeError(f"INSTANT_SERVING_SLO_BREACH: {elapsed_ms}ms > {hard_ceiling}ms")
    return {
        "schema_version": 1,
        "serving_mode": "VALIDATED_WARM_MATERIALIZED",
        "refresh_required": False,
        "performance": {"elapsed_ms": elapsed_ms, "target_wall_ms": float(performance["target_wall_ms"]), "hard_ceiling_ms": hard_ceiling, "within_hard_ceiling": True, "slo_profile": performance["profile"]},
        "freshness": freshness,
        "planning_gw": brief.get("planning_gw"),
        "decision": brief.get("decision"),
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
        "authority": {"official_fpl_native_authority": True, "user_decision_authority_preserved": True, "framework_green": framework.get("overall") == "GREEN", "gate0_pass": int(((framework.get("gate0") or {}).get("counts") or {}).get("PASS") or 0), "materialized_user_report_present": bool(user_report)},
    }


def benchmark(data_dir: str | Path | None = None, repetitions: int | None = None) -> dict[str, Any]:
    cfg = _config()
    performance = _performance_contract(cfg)
    count = int(repetitions or (cfg.get("performance") or {}).get("benchmark_repetitions") or 5)
    times: list[float] = []
    last: dict[str, Any] | None = None
    for _ in range(max(1, count)):
        last = serve(data_dir)
        times.append(float((last.get("performance") or {}).get("elapsed_ms") or 0.0))
    ceiling = float(performance["hard_ceiling_ms"])
    result = {"repetitions": len(times), "min_ms": round(min(times), 3), "median_ms": round(statistics.median(times), 3), "max_ms": round(max(times), 3), "target_wall_ms": float(performance["target_wall_ms"]), "hard_ceiling_ms": ceiling, "slo_profile": performance["profile"], "pass": max(times) <= ceiling, "freshness": (last or {}).get("freshness")}
    if not result["pass"]:
        raise RuntimeError(f"INSTANT_SERVING_BENCHMARK_FAIL: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--repetitions", type=int)
    args = parser.parse_args()
    out = benchmark(args.data_dir, args.repetitions) if args.benchmark else serve(args.data_dir)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
