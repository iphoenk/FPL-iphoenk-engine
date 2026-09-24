from __future__ import annotations
import argparse, hashlib, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from src.engines.v12_package_utility import _materialize_route_lineups

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--label", required=True)
    args=ap.parse_args()
    projections=json.loads((args.snapshot/"projections.json").read_text(encoding="utf-8"))
    route_payload=json.loads((args.snapshot/"routes.json").read_text(encoding="utf-8"))
    routes=route_payload["routes"]
    planning_gw=int(route_payload["planning_gw"])
    slot=str(route_payload["report_slot"])
    started=time.perf_counter()
    lineups, proof=_materialize_route_lineups(
        routes, projections, planning_gw=planning_gw, generated_at=slot
    )
    elapsed=time.perf_counter()-started
    canonical=json.dumps(
        lineups, sort_keys=True, separators=(",",":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    result={
        "label":args.label,
        "route_count":len(lineups),
        "canonical_bytes":len(canonical),
        "sha256":hashlib.sha256(canonical).hexdigest(),
        "wall_seconds":round(elapsed,6),
        "execution_mode":proof.get("execution_mode"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
