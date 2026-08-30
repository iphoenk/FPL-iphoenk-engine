from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = ROOT / "config"
OUTDIR = ROOT / "profile-output"


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    idx = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return round(ordered[idx], 3)


def stats(values):
    vals = [float(v) for v in values]
    if not vals:
        return {"n": 0, "min": None, "median": None, "p90": None, "p95": None, "max": None}
    return {
        "n": len(vals),
        "min": round(min(vals), 3),
        "median": round(statistics.median(vals), 3),
        "p90": percentile(vals, 0.90),
        "p95": percentile(vals, 0.95),
        "max": round(max(vals), 3),
    }


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def run_cmd(command, *, env=None, check=True):
    started = perf_counter()
    proc = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    wall_ms = (perf_counter() - started) * 1000.0
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed {command!r} exit={proc.returncode}\n"
            f"stdout={proc.stdout[-4000:]}\nstderr={proc.stderr[-4000:]}"
        )
    return proc, round(wall_ms, 3)


def network_ms_from_snapshot(snapshot):
    timing = snapshot.get("acquisition_timing") or {}
    return round(
        float(timing.get("initial_parallel_ms") or 0.0)
        + float(timing.get("dependent_parallel_ms") or 0.0)
        + float(timing.get("gw1_conditional_ms") or 0.0),
        3,
    )


def one_cold_run(index, label):
    proc, wall_ms = run_cmd([sys.executable, "-m", "src.services.orchestrator", "daily", "--stats", "--deep-stats"])
    orchestration = load(DATA / "service_orchestration_v4.json")
    snapshot = load(DATA / "runtime/snapshot.v1.json")
    decision = load(DATA / "decision_pipeline_v4.json")
    network_ms = network_ms_from_snapshot(snapshot)
    internal_ms = float(orchestration.get("duration_ms") or 0.0)
    return {
        "run": index,
        "label": label,
        "wall_ms": wall_ms,
        "orchestrator_internal_ms": round(internal_ms, 3),
        "pre_orchestration_process_import_guard_ms": round(max(0.0, wall_ms - internal_ms), 3),
        "external_network_wave_ms": network_ms,
        "wall_excluding_external_network_ms": round(max(0.0, wall_ms - network_ms), 3),
        "decision_pipeline_compute_ms": float((decision.get("timings") or {}).get("total_pipeline_ms") or 0.0),
        "optimizer_cache_hit": bool((decision.get("timings") or {}).get("optimizer_exact_cache_hit")),
        "prediction_cache_hit": bool(((load(DATA / "latest.json").get("performance") or {}).get("prediction_base_cache_hit"))),
        "service_ms": {row.get("id"): float(row.get("duration_ms") or 0.0) for row in orchestration.get("services") or []},
        "launch_order": orchestration.get("launch_order") or [],
        "completion_order": orchestration.get("completion_order") or [],
        "stdout_tail": proc.stdout[-1200:],
    }


def cold_benchmark(count):
    rows = []
    for idx in range(1, count + 1):
        rows.append(one_cold_run(idx, "fresh_process_persistent_exact_cache_eligible"))
    service_names = sorted({key for row in rows for key in row["service_ms"]})
    return {
        "method": "fresh orchestrator Python process per run; no pre-warm; persistent exact semantic disk caches remain eligible exactly as production permits",
        "runs": rows,
        "full_wall": stats([r["wall_ms"] for r in rows]),
        "orchestrator_internal": stats([r["orchestrator_internal_ms"] for r in rows]),
        "pre_orchestration_process_import_guard": stats([r["pre_orchestration_process_import_guard_ms"] for r in rows]),
        "external_network_wave": stats([r["external_network_wave_ms"] for r in rows]),
        "wall_excluding_external_network": stats([r["wall_excluding_external_network_ms"] for r in rows]),
        "decision_pipeline_compute": stats([r["decision_pipeline_compute_ms"] for r in rows]),
        "services": {name: stats([r["service_ms"].get(name, 0.0) for r in rows]) for name in service_names},
        "optimizer_cache_hits": sum(r["optimizer_cache_hit"] for r in rows),
        "prediction_cache_hits": sum(r["prediction_cache_hit"] for r in rows),
    }


def forced_cache_miss_benchmark(count):
    cache_paths = [
        DATA / "predictions_base_hot_cache_v4.json",
        DATA / "decision_hot_cache_v4.json",
    ]
    rows = []
    for idx in range(1, count + 1):
        for path in cache_paths:
            path.unlink(missing_ok=True)
        rows.append(one_cold_run(idx, "fresh_process_forced_exact_semantic_cache_miss"))
    return {
        "method": "fresh process with only the two governed exact semantic performance caches removed before each run; intelligence/search width unchanged",
        "runs": rows,
        "full_wall": stats([r["wall_ms"] for r in rows]),
        "wall_excluding_external_network": stats([r["wall_excluding_external_network_ms"] for r in rows]),
        "decision_pipeline_compute": stats([r["decision_pipeline_compute_ms"] for r in rows]),
    }


