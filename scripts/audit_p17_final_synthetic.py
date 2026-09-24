from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path


def load_fixture_module():
    path = Path.cwd() / "tests" / "test_lineup_distributional_optimizer.py"
    spec = importlib.util.spec_from_file_location("p17_acceptance_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load fixture module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("normal", "tie-rich"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from src.engines import v12_lineup_batch as batch

    fixture = load_fixture_module()
    if args.mode == "normal":
        projections, candidates = fixture._cross_route_projection_fixture(140)
    else:
        projections, candidates = fixture._cross_route_tie_rich_projection_fixture(140)
    squads = fixture._cross_route_2043_squads(projections, candidates)

    started = time.perf_counter()
    outputs, proof = batch.optimize_lineup_horizons_exact_batch(
        projections,
        squads,
        planning_gw=fixture.GW,
        generated_at=fixture.GENERATED,
        batch_size=512,
    )
    elapsed = time.perf_counter() - started

    if len(outputs) != 2043:
        raise RuntimeError(f"unexpected output count: {len(outputs)}")
    if not all(
        gw_row.get("status") == "READY"
        for row in outputs
        for gw_row in row.get("per_gw", [])
    ):
        raise RuntimeError("non-READY row in synthetic benchmark")
    if proof.get("execution_kernel") != "ROUTE_FAMILY_CORE14_AFFINE_EXACT_P1_7":
        raise RuntimeError("unexpected execution kernel")
    if proof.get("route_pruning") is not False:
        raise RuntimeError("route pruning detected")
    if int(proof.get("legal_xi_per_squad") or 0) != 550:
        raise RuntimeError("legal XI contract drift")
    if args.mode == "tie-rich":
        if float(proof.get("bench_primary_tie_rate") or 0.0) < 0.99:
            raise RuntimeError("tie-rich fixture lost primary ties")
        if int(proof.get("bench_scalar_fallback_count") or 0) != 0:
            raise RuntimeError("tie-rich fallback unexpectedly non-zero")

    payload = {
        "mode": args.mode,
        "wall_seconds": round(elapsed, 9),
        "route_count": 2043,
        "gw_count": 5,
        "legal_xi_per_squad": 550,
        "execution_kernel": proof.get("execution_kernel"),
        "route_pruning": proof.get("route_pruning"),
        "bench_primary_tie_rate": proof.get("bench_primary_tie_rate"),
        "bench_scalar_fallback_count": proof.get("bench_scalar_fallback_count"),
        "bench_scalar_fallback_rate": proof.get("bench_scalar_fallback_rate"),
        "pid": os.getpid(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
