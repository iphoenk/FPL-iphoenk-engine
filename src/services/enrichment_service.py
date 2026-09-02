from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from src.engines.v4_official_fact_integrity import build_public_fact, fact_defects, official_snapshot_metadata
from src.intelligence.understat_tactical import materialize as materialize_understat_tactical
from src.intelligence.weather_advisory import collect_weather_context
from src.services.competitive_load_service import OUT as COMPETITIVE_LOAD_OUT
from src.services.competitive_load_service import (
    EXTERNAL_COMPETITIVE_EVIDENCE,
    PRESS_EVIDENCE,
    build_competitive_load,
)
from src.services.contracts import file_digest
from src.sources import core_insights, understat, vaastav
from src.utils import CONFIG, DATA, atomic_json, iso_now, parse_dt, read_json, utcnow

RUNTIME = DATA / "runtime"
SNAPSHOT = RUNTIME / "snapshot.v1.json"
OUTFILE = RUNTIME / "enrichment.v1.json"
WEATHER_OUT = DATA / "weather_context_v4.json"
LIVE_WEATHER_EVIDENCE = DATA / "weather_live_evidence_v4.json"
UNDERSTAT_OUT = DATA / "understat_tactical_v4.json"
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


def _identity_variants(player: dict) -> list[str]:
    first = str(player.get("first_name") or "").strip()
    second = str(player.get("second_name") or "").strip()
    web = str(player.get("web_name") or "").strip()
    full = " ".join(part for part in (first, second) if part).strip()
    values = [full, web, second]
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _official_player_row(player: dict, teams: dict, positions: dict, snapshot_meta: dict) -> dict:
    fact = build_public_fact(player, teams, positions, snapshot_meta)
    variants = _identity_variants(player)
    return {
        **fact,
        "web_name": player.get("web_name"),
        "first_name": player.get("first_name"),
        "second_name": player.get("second_name"),
        "full_name": variants[0] if variants else player.get("web_name"),
        "name_variants": variants,
        "element_type": player["element_type"],
        "selected_by_percent": player.get("selected_by_percent"),
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


def _understat_summary(tactical: dict, raw_understat: dict) -> dict:
    health = tactical.get("health") or {}
    source = tactical.get("source") or {}
    return {
        "ok": health.get("status") in {"AVAILABLE", "PARTIAL"},
        "status": health.get("status"),
        "source_availability": source.get("availability"),
        "freshness": source.get("freshness"),
        "fetched_at": source.get("fetched_at"),
        "latest_match_covered": source.get("latest_match_covered"),
        "reused": bool(raw_understat.get("runtime_reused")),
        "cache_age_minutes": raw_understat.get("cache_age_minutes"),
        "team_mapping_coverage": health.get("team_mapping_coverage"),
        "player_mapping_count": health.get("player_mapping_count"),
        "player_mapping_coverage": health.get("player_mapping_coverage"),
        "player_crosswalk_coverage": health.get("player_crosswalk_coverage"),
        "source_present_mapping_coverage": health.get("source_present_mapping_coverage"),
        "source_absent_current_season_count": health.get("source_absent_current_season_count"),
        "identity_unresolved_count": health.get("identity_unresolved_count"),
        "unresolved_mapping_count": health.get("unresolved_mapping_count"),
        "tactical_matchup_usable_count": health.get("tactical_matchup_usable_count"),
        "tactical_matchup_coverage": health.get("tactical_matchup_coverage"),
        "fallback_state": health.get("fallback_state"),
        "degradation_reason": health.get("degradation_reason"),
        "artifact": str(UNDERSTAT_OUT.relative_to(DATA.parent)),
        "optional_enrichment": True,
        "direct_xpts_mutation": False,
        "direct_xmins_mutation": False,
    }


def run(sync_stats: bool = False, deep_stats: bool = False) -> dict:
    started = perf_counter()
    raw = read_json(SNAPSHOT, {})
    if raw.get("schema") != "snapshot.v1":
        raise RuntimeError("valid snapshot.v1 required")
    bootstrap = (raw.get("official") or {}).get("bootstrap") or {}
    phase = raw.get("phase") or {}
    stats_gw = phase.get("current_gw") or phase.get("last_finished_gw")
    previous_weather = read_json(WEATHER_OUT, {})
    live_weather_evidence = read_json(LIVE_WEATHER_EVIDENCE, {})
    advanced = {}
    if sync_stats and stats_gw:
        reuse = _reuse_policy()
        current_ttl = float(reuse.get("current_gw_stats_ttl_minutes") or 60)
        deep_ttl = float(reuse.get("deep_stats_ttl_minutes") or 180)
        previous_ttl = float(reuse.get("previous_season_ttl_minutes") or 10080)
        tasks = {
            "core_insights": lambda: _core_insights_task(int(stats_gw), current_ttl),
            "vaastav": lambda: _vaastav_task(int(stats_gw), current_ttl),
            "last_season": lambda: _previous_season_task(previous_ttl),
            "understat_raw": understat.sync,
            "weather_context": lambda: collect_weather_context(
                raw,
                previous=previous_weather,
                live_evidence=live_weather_evidence,
            ),
        }
        if deep_stats:
            tasks["deep"] = lambda: _deep_task(int(stats_gw), deep_ttl)
        results = _run_parallel(tasks)
        weather_context = results.pop("weather_context")
        raw_understat = results.pop("understat_raw")
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
            "reuse_policy": {
                "current_gw_stats_ttl_minutes": current_ttl,
                "deep_stats_ttl_minutes": deep_ttl,
                "previous_season_ttl_minutes": previous_ttl,
                "understat_policy_owned_by": "config/intelligence/understat_tactical.json",
                "official_fpl_excluded": True,
                "volatile_team_news_excluded": True,
                "weather_source_refresh_bounded_and_fail_soft": True,
            },
        }
        if deep_stats:
            advanced["deep"] = results["deep"]
    else:
        raw_understat = understat.load()
        weather_context = collect_weather_context(
            raw,
            previous=previous_weather,
            live_evidence=live_weather_evidence,
        )

    atomic_json(WEATHER_OUT, weather_context)
    teams = {team["id"]: team["name"] for team in bootstrap.get("teams", [])}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    official_snapshot = official_snapshot_metadata(
        bootstrap,
        ((raw.get("endpoint_health") or {}).get("bootstrap") or {}),
    )
    universe = [_official_player_row(player, teams, positions, official_snapshot) for player in bootstrap.get("elements", [])]
    official_fact_complete = sum(
        not fact_defects(row, expected_element=int(row.get("element_id") or 0))
        for row in universe
    )

    # Preserve Official FPL web_name for the canonical universe while using the
    # fuller Official identity only at the Understat cross-source join boundary.
    understat_identity_universe = [
        {**row, "name": row.get("full_name") or row.get("name")}
        for row in universe
    ]
    understat_tactical = materialize_understat_tactical(raw_understat, raw, understat_identity_universe)
    advanced["understat"] = _understat_summary(understat_tactical, raw_understat)

    competitive_load = build_competitive_load(
        raw,
        read_json(PRESS_EVIDENCE, {}),
        read_json(EXTERNAL_COMPETITIVE_EVIDENCE, {}),
    )
    atomic_json(COMPETITIVE_LOAD_OUT, competitive_load)

    weather_health = weather_context.get("health") or {}
    out = {
        "schema": "enrichment.v1",
        "schema_version": 499,
        "generated_at": iso_now(),
        "lineage": {"snapshot_schema": "snapshot.v1", "snapshot_sha256": file_digest(SNAPSHOT)},
        "stats_gw": stats_gw,
        "advanced_stats_sync": advanced,
        "official_fact_snapshot": official_snapshot,
        "understat_tactical": {
            "artifact": str(UNDERSTAT_OUT.relative_to(DATA.parent)),
            "contract": understat_tactical.get("contract"),
            "health": (understat_tactical.get("health") or {}).get("status"),
            "freshness": (understat_tactical.get("source") or {}).get("freshness"),
            "player_mapping_coverage": (understat_tactical.get("health") or {}).get("player_mapping_coverage"),
            "player_crosswalk_coverage": (understat_tactical.get("health") or {}).get("player_crosswalk_coverage"),
            "source_present_mapping_coverage": (understat_tactical.get("health") or {}).get("source_present_mapping_coverage"),
            "identity_unresolved_count": (understat_tactical.get("health") or {}).get("identity_unresolved_count"),
            "tactical_matchup_coverage": (understat_tactical.get("health") or {}).get("tactical_matchup_coverage"),
            "optional_enrichment": True,
            "direct_xpts_mutation": False,
            "direct_xmins_mutation": False,
        },
        "weather_context": {
            "artifact": "data/weather_context_v4.json",
            "contract": weather_context.get("contract"),
            "model": weather_context.get("model"),
            "provider": weather_context.get("provider"),
            "health": weather_health.get("status"),
            "reason": weather_health.get("reason"),
            "required_for_tactical_context": weather_health.get("required_for_tactical_context"),
            "tactical_context_completeness": weather_health.get("tactical_context_completeness"),
            "fixture_count": weather_context.get("fixture_count"),
            "available_count": weather_context.get("available_count"),
            "material_count": weather_context.get("material_count"),
            "evidence_precedence": weather_context.get("evidence_precedence"),
            "advisory_only": (weather_context.get("governance") or {}).get("advisory_only"),
            "expected_xpts_mean_adjustment": 0.0,
        },
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
            "source_snapshot_id": official_snapshot.get("source_snapshot_id"),
            "fetched_at": official_snapshot.get("fetched_at"),
            "freshness": official_snapshot.get("freshness"),
            "players": len(universe),
            "required_public_fact_complete": official_fact_complete,
            "identity_full_name": sum(bool(row.get("full_name")) for row in universe),
            "identity_variant_coverage": sum(bool(row.get("name_variants")) for row in universe),
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
        "official_fact_complete": official_fact_complete,
        "official_identity_full_name": out["official_player_evidence"]["identity_full_name"],
        "official_identity_variant_coverage": out["official_player_evidence"]["identity_variant_coverage"],
        "official_snapshot": official_snapshot.get("source_snapshot_id"),
        "stats_reused": {key: value.get("reused") for key, value in advanced.items() if isinstance(value, dict) and "reused" in value},
        "understat": (understat_tactical.get("health") or {}).get("status"),
        "understat_player_mapping_coverage": (understat_tactical.get("health") or {}).get("player_mapping_coverage"),
        "understat_player_crosswalk_coverage": (understat_tactical.get("health") or {}).get("player_crosswalk_coverage"),
        "understat_source_present_mapping_coverage": (understat_tactical.get("health") or {}).get("source_present_mapping_coverage"),
        "understat_identity_unresolved_count": (understat_tactical.get("health") or {}).get("identity_unresolved_count"),
        "understat_tactical_matchup_coverage": (understat_tactical.get("health") or {}).get("tactical_matchup_coverage"),
        "competitive_load_rows": competitive_load.get("coverage", {}).get("observed_player_fixture_rows"),
        "competitive_load_complete_for_visible_report": competitive_load.get("coverage", {}).get("complete_for_visible_report"),
        "weather_context": weather_health.get("status"),
        "weather_tactical_completeness": weather_health.get("tactical_context_completeness"),
        "weather_material_fixtures": weather_context.get("material_count"),
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