def fast_benchmark(count):
    rows = []
    for idx in range(1, count + 1):
        _, wall_ms = run_cmd([sys.executable, "-m", "src.services.hot_orchestrator", "daily", "--stats", "--deep-stats"])
        hot = load(DATA / "hot_orchestration_v4.json")
        rows.append({
            "run": idx,
            "launcher_wall_ms": wall_ms,
            "total_e2e_ms": float(hot.get("total_e2e_ms") or 0.0),
            "serving_e2e_ms": float(hot.get("serving_e2e_excluding_startup_assurance_ms") or 0.0),
            "startup_assurance_ms": float(hot.get("startup_assurance_ms") or 0.0),
            "official_ms": float(hot.get("official_acquisition_ms") or 0.0),
            "decision_ms": float(hot.get("decision_compute_ms") or 0.0),
            "optimizer_cache_hit": bool(hot.get("optimizer_cache_hit")),
        })
    warm = (load(DATA / "serving_benchmark_v4.json").get("warm_serving") or {})
    return {
        "runs": rows,
        "serving_e2e": stats([r["serving_e2e_ms"] for r in rows]),
        "full_hot_path": stats([r["total_e2e_ms"] for r in rows]),
        "startup_assurance": stats([r["startup_assurance_ms"] for r in rows]),
        "official_acquisition": stats([r["official_ms"] for r in rows]),
        "decision_compute": stats([r["decision_ms"] for r in rows]),
        "warm_serving_artifact": warm,
    }


def architecture_guard_benchmark(count=7):
    walls = []
    for _ in range(count):
        _, wall = run_cmd([sys.executable, "-m", "src.services.architecture_guard_service"])
        walls.append(wall)
    return {"fresh_process_wall": stats(walls)}


def import_profile(repeats=5):
    registry = load(CONFIG / "service_registry.json")
    modules = [str(row["module"]) for row in registry.get("services") or []]
    bare = []
    for _ in range(repeats):
        _, wall = run_cmd([sys.executable, "-c", "pass"])
        bare.append(wall)
    results = {}
    pattern_template = r"^import time:\s+(\d+)\s+\|\s+(\d+)\s+\|\s+{module}\s*$"
    for module in modules:
        walls, cumulative = [], []
        pattern = re.compile(pattern_template.format(module=re.escape(module)), re.MULTILINE)
        for _ in range(repeats):
            proc, wall = run_cmd([sys.executable, "-X", "importtime", "-c", f"import {module}"])
            walls.append(wall)
            matches = pattern.findall(proc.stderr)
            if matches:
                cumulative.append(float(matches[-1][1]) / 1000.0)
        results[module] = {
            "fresh_process_import_wall": stats(walls),
            "python_importtime_cumulative_ms": stats(cumulative),
            "estimated_wall_above_bare_python_median_ms": round(max(0.0, statistics.median(walls) - statistics.median(bare)), 3),
        }
    return {"bare_python_process_wall": stats(bare), "modules": results}


def dag_overlap_profile(trace_json_opens=False):
    from src.services.orchestrator import orchestrate

    registry = load(CONFIG / "service_registry.json")
    contracts = load(CONFIG / "service_contract_registry.json")
    by_module = {str(row.get("module")): str(row.get("id")) for row in registry.get("services") or []}
    intervals = {}
    lock = threading.Lock()
    trace_dir = OUTDIR / "strace"
    if trace_json_opens:
        trace_dir.mkdir(parents=True, exist_ok=True)
    strace = shutil.which("strace") if trace_json_opens else None

    def runner(command, **kwargs):
        module = None
        if "-m" in command:
            try:
                module = command[command.index("-m") + 1]
            except Exception:
                pass
        service_id = by_module.get(str(module), str(module or command[-1]))
        start = perf_counter()
        actual = list(command)
        trace_prefix = None
        if strace:
            trace_prefix = trace_dir / service_id
            actual = [strace, "-ff", "-e", "trace=openat", "-o", str(trace_prefix)] + actual
        proc = subprocess.run(actual, **kwargs)
        end = perf_counter()
        with lock:
            intervals[service_id] = {"start": start, "end": end, "duration_ms": round((end - start) * 1000.0, 3)}
        return proc

    t0 = perf_counter()
    report = orchestrate(service_registry=registry, contract_registry=contracts, runner=runner)
    t1 = perf_counter()
    normalized = {
        key: {
            "start_ms": round((value["start"] - t0) * 1000.0, 3),
            "end_ms": round((value["end"] - t0) * 1000.0, 3),
            "child_wall_ms": value["duration_ms"],
        }
        for key, value in intervals.items()
    }
    waits = {}
    for service in registry.get("services") or []:
        sid = service["id"]
        deps = service.get("depends_on") or []
        if not deps or sid not in normalized:
            continue
        dep_end = max(normalized[d]["end_ms"] for d in deps if d in normalized)
        waits[sid] = round(max(0.0, normalized[sid]["start_ms"] - dep_end), 3)

    overlap = None
    if "validation" in normalized and "optimization" in normalized:
        a, b = normalized["validation"], normalized["optimization"]
        overlap_ms = max(0.0, min(a["end_ms"], b["end_ms"]) - max(a["start_ms"], b["start_ms"]))
        denom = min(a["child_wall_ms"], b["child_wall_ms"])
        overlap = {
            "overlap_ms": round(overlap_ms, 3),
            "shorter_branch_overlap_efficiency": round(overlap_ms / denom, 4) if denom else None,
        }

    trace_summary = {}
    if strace:
        for service in by_module.values():
            counter = Counter()
            for path in trace_dir.glob(service + "*"):
                text = path.read_text(errors="replace")
                for match in re.finditer(r'openat\([^\n]*?"([^"\n]+\.json)"', text):
                    raw_path = match.group(1)
                    if raw_path.startswith(str(ROOT)):
                        raw_path = os.path.relpath(raw_path, ROOT)
                    counter[raw_path] += 1
            trace_summary[service] = [{"path": p, "opens": n} for p, n in counter.most_common() if n > 1][:50]

    return {
        "wall_ms": round((t1 - t0) * 1000.0, 3),
        "orchestrator_internal_ms": report.get("duration_ms"),
        "intervals": normalized,
        "dependency_ready_to_child_start_gap_ms": waits,
        "validation_optimization_overlap": overlap,
        "json_repeated_opens_by_service": trace_summary,
        "strace_available": bool(strace),
    }


