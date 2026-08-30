from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from src.services.competitive_load_service import OUT as COMPETITIVE_LOAD_OUT
from src.services.competitive_load_service import PRESS_EVIDENCE, build_competitive_load
from src.services.contracts import file_digest
from src.sources import core_insights, vaastav
from src.utils import CONFIG, DATA, atomic_json, iso_now, parse_dt, read_json, utcnow

RUNTIME = DATA / "runtime"
SNAPSHOT = RUNTIME / "snapshot.v1.json"
OUTFILE = RUNTIME / "enrichment.v1.json"
STATS = DATA / "stats"


def _run_parallel(tasks: dict) -> dict:
    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="fpl-enrichment") as pool:
        futures = {name: pool.submit(fn) for name, fn in tasks.items()}
        return {name: future.result() for name, future in futures.items()}


def _cache_age_minutes(payload: dict) -> float | None:
    stamp = parse_dt(payload.get("fetched_at")) if payload else None
    if not stamp:
        return None
    return max(0.0, (utcnow() - stamp).total_seconds() / 60.0)


def _fresh_cached(path, ttl_minutes: float, validator) -> tuple[dict | None, float | None]:
    payload = read_json(path, {})
    age = _cache_age_minutes(payload)
    if payload and age is not None and age <= ttl_minutes and validator(payload):
        return payload, round(age, 2)
    return None, age


def _reuse_policy() -> dict:
    return (read_json(CONFIG / "sources.json", {}) or {}).get("performance_reuse") or {}


def _core_insights_task(gw: int, ttl: float) -> dict:
    cached, age = _fresh_cached(
        STATS / f"core_insights_gw{gw}.json",
        ttl,
        lambda payload: bool(payload.get("schema_valid")) and bool(payload.get("rows")),
    )
    if cached:
        return {**cached, "runtime_reused": True, "cache_age_minutes": age}
    fresh = core_insights.sync_gw(gw)
    return {**fresh, "runtime_reused": False, "cache_age_minutes": 0.0}


def _vaastav_task(gw: int, ttl: float) -> dict:
    cached, age = _fresh_cached(
        STATS / f"vaastav_gw{gw}.json",
        ttl,
        lambda payload: bool(payload.get("rows")) and payload.get("status") != "FAILED",
    )
    if cached:
        return {**cached, "runtime_reused": True, "cache_age_minutes": age}
    fresh = vaastav.sync_gw(gw)
    return {**fresh, "runtime_reused": False, "cache_age_minutes": 0.0}


def _previous_season_task(ttl: float) -> dict:
    cached, age = _fresh_cached(
        STATS / "vaastav_previous_season.json",
        ttl,
        lambda payload: bool(payload.get("rows")) and payload.get("status") == "LIVE",
    )
    if cached:
        return {**cached, "runtime_reused": True, "cache_age_minutes": age}
    fresh = vaastav.sync_previous_season()
    return {**fresh, "runtime_reused": False, "cache_age_minutes": 0.0}


def _historical_season_task(season: str, ttl: float) -> dict:
    safe = season.replace("-", "_")
    cached, age = _fresh_cached(
        STATS / f"vaastav_historical_{safe}.json",
        ttl,
        lambda payload: (
            bool(payload.get("rows"))
            and payload.get("status") == "LIVE"
            and payload.get("season") == season
            and payload.get("immutable_completed_season") is True
        ),
    )
    if cached:
        return {**cached, "runtime_reused": True, "cache_age_minutes": age}
    fresh = vaastav.sync_historical_season(season)
    return {**fresh, "runtime_reused": False, "cache_age_minutes": 0.0}


