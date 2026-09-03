from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.utils import DATA, atomic_json, read_json

REGISTRY = "V3_SHARDED_OPTIMIZER_RESOURCE_TELEMETRY_V1"


def _bytes(path: Path) -> int:
    return int(path.stat().st_size) if path.is_file() else 0


def _measurement(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_PROCESS_RESOURCE_MEASUREMENT_V1":
        raise RuntimeError(f"invalid process resource measurement: {path}")
    if int(payload.get("exit_code") or 0) != 0:
        raise RuntimeError(f"failed child command cannot contribute accepted telemetry: {path}")
    if int(payload.get("peak_rss_kb") or 0) <= 0:
        raise RuntimeError(f"missing peak RSS telemetry: {path}")
    return payload


def aggregate(plan_path: Path, shard_dir: Path, reducer_resource: Path, performance_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    reducer = _measurement(reducer_resource)
    shard_measurements = sorted(shard_dir.glob("resource-*.json"))
    expected = int(plan.get("shard_count") or 0)
    if len(shard_measurements) != expected:
        raise RuntimeError(f"resource telemetry shard count mismatch expected={expected} actual={len(shard_measurements)}")
    workers = [_measurement(path) for path in shard_measurements]

    seed_paths = [DATA / "projections.json", DATA / "team.json", plan_path]
    if not all(path.is_file() for path in seed_paths):
        raise RuntimeError("sharded resource telemetry missing seed input material")
    optimizer_path = DATA / "package_optimizer.json"
    if not optimizer_path.is_file():
        raise RuntimeError("sharded resource telemetry missing reduced optimizer output")

    shard_evidence_paths = [path for path in shard_dir.glob("shard-*.json") if path.is_file()]
    seed_input_bytes = sum(_bytes(path) for path in seed_paths)
    temporary_bytes = sum(_bytes(path) for path in shard_evidence_paths + shard_measurements) + _bytes(reducer_resource)
    promoted_output_bytes = _bytes(optimizer_path)
    worker_peak = max(int(row["peak_rss_kb"]) for row in workers)
    reducer_peak = int(reducer["peak_rss_kb"])

    performance = read_json(performance_path, {})
    if not isinstance(performance, dict):
        raise RuntimeError("runtime performance payload must be an object")
    performance["resources"] = {
        "peak_rss_kb": reducer_peak,
        "child_peak_rss_kb": worker_peak,
        "temporary_bytes": temporary_bytes,
        "seed_input_bytes": seed_input_bytes,
        "promoted_output_bytes": promoted_output_bytes,
        "semantics": {
            "peak_rss_kb": "EXACT_REDUCER_CHILD_PROCESS_PEAK",
            "child_peak_rss_kb": "MAX_DISTRIBUTED_SHARD_WORKER_PROCESS_PEAK",
            "temporary_bytes": "SHARD_EVIDENCE_PLUS_RESOURCE_EVIDENCE_BYTES",
            "seed_input_bytes": "PROJECTIONS_PLUS_TEAM_PLUS_SHARD_PLAN_BYTES",
            "promoted_output_bytes": "FINAL_PACKAGE_OPTIMIZER_BYTES",
        },
    }
    sharded = performance.setdefault("sharded_precompute", {})
    sharded["resource_telemetry_registry"] = REGISTRY
    sharded["distributed_worker_count"] = len(workers)
    sharded["distributed_worker_peak_rss_kb"] = worker_peak
    sharded["reducer_peak_rss_kb"] = reducer_peak
    sharded["shard_worker_elapsed_ms"] = [float(row.get("elapsed_ms") or 0.0) for row in workers]
    sharded["resource_observability_complete"] = True
    atomic_json(performance_path, performance)

    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("runtime_architecture", {})["sharded_resource_telemetry"] = {
        "registry": REGISTRY,
        "distributed_worker_count": len(workers),
        "distributed_worker_peak_rss_kb": worker_peak,
        "reducer_peak_rss_kb": reducer_peak,
        "complete": True,
    }
    atomic_json(DATA / "latest.json", latest)
    return performance


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate exact resource evidence for V3 cross-runner optimizer")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--shard-dir", required=True)
    parser.add_argument("--reducer-resource", required=True)
    parser.add_argument("--performance", default=str(DATA / "runtime_performance.json"))
    args = parser.parse_args()
    performance = aggregate(Path(args.plan), Path(args.shard_dir), Path(args.reducer_resource), Path(args.performance))
    print(json.dumps({
        "status": "PASS",
        "registry": REGISTRY,
        "resources": performance.get("resources"),
        "distributed_worker_count": (performance.get("sharded_precompute") or {}).get("distributed_worker_count"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
