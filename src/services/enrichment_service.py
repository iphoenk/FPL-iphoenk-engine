from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from src.services.contracts import file_digest
from src.sources import core_insights, vaastav
from src.utils import DATA, atomic_json, iso_now, read_json

RUNTIME = DATA / "runtime"
SNAPSHOT = RUNTIME / "snapshot.v1.json"
OUTFILE = RUNTIME / "enrichment.v1.json"


def run(sync_stats: bool = False, deep_stats: bool = False) -> dict:
    started = perf_counter()
    raw = read_json(SNAPSHOT, {})
    if raw.get("schema") != "snapshot.v1":
        raise RuntimeError("valid snapshot.v1 required")
    bootstrap = (raw.get("official") or {}).get("bootstrap") or {}
    phase = raw.get("phase") or {}
    stats_gw = phase.get("current_gw") or phase.get("last_finished_gw")
    advanced = {}
    if sync_stats and stats_gw:
        tasks = {"core_insights": lambda: core_insights.sync_gw(stats_gw), "vaastav": lambda: vaastav.sync_gw(stats_gw), "last_season": vaastav.sync_previous_season}
        if deep_stats:
            tasks["deep"] = lambda: core_insights.sync_optional_deep_files(stats_gw)
        with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="fpl-enrichment") as pool:
            results = {name: future.result() for name, future in ((name, pool.submit(fn)) for name, fn in tasks.items())}
        advanced = {"core_insights": {"ok": bool(results["core_insights"].get("schema_valid")), "rows": results["core_insights"].get("row_count")}, "vaastav": {"ok": bool(results["vaastav"].get("rows")), "rows": results["vaastav"].get("row_count")}, "last_season": {"ok": bool(results["last_season"].get("rows")), "rows": results["last_season"].get("row_count")}}
        if deep_stats:
            advanced["deep"] = results["deep"]
    teams = {team["id"]: team["name"] for team in bootstrap.get("teams", [])}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    universe = [{"element": p["id"], "name": p["web_name"], "team": teams[p["team"]], "team_id": p["team"], "position": positions[p["element_type"]], "element_type": p["element_type"], "now_cost": p["now_cost"], "ownership": p.get("selected_by_percent"), "status": p.get("status"), "points": p.get("total_points"), "minutes": p.get("minutes"), "transfers_in_event": p.get("transfers_in_event"), "transfers_out_event": p.get("transfers_out_event")} for p in bootstrap.get("elements", [])]
    out = {"schema": "enrichment.v1", "schema_version": 481, "generated_at": iso_now(), "lineage": {"snapshot_schema": "snapshot.v1", "snapshot_sha256": file_digest(SNAPSHOT)}, "stats_gw": stats_gw, "advanced_stats_sync": advanced, "universe": universe, "duration_ms": round((perf_counter() - started) * 1000, 2)}
    atomic_json(OUTFILE, out)
    print(json.dumps({"service": "enrichment", "schema": "enrichment.v1", "duration_ms": out["duration_ms"]}))
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--deep-stats", action="store_true")
    args = parser.parse_args()
    return run(args.stats, args.deep_stats)


if __name__ == "__main__":
    cli()
