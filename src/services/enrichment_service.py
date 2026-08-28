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


def _run_parallel(tasks: dict) -> dict:
    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="fpl-enrichment") as pool:
        futures = {name: pool.submit(fn) for name, fn in tasks.items()}
        return {name: future.result() for name, future in futures.items()}


def _official_player_row(player: dict, teams: dict, positions: dict) -> dict:
    return {
        "element": player["id"],
        "name": player["web_name"],
        "team": teams[player["team"]],
        "team_id": player["team"],
        "position": positions[player["element_type"]],
        "element_type": player["element_type"],
        "now_cost": player["now_cost"],
        "ownership": player.get("selected_by_percent"),
        "status": player.get("status"),
        "chance_of_playing_next_round": player.get("chance_of_playing_next_round"),
        "news": player.get("news"),
        "points": player.get("total_points"),
        "points_per_game": player.get("points_per_game"),
        "form": player.get("form"),
        "starts": player.get("starts"),
        "minutes": player.get("minutes"),
        "goals_scored": player.get("goals_scored"),
        "assists": player.get("assists"),
        "expected_goals": player.get("expected_goals"),
        "expected_assists": player.get("expected_assists"),
        "expected_goal_involvements": player.get("expected_goal_involvements"),
        "goals_conceded": player.get("goals_conceded"),
        "expected_goals_conceded": player.get("expected_goals_conceded"),
        "clean_sheets": player.get("clean_sheets"),
        "saves": player.get("saves"),
        "bonus": player.get("bonus"),
        "bps": player.get("bps"),
        "influence": player.get("influence"),
        "creativity": player.get("creativity"),
        "threat": player.get("threat"),
        "ict_index": player.get("ict_index"),
        "ep_this": player.get("ep_this"),
        "ep_next": player.get("ep_next"),
        "transfers_in_event": player.get("transfers_in_event"),
        "transfers_out_event": player.get("transfers_out_event"),
        "cost_change_event": player.get("cost_change_event"),
        "cost_change_start": player.get("cost_change_start"),
        "official_fpl_source": "bootstrap-static.elements",
    }


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
        history_seasons = vaastav.historical_seasons()
        tasks = {
            "core_insights": lambda: core_insights.sync_gw(stats_gw),
            "vaastav": lambda: vaastav.sync_gw(stats_gw),
            "last_season": vaastav.sync_previous_season,
        }
        for season in history_seasons:
            tasks[f"historical:{season}"] = lambda season=season: vaastav.sync_historical_season(season)
        if deep_stats:
            tasks["deep"] = lambda: core_insights.sync_optional_deep_files(stats_gw)
        results = _run_parallel(tasks)
        advanced = {
            "core_insights": {"ok": bool(results["core_insights"].get("schema_valid")), "rows": results["core_insights"].get("row_count")},
            "vaastav": {"ok": bool(results["vaastav"].get("rows")), "rows": results["vaastav"].get("row_count")},
            "last_season": {"ok": bool(results["last_season"].get("rows")), "rows": results["last_season"].get("row_count")},
            "historical_seasons": {
                season: {
                    "ok": bool(results[f"historical:{season}"].get("rows")),
                    "rows": results[f"historical:{season}"].get("row_count"),
                    "cache_reused": bool(results[f"historical:{season}"].get("cache_reused")),
                }
                for season in history_seasons
            },
        }
        if deep_stats:
            advanced["deep"] = results["deep"]
    teams = {team["id"]: team["name"] for team in bootstrap.get("teams", [])}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    universe = [_official_player_row(player, teams, positions) for player in bootstrap.get("elements", [])]
    out = {
        "schema": "enrichment.v1",
        "schema_version": 495,
        "generated_at": iso_now(),
        "lineage": {"snapshot_schema": "snapshot.v1", "snapshot_sha256": file_digest(SNAPSHOT)},
        "stats_gw": stats_gw,
        "advanced_stats_sync": advanced,
        "official_player_evidence": {
            "source": "raw_snapshot.official.bootstrap.elements",
            "players": len(universe),
            "ownership": sum(row.get("ownership") is not None for row in universe),
            "expected_goals": sum(row.get("expected_goals") is not None for row in universe),
            "expected_assists": sum(row.get("expected_assists") is not None for row in universe),
            "bps": sum(row.get("bps") is not None for row in universe),
            "starts": sum(row.get("starts") is not None for row in universe),
        },
        "universe": universe,
        "duration_ms": round((perf_counter() - started) * 1000, 2),
    }
    atomic_json(OUTFILE, out)
    print(json.dumps({"service": "enrichment", "schema": "enrichment.v1", "duration_ms": out["duration_ms"], "official_players": len(universe)}))
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--deep-stats", action="store_true")
    args = parser.parse_args()
    return run(args.stats, args.deep_stats)


if __name__ == "__main__":
    cli()
