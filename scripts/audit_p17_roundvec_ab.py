from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path.cwd()))

from src.engines import v12_integrated_report_runner as ir
from src.engines.v12_package_search import search_packages
from src.engines.v12_package_utility import _cumulative_lineup_horizons, _materialize_route_lineups, _route_squad
from src.engines.v12_lineup_optimizer import prime_player_surface_cache, reset_p17_execution_observability
from src.engines.v12_tactical_role import attach_tactical_role_scores
from src.models.official_role_evidence import attach_official_role_evidence
from src.models.team_strength import build_team_strength
from src.models.v12_analytics_foundation import load_v6_analytics_foundation, require_match_foundation
from src.models.historical_projection import build as build_player_projections

def dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False), encoding="utf-8")

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def thread_info() -> list[dict[str, Any]]:
    try:
        from threadpoolctl import threadpool_info
        return threadpool_info()
    except Exception as exc:
        return [{"status": "NOT_AVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}]

def build_snapshot(runtime_root: Path, out: Path, slot: str) -> None:
    official = ir._official_payload(runtime_root)
    bootstrap, fixtures = official["bootstrap"], official["fixtures"]
    planning_gw = ir._planning_gw(bootstrap)
    state = ir._read_json(ir.STATE_PATH, {}) or {}
    personal = ir._personal_evidence_resolution(runtime_root, state, planning_gw=planning_gw)
    owned = ir._owned15(personal, bootstrap)
    strength = build_team_strength(bootstrap, fixtures)
    foundation = require_match_foundation(load_v6_analytics_foundation(
        runtime_root, bootstrap=bootstrap, planning_gw=planning_gw, strength=strength or {}
    ))
    started = time.perf_counter()
    projections = build_player_projections(
        bootstrap, strength or {}, planning_gw, foundation.get("historical_prior") or {},
        player_features_payload=foundation.get("player_features_payload") or {},
        player_match_rows=foundation.get("player_match_rows") or [],
        opponent_history_rows=foundation.get("opponent_history_rows") or [],
        opponent_history_scope=foundation.get("opponent_history_scope"),
    )
    stage2_seconds = time.perf_counter() - started
    attach_official_role_evidence(projections, bootstrap)
    attach_tactical_role_scores(projections, planning_gw, team_strength=strength or {})
    finance = ir._private_finance_context(personal)
    search = search_packages(
        current_squad=owned,
        candidate_universe=ir._package_candidate_rows(projections),
        bank=finance.get("bank"), max_transfers=1, universe_complete=True,
        expected_eligible_universe_count=None, lossy_pruning=False, execution_mode="SCALAR",
    )
    p, r = out / "projections.json", out / "routes.json"
    dump(p, projections)
    dump(r, {"planning_gw": planning_gw, "report_slot": slot, "routes": search.get("routes") or []})
    dump(out / "snapshot_metadata.json", {
        "planning_gw": planning_gw, "report_slot": slot,
        "stage2_build_seconds_unprofiled": round(stage2_seconds, 6),
        "projection_sha256": sha(p), "routes_sha256": sha(r),
        "projection_player_count": len(projections.get("players") or []),
        "route_count": len(search.get("routes") or []),
        "thread_env": {k: os.environ.get(k) for k in ["OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","BLIS_NUM_THREADS"]},
        "threadpool_info": thread_info(),
    })

def benchmark(out: Path, label: str, scalar_n: int) -> None:
    projections = json.loads((out / "projections.json").read_text(encoding="utf-8"))
    route_payload = json.loads((out / "routes.json").read_text(encoding="utf-8"))
    routes = route_payload["routes"]
    planning_gw = int(route_payload["planning_gw"])
    slot = str(route_payload["report_slot"])
    started = time.perf_counter()
    _, batch_proof = _materialize_route_lineups(routes, projections, planning_gw=planning_gw, generated_at=slot)
    batch_seconds = time.perf_counter() - started

    sample = routes[:scalar_n]
    squads = [_route_squad(row) for row in sample]
    material = sorted({int(e) for squad in squads for e in squad})
    reset_p17_execution_observability()
    prime_started = time.perf_counter()
    prime_player_surface_cache(projections, planning_gws=range(planning_gw, planning_gw + 5), material_elements=material)
    prime_seconds = time.perf_counter() - prime_started
    per_squad = []
    scalar_started = time.perf_counter()
    for squad in squads:
        t = time.perf_counter()
        _cumulative_lineup_horizons(projections, squad, planning_gw=planning_gw, generated_at=slot)
        per_squad.append(time.perf_counter() - t)
    scalar_seconds = time.perf_counter() - scalar_started
    rows = sorted(per_squad)
    def pct(f: float) -> float:
        return rows[min(len(rows)-1, max(0, round((len(rows)-1)*f)))]
    dump(out / f"benchmark_{label}.json", {
        "label": label,
        "thread_env": {k: os.environ.get(k) for k in ["OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","BLIS_NUM_THREADS"]},
        "threadpool_info": thread_info(),
        "batch_wall_seconds_external": round(batch_seconds, 6),
        "batch_proof": batch_proof,
        "scalar_sample_count": len(squads),
        "scalar_route_ids": [str(x.get("route_id")) for x in sample],
        "scalar_prime_seconds": round(prime_seconds, 6),
        "scalar_total_seconds_excluding_prime": round(scalar_seconds, 6),
        "scalar_per_squad": {"min":round(rows[0],6),"p50":round(pct(.5),6),"p95":round(pct(.95),6),"max":round(rows[-1],6),"mean":round(sum(rows)/len(rows),6)} if rows else {},
    })

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-root", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--slot", default="2026-09-23T19:40:00+07:00")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--label", default="default")
    ap.add_argument("--scalar-n", type=int, default=65)
    args = ap.parse_args()
    if args.build:
        if args.runtime_root is None:
            raise SystemExit("--runtime-root required for --build")
        build_snapshot(args.runtime_root, args.out, args.slot)
    if args.benchmark:
        benchmark(args.out, args.label, args.scalar_n)

if __name__ == "__main__":
    main()
