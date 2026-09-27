from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "performance" / "v12_perf_a.json"
NORMALIZED_DISABLE = (
    "X86_V4,AVX512F,AVX512CD,AVX512_KNL,AVX512_KNM,"
    "AVX512_SKX,AVX512_CLX,AVX512_CNL,AVX512_ICL,AVX512_SPR"
)


def _config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _child(runtime_class: str, output: Path) -> int:
    # NumPy must only be imported after the child process was launched with the
    # requested runtime environment.
    from src.engines.v12_cache_runtime_identity import runtime_cache_identity
    from src.engines.v12_monte_carlo import (
        package_route_definitions,
        run_correlated_monte_carlo,
    )
    from src.engines.v12_monte_carlo_acceptance import build_acceptance_fixture

    cfg = _config()
    projections, package = build_acceptance_fixture()
    route_defs = package_route_definitions(package, route_ids=["R1"])
    started = time.perf_counter()
    result = run_correlated_monte_carlo(
        projections,
        route_defs,
        actual_paths=int(cfg["actual_paths"]),
        seed=int(cfg["seed"]),
        input_snapshot_id=str(cfg["input_snapshot_id"]),
        canonical=True,
        horizons=tuple(int(x) for x in cfg["horizons"]),
        selected_route_id="R1",
        generated_at="2026-09-20T01:09:04Z",
        factual_snapshot_timestamps={
            "acceptance_fixture": "2026-09-20T01:09:04Z"
        },
    )
    elapsed = time.perf_counter() - started
    payload = {
        "runtime_class": runtime_class,
        "elapsed_seconds": elapsed,
        "status": result.get("status"),
        "canonical_pass": result.get("canonical_pass"),
        "actual_paths": result.get("actual_paths"),
        "seed": result.get("seed"),
        "input_snapshot_id": cfg["input_snapshot_id"],
        "output_fingerprint": result.get("output_fingerprint"),
        "run_fingerprint": result.get("run_fingerprint"),
        "selected_metrics": (result.get("metrics") or {}).get("R1", {}).get("1"),
        "runtime_cache_identity": runtime_cache_identity(),
    }
    output.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if payload["status"] == "PASS" and payload["canonical_pass"] is True else 2


def _env(runtime_class: str) -> dict[str, str]:
    env = dict(os.environ)
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["V12_PRIVATE_CACHE_PROFILE"] = "SECURE_NO_PERSONAL_CACHE"
    env.pop("V12_P17_DECISION_CACHE_DIR", None)
    env.pop("V12_MC_SIM_CACHE_DIR", None)
    if runtime_class == "NORMALIZED":
        env["OPENBLAS_CORETYPE"] = "Haswell"
        env["NPY_DISABLE_CPU_FEATURES"] = NORMALIZED_DISABLE
    elif runtime_class == "NATIVE":
        env.pop("OPENBLAS_CORETYPE", None)
        env.pop("NPY_DISABLE_CPU_FEATURES", None)
    else:
        raise ValueError(runtime_class)
    return env


def run(output: Path) -> int:
    cfg = _config()
    order = list(cfg["order"])
    rows: list[dict[str, Any]] = []
    tmp = output.parent / ".perf-a"
    tmp.mkdir(parents=True, exist_ok=True)
    for index, runtime_class in enumerate(order, start=1):
        child_out = tmp / f"{index:02d}-{runtime_class.lower()}.json"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "src.engines.v12_perf_a",
                "--child-runtime",
                runtime_class,
                "--output",
                str(child_out),
            ],
            cwd=ROOT,
            env=_env(runtime_class),
            check=True,
        )
        row = json.loads(child_out.read_text(encoding="utf-8"))
        row["sequence"] = index
        rows.append(row)

    fingerprints = {str(row.get("output_fingerprint")) for row in rows}
    paths = {int(row.get("actual_paths") or 0) for row in rows}
    seeds = {int(row.get("seed") or 0) for row in rows}
    snapshots = {str(row.get("input_snapshot_id")) for row in rows}
    normalized = [float(r["elapsed_seconds"]) for r in rows if r["runtime_class"] == "NORMALIZED"]
    native = [float(r["elapsed_seconds"]) for r in rows if r["runtime_class"] == "NATIVE"]
    normalized_median = statistics.median(normalized)
    native_median = statistics.median(native)
    ratio = native_median / normalized_median if normalized_median > 0 else None

    failures = []
    if order != ["NORMALIZED", "NATIVE", "NORMALIZED", "NATIVE"]:
        failures.append("ORDER_NOT_ABAB")
    if len(fingerprints) != 1:
        failures.append("SEMANTIC_OUTPUT_DRIFT")
    if paths != {int(cfg["actual_paths"])}:
        failures.append("PATH_COUNT_DRIFT")
    if seeds != {int(cfg["seed"])}:
        failures.append("SEED_DRIFT")
    if snapshots != {str(cfg["input_snapshot_id"])}:
        failures.append("SNAPSHOT_DRIFT")
    if any(r.get("status") != "PASS" or r.get("canonical_pass") is not True for r in rows):
        failures.append("CANONICAL_MC_NOT_PASS")

    decision = (
        "PERF_B_JUSTIFIED"
        if ratio is not None and ratio <= float(cfg["native_material_speedup_ratio_lte"])
        else "KEEP_NORMALIZED_RUNTIME"
    )
    result = {
        "schema_version": 1,
        "authority": cfg["authority"],
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "same_host_execution": True,
        "order": order,
        "samples": rows,
        "normalized_median_seconds": normalized_median,
        "native_median_seconds": native_median,
        "native_to_normalized_ratio": ratio,
        "material_speedup_threshold_ratio": cfg["native_material_speedup_ratio_lte"],
        "next_action": decision if not failures else "BLOCKED",
        "semantic_output_fingerprint": next(iter(fingerprints)) if len(fingerprints) == 1 else None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if not failures else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child-runtime", choices=("NORMALIZED", "NATIVE"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.child_runtime:
        return _child(args.child_runtime, args.output)
    return run(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
