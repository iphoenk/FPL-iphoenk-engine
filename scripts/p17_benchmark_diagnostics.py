from __future__ import annotations

import argparse
import cProfile
import importlib.util
import json
from pathlib import Path
import pstats
import statistics
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TEST_PATH = ROOT / "tests" / "test_lineup_distributional_optimizer.py"


def _load_fixture_module():
    spec = importlib.util.spec_from_file_location(
        "p17_benchmark_fixture",
        TEST_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load fixture module: {TEST_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_squads(route_count: int):
    fixture = _load_fixture_module()
    projections, candidates = fixture._cross_route_projection_fixture(140)
    owned = projections["players"][:15]
    base_ids = tuple(sorted(int(row["element"]) for row in owned))
    owned_by_id = {int(row["element"]): row for row in owned}
    candidates_by_position = {
        position: [
            int(row["element"])
            for row in candidates
            if row["position"] == position
        ]
        for position in ("GK", "DEF", "MID", "FWD")
    }
    squads = [base_ids]
    for outgoing in base_ids:
        position = owned_by_id[outgoing]["position"]
        for incoming in candidates_by_position[position]:
            squads.append(
                tuple(
                    sorted(
                        (set(base_ids) - {outgoing})
                        | {incoming}
                    )
                )
            )
            if len(squads) == route_count:
                break
        if len(squads) == route_count:
            break
    if len(squads) != route_count:
        raise RuntimeError(
            f"fixture produced {len(squads)} squads, expected {route_count}"
        )
    if len(set(squads)) != route_count:
        raise RuntimeError("fixture lost unique squad identity")
    return fixture, projections, squads


def _run_batch(route_count: int) -> dict[str, Any]:
    fixture, projections, squads = _build_squads(route_count)
    from src.engines import v12_lineup_batch as batch

    started = time.perf_counter()
    outputs, proof = batch.optimize_lineup_horizons_exact_batch(
        projections,
        squads,
        planning_gw=fixture.GW,
        generated_at=fixture.GENERATED,
        batch_size=512,
    )
    elapsed = time.perf_counter() - started
    if len(outputs) != route_count:
        raise RuntimeError("batch output count drift")
    if not all(
        len(row["per_gw"]) == 5
        and all(gw_row["status"] == "READY" for gw_row in row["per_gw"])
        for row in outputs
    ):
        raise RuntimeError("batch output readiness drift")
    return {
        "mode": "batch",
        "route_count": route_count,
        "gw_count": 5,
        "elapsed_seconds": elapsed,
        "proof": proof,
    }


def _run_scalar(route_count: int) -> dict[str, Any]:
    fixture, projections, squads = _build_squads(route_count)
    from src.engines import v12_package_utility as package

    started = time.perf_counter()
    rows = []
    for squad in squads:
        per_gw = []
        for offset in range(5):
            per_gw.append(
                package._lineup_decision(
                    projections,
                    squad,
                    gw=fixture.GW + offset,
                    generated_at=fixture.GENERATED,
                )
            )
        rows.append(per_gw)
    elapsed = time.perf_counter() - started
    if len(rows) != route_count:
        raise RuntimeError("scalar output count drift")
    if not all(
        len(row) == 5
        and all(gw_row["status"] == "READY" for gw_row in row)
        for row in rows
    ):
        raise RuntimeError("scalar output readiness drift")
    return {
        "mode": "scalar",
        "route_count": route_count,
        "gw_count": 5,
        "elapsed_seconds": elapsed,
    }


def _profile_batch(route_count: int, pstats_path: Path) -> dict[str, Any]:
    profiler = cProfile.Profile()
    result: dict[str, Any] = {}
    profiler.enable()
    try:
        result = _run_batch(route_count)
    finally:
        profiler.disable()
        profiler.dump_stats(str(pstats_path))
    stats = pstats.Stats(str(pstats_path))
    rows = []
    for (filename, line, function), raw in stats.stats.items():
        cc, nc, tt, ct, _callers = raw
        rows.append(
            {
                "file": filename,
                "line": int(line),
                "function": function,
                "primitive_calls": int(cc),
                "total_calls": int(nc),
                "internal_seconds": float(tt),
                "cumulative_seconds": float(ct),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["cumulative_seconds"],
            -row["internal_seconds"],
            row["file"],
            row["line"],
            row["function"],
        )
    )
    result["profile_top"] = rows[:80]
    return result


def _child(mode: str, route_count: int, output: Path, pstats_path: Path | None):
    if mode == "batch":
        payload = _run_batch(route_count)
    elif mode == "scalar":
        payload = _run_scalar(route_count)
    elif mode == "profile-batch":
        if pstats_path is None:
            raise RuntimeError("--pstats is required for profile-batch")
        payload = _profile_batch(route_count, pstats_path)
    else:
        raise RuntimeError(f"unsupported child mode: {mode}")
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _invoke_child(
    *,
    mode: str,
    route_count: int,
    output: Path,
    pstats_path: Path | None = None,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child-mode",
        mode,
        "--route-count",
        str(route_count),
        "--output",
        str(output),
    ]
    if pstats_path is not None:
        cmd.extend(["--pstats", str(pstats_path)])
    subprocess.run(cmd, cwd=ROOT, check=True)
    return json.loads(output.read_text(encoding="utf-8"))


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    return {
        "count": len(ordered),
        "min": min(ordered),
        "median": statistics.median(ordered),
        "max": max(ordered),
        "mean": statistics.mean(ordered),
        "range": max(ordered) - min(ordered),
    }


def _render_md(payload: dict[str, Any]) -> str:
    repeated = payload["batch_2043_repeated"]
    ratio = payload["same_runner_scalar_vs_batch"]
    lines = [
        "# P1.7 2043×5 benchmark diagnostics",
        "",
        "This is diagnostic evidence only. It does not change or relax the existing",
        "10.0 second acceptance gate.",
        "",
        "## Five independent batch processes",
        "",
        "| Run | Seconds |",
        "|---:|---:|",
    ]
    for index, seconds in enumerate(repeated["samples_seconds"], start=1):
        lines.append(f"| {index} | {seconds:.6f} |")
    s = repeated["summary"]
    lines.extend(
        [
            "",
            f"- min: {s['min']:.6f} s",
            f"- median: {s['median']:.6f} s",
            f"- max: {s['max']:.6f} s",
            f"- mean: {s['mean']:.6f} s",
            f"- range: {s['range']:.6f} s",
            "",
            "## Same-runner scalar vs batch",
            "",
            f"- route_count: {ratio['route_count']}",
            f"- scalar: {ratio['scalar_seconds']:.6f} s",
            f"- batch: {ratio['batch_seconds']:.6f} s",
            f"- speedup: {ratio['speedup_x']:.3f}×",
            "",
            "## Profile top functions",
            "",
            "| Function | File | Internal s | Cumulative s | Calls |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in payload["profile"]["top_functions"][:30]:
        lines.append(
            f"| {row['function']} | {Path(row['file']).name}:{row['line']} | "
            f"{row['internal_seconds']:.6f} | {row['cumulative_seconds']:.6f} | "
            f"{row['total_calls']} |"
        )
    lines.extend(
        [
            "",
            "_cProfile cumulative time is inclusive and must not be summed across nested functions._",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child-mode", choices=("batch", "scalar", "profile-batch"))
    parser.add_argument("--route-count", type=int, default=2043)
    parser.add_argument("--output")
    parser.add_argument("--pstats")
    parser.add_argument("--artifact-dir", default="artifacts/p17-benchmark")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--scalar-route-count", type=int, default=65)
    args = parser.parse_args()

    if args.child_mode:
        if not args.output:
            raise SystemExit("--output is required in child mode")
        _child(
            args.child_mode,
            args.route_count,
            Path(args.output),
            Path(args.pstats) if args.pstats else None,
        )
        return 0

    artifact_dir = ROOT / args.artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)

    samples = []
    for index in range(args.repeats):
        row = _invoke_child(
            mode="batch",
            route_count=2043,
            output=artifact_dir / f"batch_2043_run_{index + 1}.json",
        )
        samples.append(float(row["elapsed_seconds"]))

    scalar = _invoke_child(
        mode="scalar",
        route_count=args.scalar_route_count,
        output=artifact_dir / "scalar_subset.json",
    )
    batch_subset = _invoke_child(
        mode="batch",
        route_count=args.scalar_route_count,
        output=artifact_dir / "batch_subset.json",
    )
    profile = _invoke_child(
        mode="profile-batch",
        route_count=2043,
        output=artifact_dir / "profile_batch_2043.json",
        pstats_path=artifact_dir / "batch_2043.pstats",
    )

    scalar_seconds = float(scalar["elapsed_seconds"])
    batch_seconds = float(batch_subset["elapsed_seconds"])
    payload = {
        "schema_version": 1,
        "gate_10_seconds_unchanged": True,
        "batch_2043_repeated": {
            "process_isolation": True,
            "samples_seconds": samples,
            "summary": _summary(samples),
        },
        "same_runner_scalar_vs_batch": {
            "route_count": args.scalar_route_count,
            "gw_count": 5,
            "scalar_seconds": scalar_seconds,
            "batch_seconds": batch_seconds,
            "speedup_x": (
                scalar_seconds / batch_seconds if batch_seconds > 0 else None
            ),
        },
        "profile": {
            "route_count": 2043,
            "gw_count": 5,
            "profiled_elapsed_seconds": float(profile["elapsed_seconds"]),
            "top_functions": profile["profile_top"],
        },
    }
    (artifact_dir / "benchmark_diagnostics.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "benchmark_diagnostics.md").write_text(
        _render_md(payload),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
