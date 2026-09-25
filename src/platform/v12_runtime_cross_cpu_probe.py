from __future__ import annotations

"""Cross-host bit-identity probe for the normalized V12 numeric runtime.

This probe intentionally executes a governed exact P1.7 cross-route kernel,
not a toy NumPy calculation. It records physical host CPU only as evidence and
hashes the canonical public decision surface for cross-host comparison.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from src.engines.v12_cache_runtime_identity import (
    physical_cpu_model,
    runtime_cache_identity,
    validate_canonical_runtime_class,
)
from src.engines import v12_lineup_batch as batch


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "test_lineup_distributional_optimizer.py"
PUBLIC_KEYS = (
    "status",
    "gw",
    "route_utility",
    "expected_fpl_points",
    "distributional_downside",
    "supportable_upside",
    "expected_autosub_value",
    "cameo_blocking_cost",
    "formation",
    "starting_xi",
    "bench_gk",
    "bench_order",
    "captain",
    "vice_captain",
    "captain_safe_pool_count",
    "confidence",
    "covariance_status",
)


def _fixture_module():
    spec = importlib.util.spec_from_file_location(
        "_v12_runtime_probe_fixture",
        FIXTURE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load P1.7 governed fixture module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probe_squads(module, projections, candidates):
    base = projections["players"][:15]
    base_ids = tuple(sorted(int(row["element"]) for row in base))
    base_by_id = {int(row["element"]): row for row in base}
    candidates_by_position = {
        position: [
            row
            for row in candidates
            if row["position"] == position
        ]
        for position in ("GK", "DEF", "MID", "FWD")
    }
    squads = [base_ids]
    for outgoing in (
        base_ids[0],
        base_ids[2],
        base_ids[7],
        base_ids[12],
    ):
        position = base_by_id[outgoing]["position"]
        for incoming in candidates_by_position[position][:2]:
            squads.append(
                tuple(
                    sorted(
                        (set(base_ids) - {outgoing})
                        | {int(incoming["element"])}
                    )
                )
            )
    if len(squads) != 9 or len(set(squads)) != 9:
        raise RuntimeError("runtime probe squad fixture drift")
    return squads


def build_probe() -> dict[str, Any]:
    runtime_evidence = validate_canonical_runtime_class()
    module = _fixture_module()
    projections, candidates = module._cross_route_projection_fixture(5)
    squads = _probe_squads(module, projections, candidates)
    outputs, proof = batch.optimize_lineup_horizons_exact_batch(
        projections,
        squads,
        planning_gw=int(module.GW),
        generated_at=str(module.GENERATED),
        batch_size=8,
    )
    canonical = [
        {
            key: gw_row.get(key)
            for key in PUBLIC_KEYS
        }
        for route in outputs
        for gw_row in route.get("per_gw") or []
    ]
    payload = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return {
        "schema": "V12_RUNTIME_CROSS_CPU_PROBE_V1",
        "physical_cpu_model": physical_cpu_model(),
        "runtime_cache_identity": runtime_cache_identity(),
        "runtime_normalization": runtime_evidence,
        "output_sha256": hashlib.sha256(payload).hexdigest(),
        "output_rows": len(canonical),
        "squad_count": len(outputs),
        "horizon_count": 5,
        "execution_kernel": proof.get("execution_kernel"),
        "legal_xi_per_squad": proof.get("legal_xi_per_squad"),
        "route_pruning": proof.get("route_pruning"),
        "approximation": proof.get("approximation"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_probe()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