def _deep_task(gw: int, ttl: float) -> dict:
    names = ("shots", "playermatchstats")
    cached_rows = {}
    ages = []
    for name in names:
        payload, age = _fresh_cached(
            STATS / f"{name}_gw{gw}.json",
            ttl,
            lambda row: isinstance(row.get("rows"), list),
        )
        if not payload:
            fresh = core_insights.sync_optional_deep_files(gw)
            fresh["runtime_reused"] = False
            fresh["cache_age_minutes"] = 0.0
            return fresh
        cached_rows[name] = {"ok": True, "rows": len(payload.get("rows") or []), "url": payload.get("source_url")}
        if age is not None:
            ages.append(age)
    return {
        **cached_rows,
        "runtime_reused": True,
        "cache_age_minutes": round(max(ages) if ages else 0.0, 2),
    }


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
        reuse = _reuse_policy()
        current_ttl = float(reuse.get("current_gw_stats_ttl_minutes") or 60)
        deep_ttl = float(reuse.get("deep_stats_ttl_minutes") or 180)
        previous_ttl = float(reuse.get("previous_season_ttl_minutes") or 10080)
        history_seasons = vaastav.historical_seasons()
        tasks = {
            "core_insights": lambda: _core_insights_task(int(stats_gw), current_ttl),
            "vaastav": lambda: _vaastav_task(int(stats_gw), current_ttl),
            "last_season": lambda: _previous_season_task(previous_ttl),
        }
        for season in history_seasons:
            tasks[f"historical:{season}"] = lambda season=season: _historical_season_task(season, previous_ttl)
        if deep_stats:
            tasks["deep"] = lambda: _deep_task(int(stats_gw), deep_ttl)
        results = _run_parallel(tasks)
        advanced = {
            "core_insights": {
                "ok": bool(results["core_insights"].get("schema_valid")),
                "rows": results["core_insights"].get("row_count"),
                "reused": bool(results["core_insights"].get("runtime_reused")),
                "cache_age_minutes": results["core_insights"].get("cache_age_minutes"),
            },
            "vaastav": {
                "ok": bool(results["vaastav"].get("rows")),
                "rows": results["vaastav"].get("row_count"),
                "reused": bool(results["vaastav"].get("runtime_reused")),
                "cache_age_minutes": results["vaastav"].get("cache_age_minutes"),
            },
            "last_season": {
                "ok": bool(results["last_season"].get("rows")),
                "rows": results["last_season"].get("row_count"),
                "reused": bool(results["last_season"].get("runtime_reused")),
                "cache_age_minutes": results["last_season"].get("cache_age_minutes"),
            },
            "historical_seasons": {
                season: {
                    "ok": bool(results[f"historical:{season}"].get("rows")),
                    "rows": results[f"historical:{season}"].get("row_count"),
                    "reused": bool(results[f"historical:{season}"].get("runtime_reused")),
                    "cache_age_minutes": results[f"historical:{season}"].get("cache_age_minutes"),
                }
                for season in history_seasons
            },
            "reuse_policy": {
                "current_gw_stats_ttl_minutes": current_ttl,
                "deep_stats_ttl_minutes": deep_ttl,
                "previous_season_ttl_minutes": previous_ttl,
                "historical_completed_seasons_immutable": True,
                "official_fpl_excluded": True,
                "volatile_team_news_excluded": True,
            },
        }
        if deep_stats:
            advanced["deep"] = results["deep"]

    teams = {team["id"]: team["name"] for team in bootstrap.get("teams", [])}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    universe = [_official_player_row(player, teams, positions) for player in bootstrap.get("elements", [])]

    competitive_load = build_competitive_load(raw, read_json(PRESS_EVIDENCE, {}))
    atomic_json(COMPETITIVE_LOAD_OUT, competitive_load)

    out = {
        "schema": "enrichment.v1",
        "schema_version": 495,
        "generated_at": iso_now(),
        "lineage": {"snapshot_schema": "snapshot.v1", "snapshot_sha256": file_digest(SNAPSHOT)},
        "stats_gw": stats_gw,
        "advanced_stats_sync": advanced,
        "competitive_load": {
            "artifact": str(COMPETITIVE_LOAD_OUT.relative_to(DATA.parent)),
            "schema": competitive_load.get("schema"),
            "players": competitive_load.get("coverage", {}).get("players"),
            "official_fpl_current_gw_load": competitive_load.get("coverage", {}).get("official_fpl_current_gw_load"),
            "observed_player_fixture_rows": competitive_load.get("coverage", {}).get("observed_player_fixture_rows"),
            "other_competitions": competitive_load.get("coverage", {}).get("other_competitions"),
            "press_conference_collection": competitive_load.get("coverage", {}).get("press_conference_collection"),
            "complete_for_visible_report": competitive_load.get("coverage", {}).get("complete_for_visible_report"),
        },
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
    print(json.dumps({
        "service": "enrichment",
        "schema": "enrichment.v1",
        "duration_ms": out["duration_ms"],
        "official_players": len(universe),
        "stats_reused": {key: value.get("reused") for key, value in advanced.items() if isinstance(value, dict) and "reused" in value},
        "historical_seasons": sorted((advanced.get("historical_seasons") or {}).keys()),
        "competitive_load_rows": competitive_load.get("coverage", {}).get("observed_player_fixture_rows"),
        "competitive_load_complete_for_visible_report": competitive_load.get("coverage", {}).get("complete_for_visible_report"),
    }))
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--deep-stats", action="store_true")
    args = parser.parse_args()
    return run(args.stats, args.deep_stats)


if __name__ == "__main__":
    cli()
