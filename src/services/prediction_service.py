from __future__ import annotations

import json
from time import perf_counter

from src.engines.fpl_rules_2026 import POSITION_BY_TYPE
from src.engines.source_sweep_status import build_source_sweep_status
from src.engines.v4_runner import build_predictions
from src.services.contracts import file_digest
from src.utils import DATA, append_jsonl, atomic_json, iso_now, read_json

RUNTIME = DATA / "runtime"
SNAPSHOT = RUNTIME / "snapshot.v1.json"
ENRICHMENT = RUNTIME / "enrichment.v1.json"
LIVE_STAT_FIELDS = (
    "minutes", "goals_scored", "assists", "clean_sheets", "goals_conceded",
    "own_goals", "penalties_saved", "penalties_missed", "yellow_cards", "red_cards",
    "saves", "bonus", "bps", "total_points", "defensive_contribution",
)


def _expanded_live(element_live: dict) -> dict:
    stats = element_live.get("stats") or {}
    out = {field: stats.get(field) for field in LIVE_STAT_FIELDS if field in stats}
    out["explain"] = element_live.get("explain")
    return out


def _write_price_artifacts(bootstrap: dict, generated: str) -> tuple[list[dict], list[dict]]:
    previous = read_json(DATA / "price_cache.json", {}).get("players", {})
    current, confirmed, momentum = {}, [], []
    total_players = bootstrap.get("total_players", 0) or 0
    for player in bootstrap.get("elements", []):
        key = str(player["id"])
        current[key] = {"now_cost": player["now_cost"], "ownership": player.get("selected_by_percent")}
        old = previous.get(key)
        if old and old.get("now_cost") != player["now_cost"]:
            confirmed.append({"element": player["id"], "name": player["web_name"], "previous": old["now_cost"], "current": player["now_cost"], "delta": player["now_cost"] - old["now_cost"]})
        ownership = float(player.get("selected_by_percent") or 0)
        estimated_owners = max(1, int(total_players * ownership / 100))
        net = (player.get("transfers_in_event") or 0) - (player.get("transfers_out_event") or 0)
        momentum.append({"element": player["id"], "name": player["web_name"], "net_transfers": net, "ownership_pct": ownership, "momentum": net / estimated_owners})
    momentum.sort(key=lambda row: row["momentum"], reverse=True)
    atomic_json(DATA / "price_cache.json", {"generated_at": generated, "players": current})
    atomic_json(DATA / "prices.json", {"generated_at": generated, "confirmed_changes": confirmed, "top_buy_pressure": momentum[:25], "top_sell_pressure": list(reversed(momentum[-25:]))})
    return confirmed, momentum


def _official_context_summary(bootstrap: dict, fixtures: list[dict]) -> dict:
    teams, players = list(bootstrap.get("teams") or []), list(bootstrap.get("elements") or [])
    upcoming = [row for row in fixtures if not row.get("finished") and row.get("event") is not None]
    strength_fields = ("strength_attack_home", "strength_attack_away", "strength_defence_home", "strength_defence_away", "strength_overall_home", "strength_overall_away")
    strength_complete = sum(all(team.get(field) is not None for field in strength_fields) for team in teams)
    fixture_context_complete = sum(row.get("team_h") is not None and row.get("team_a") is not None and row.get("team_h_difficulty") is not None and row.get("team_a_difficulty") is not None for row in upcoming)
    player_fields = {"ownership": "selected_by_percent", "expected_goals": "expected_goals", "expected_assists": "expected_assists", "expected_goal_involvements": "expected_goal_involvements", "expected_goals_conceded": "expected_goals_conceded", "bps": "bps", "bonus": "bonus", "form": "form", "starts": "starts"}
    coverage = {label: sum(player.get(field) is not None for player in players) for label, field in player_fields.items()}
    return {"source": "raw_snapshot.official.bootstrap+fixtures", "official_fpl_first": True, "teams": len(teams), "team_strength_rows_complete": strength_complete, "upcoming_fixture_rows": len(upcoming), "fixture_context_rows_complete": fixture_context_complete, "player_rows": len(players), "player_field_coverage": coverage, "effective_ownership_available_from_official_fpl": False, "external_schedule_scope": "premier_league_only"}


def _team_value_totals(ledger: list[dict], itb: int | None) -> dict:
    squad_market_value = sum(int(row["now_cost"]) for row in ledger)
    squad_sell_value = sum(int(row["sell_cost"]) for row in ledger if row.get("sell_cost") is not None)
    bank = int(itb or 0)
    return {
        "squad_market_value": squad_market_value,
        "itb": bank,
        "total_market_funds": squad_market_value + bank,
        "squad_sell_value": squad_sell_value,
        "transferable_funds": squad_sell_value + bank,
        "unit": "tenths_gbp_million",
    }