def json_io_profile(repeats=15):
    from src.utils import _dumps_pretty, _loads

    candidates = [
        DATA / "runtime/snapshot.v1.json",
        DATA / "runtime/enrichment.v1.json",
        DATA / "predictions_v4.json",
        DATA / "universe.json",
        DATA / "latest.json",
        DATA / "decision_pipeline_v4.json",
        DATA / "tactical_serving_v4.json",
        DATA / "framework_health_preflight_v4.json",
        DATA / "framework_health_v4.json",
    ]
    results = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "artifact.json"
        for path in candidates:
            if not path.is_file():
                continue
            raw = path.read_bytes()
            payload = _loads(raw)
            read_times, parse_times, serialize_times, atomic_times = [], [], [], []
            for _ in range(repeats):
                t = perf_counter(); path.read_bytes(); read_times.append((perf_counter() - t) * 1000.0)
                t = perf_counter(); _loads(raw); parse_times.append((perf_counter() - t) * 1000.0)
                t = perf_counter(); dumped = _dumps_pretty(payload); serialize_times.append((perf_counter() - t) * 1000.0)
                t = perf_counter(); tmp.write_bytes(dumped); os.replace(tmp, tmp.with_suffix(".done")); tmp.with_suffix(".done").replace(tmp); atomic_times.append((perf_counter() - t) * 1000.0)
            results[str(path.relative_to(ROOT))] = {
                "bytes": len(raw),
                "read_bytes": stats(read_times),
                "parse": stats(parse_times),
                "serialize_pretty": stats(serialize_times),
                "tmp_write_plus_two_renames": stats(atomic_times),
            }
    return results


def summarize_root_causes(profile):
    cold = profile["cold"]
    services = cold.get("services") or {}
    ranked = sorted(
        ((name, values.get("median") or 0.0) for name, values in services.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return [{"rank": idx + 1, "component": name, "median_ms": ms} for idx, (name, ms) in enumerate(ranked)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cold-runs", type=int, default=10)
    parser.add_argument("--forced-miss-runs", type=int, default=3)
    parser.add_argument("--fast-runs", type=int, default=25)
    parser.add_argument("--trace-json-opens", action="store_true")
    args = parser.parse_args()
    OUTDIR.mkdir(exist_ok=True)

    profile = {
        "schema_version": 1,
        "purpose": "temporary observational V4 cold-orchestration profile; no production artifact schema changes",
        "python": sys.version,
        "cold": cold_benchmark(args.cold_runs),
        "forced_semantic_cache_miss": forced_cache_miss_benchmark(args.forced_miss_runs),
        "architecture_guard": architecture_guard_benchmark(),
        "imports": import_profile(),
        "dag": dag_overlap_profile(trace_json_opens=args.trace_json_opens),
        "json_io": json_io_profile(),
        "fast": fast_benchmark(args.fast_runs),
    }
    profile["root_causes_by_cold_service_median"] = summarize_root_causes(profile)
    out = OUTDIR / "v4-cold-profile.json"
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "cold_full_wall": profile["cold"]["full_wall"],
        "cold_ex_network": profile["cold"]["wall_excluding_external_network"],
        "fast": profile["fast"]["serving_e2e"],
        "warm": profile["fast"]["warm_serving_artifact"],
        "dag_overlap": profile["dag"]["validation_optimization_overlap"],
        "root_causes": profile["root_causes_by_cold_service_median"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