def run() -> dict:
    started = perf_counter()
    raw, enrichment = read_json(SNAPSHOT, {}), read_json(ENRICHMENT, {})
    if raw.get("schema") != "snapshot.v1" or enrichment.get("schema") != "enrichment.v1":
        raise RuntimeError("snapshot.v1 and enrichment.v1 required")
    snapshot_sha = file_digest(SNAPSHOT)
    if enrichment.get("lineage", {}).get("snapshot_sha256") != snapshot_sha:
        raise RuntimeError("enrichment lineage does not match snapshot")
    official, phase = raw["official"], raw["phase"]
    bootstrap, fixtures = official["bootstrap"], official.get("fixtures") or []
    generated = iso_now()
    predictions = build_predictions(bootstrap, fixtures, generated, stats_gw=enrichment.get("stats_gw"))
    atomic_json(DATA / "predictions_v4.json", predictions)
    atomic_json(DATA / "universe.json", {"generated_at": generated, "players": enrichment["universe"]})
    atomic_json(DATA / "health.json", raw["endpoint_health"])
    atomic_json(DATA / "chips.json", {"generated_at": generated, "used": (official.get("history") or {}).get("chips", [])})
    ledger, squad = raw["team_value_ledger"], raw["squad"]
    itb = raw.get("itb_tenths")
    value_totals = _team_value_totals(ledger, itb)
    atomic_json(DATA / "team.json", {"generated_at": generated, "team_id": raw["team_id"], "squad_authority": raw["squad_authority"], "projection_baseline": raw.get("projection_baseline") or {}, "squad": squad, "team_value_ledger": ledger, "totals": value_totals})
    live_payload = {"generated_at": generated, "status": "IDLE", "scoring_gw": phase.get("scoring_gw"), "players": []}
    picks, live = official.get("picks"), official.get("event_live")
    if picks and live:
        by_id = {player["id"]: player for player in bootstrap["elements"]}
        teams = {team["id"]: team["name"] for team in bootstrap.get("teams", [])}
        live_by_id = {player["id"]: player for player in live.get("elements", [])}
        detail, gross = [], 0
        for pick in picks.get("picks", []):
            stats = _expanded_live(live_by_id.get(pick["element"], {}))
            raw_points = stats.get("total_points", 0) or 0
            gross += raw_points * max(0, pick.get("multiplier", 0))
            player = by_id.get(pick["element"], {})
            detail.append({"element": pick["element"], "name": player.get("web_name"), "team": teams.get(player.get("team")), "position": POSITION_BY_TYPE.get(player.get("element_type")), "pick_position": pick.get("position"), "multiplier": pick.get("multiplier"), "captain": pick.get("is_captain"), "vice": pick.get("is_vice_captain"), **stats})
        hit = (picks.get("entry_history") or {}).get("event_transfers_cost", 0)
        live_payload.update({"status": "PROVISIONAL" if phase.get("is_live_event") else "RECONCILED_OR_IDLE", "gross_points": gross, "hit": hit, "net_points": gross - hit, "players": detail})
    atomic_json(DATA / "live.json", live_payload)
    confirmed, momentum = _write_price_artifacts(bootstrap, generated)
    enrichment_sha = file_digest(ENRICHMENT)
    prediction_ms = round((perf_counter() - started) * 1000, 2)
    raw_snapshot_ms = float(raw.get("duration_ms") or 0)
    enrichment_ms = float(enrichment.get("duration_ms") or 0)
    official_context = _official_context_summary(bootstrap, fixtures)
    source_sweep_status = build_source_sweep_status(raw.get("endpoint_health") or {})
    latest = {
        "schema_version": 496,
        "engine_version": "4.9.6-official-first-reporting",
        "generated_at": generated, "mode": raw["mode"], "checkpoint_context": raw["checkpoint_context"], "team_id": raw["team_id"], "phase": phase,
        "endpoint_health": raw["endpoint_health"], "source_sweep_status": source_sweep_status, "squad_authority": raw["squad_authority"], "projection_baseline": raw.get("projection_baseline") or {}, "advanced_stats_sync": enrichment["advanced_stats_sync"], "official_context": official_context,
        "prediction_summary": {"model": predictions["model_version"], "players": len(predictions["players"]), "top_5gw": predictions["players"][:10]},
        "team_summary": value_totals,
        "live_summary": {"status": live_payload["status"], "gross_points": live_payload.get("gross_points"), "net_points": live_payload.get("net_points")},
        "price_summary": {"confirmed_changes": confirmed, "top_buy_pressure": momentum[:10]},
        "lineage": {"snapshot_sha256": snapshot_sha, "enrichment_sha256": enrichment_sha},
        "files": {"team": "data/team.json", "live": "data/live.json", "prices": "data/prices.json", "health": "data/health.json", "universe": "data/universe.json", "chips": "data/chips.json", "predictions": "data/predictions_v4.json", "effective_plan": "data/effective_plan_v4.json", "gw_scorecard": "data/gw_scorecard_v4.json", "checkpoint_decision": "data/checkpoint_decision_v4.json", "service_orchestration": "data/service_orchestration_v4.json"},
        "performance": {"raw_snapshot_ms": raw_snapshot_ms, "enrichment_ms": enrichment_ms, "prediction_ms": prediction_ms, "engine_before_snapshot_write_ms": round(raw_snapshot_ms + enrichment_ms + prediction_ms, 2)},
        "meta": {"direct_fpl_api_authority": False, "raw_snapshot_is_official_api_authority": True, "official_fpl_first_for_available_fields": True, "fail_closed": True, "prediction_point_in_time": True, "advanced_stats_are_community_enrichment": True, "leakage_guard_required_for_predictive_training": True, "parallel_fetch_is_single_snapshot_not_polling": True, "checkpoint_policy_registry_driven": True, "simulation_never_authorizes_action": True, "service_contract_compatible": True, "service_boundaries_registry_driven": True, "engine_recommendations_are_advisory": True, "human_effective_plan_is_separate_contract": True, "source_governance_names_do_not_imply_runtime_adapters": True, "team_value_labels_are_semantically_explicit": True},
    }
    atomic_json(DATA / "latest.json", latest)
    gw = phase.get("submitted_gw") or phase.get("planning_gw")
    if gw:
        atomic_json(DATA / "gw" / f"{gw:02d}.json", latest)
    append_jsonl(DATA / "history.jsonl", latest)
    print(json.dumps({"service": "prediction", "engine": latest["engine_version"], "players": len(predictions["players"]), "official_context": official_context, "source_sweep_runtime_wired": source_sweep_status.get("runtime_wired_sources"), "duration_ms": latest["performance"]["prediction_ms"]}))
    return latest


if __name__ == "__main__":
    run()
