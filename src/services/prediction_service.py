from __future__ import annotations

import json
from time import perf_counter

from src.engines.fpl_rules_2026 import POSITION_BY_TYPE
from src.engines.source_sweep_status import build_source_sweep_status
from src.engines.v4_freshness import evaluate_freshness
from src.engines.v4_price_context import refresh_price_context
from src.engines.v4_xmins_evidence import attach_xmins_evidence
from src.services.contracts import file_digest
from src.services.prediction_model_cache import build_predictions_cached, last_status as prediction_cache_status
from src.utils import DATA, append_jsonl, atomic_json, iso_now, read_json

# Compatibility seam retained for tests and callers that patch the prediction
# builder at the service boundary. Production points this alias at the exact
# semantic cache wrapper.
build_predictions = build_predictions_cached

RUNTIME = DATA / "runtime"
SNAPSHOT = RUNTIME / "snapshot.v1.json"
ENRICHMENT = RUNTIME / "enrichment.v1.json"
LIVE_STAT_FIELDS = (
    "minutes", "goals_scored", "assists", "clean_sheets", "goals_conceded", "own_goals",
    "penalties_saved", "penalties_missed", "yellow_cards", "red_cards", "saves", "bonus",
    "bps", "total_points", "defensive_contribution",
)


def _expanded_live(element_live):
    stats = element_live.get("stats") or {}
    out = {field: stats.get(field) for field in LIVE_STAT_FIELDS if field in stats}
    out["explain"] = element_live.get("explain")
    return out


def _official_context_summary(bootstrap, fixtures):
    teams = list(bootstrap.get("teams") or [])
    players = list(bootstrap.get("elements") or [])
    upcoming = [row for row in fixtures if not row.get("finished") and row.get("event") is not None]
    strength_fields = (
        "strength_attack_home", "strength_attack_away", "strength_defence_home",
        "strength_defence_away", "strength_overall_home", "strength_overall_away",
    )
    strength_complete = sum(all(team.get(field) is not None for field in strength_fields) for team in teams)
    fixture_context_complete = sum(
        row.get("team_h") is not None and row.get("team_a") is not None
        and row.get("team_h_difficulty") is not None and row.get("team_a_difficulty") is not None
        for row in upcoming
    )
    player_fields = {
        "ownership": "selected_by_percent", "expected_goals": "expected_goals",
        "expected_assists": "expected_assists", "expected_goal_involvements": "expected_goal_involvements",
        "expected_goals_conceded": "expected_goals_conceded", "bps": "bps", "bonus": "bonus",
        "form": "form", "starts": "starts",
    }
    coverage = {label: sum(player.get(field) is not None for player in players) for label, field in player_fields.items()}
    return {
        "source": "raw_snapshot.official.bootstrap+fixtures",
        "official_fpl_first": True,
        "teams": len(teams),
        "team_strength_rows_complete": strength_complete,
        "upcoming_fixture_rows": len(upcoming),
        "fixture_context_rows_complete": fixture_context_complete,
        "player_rows": len(players),
        "player_field_coverage": coverage,
        "effective_ownership_available_from_official_fpl": False,
        "external_schedule_scope": "premier_league_only",
    }


def _team_value_totals(ledger, itb):
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
        "market_value": squad_market_value,
        "sell_value": squad_sell_value,
    }


def _chip_state_summary(official, phase):
    picks = official.get("picks") or {}
    history = official.get("history") or {}
    submitted_chip = str(picks.get("active_chip") or "NONE").upper()
    used = list(history.get("chips") or [])
    used_names = [str(row.get("name") or "").upper() for row in used if isinstance(row, dict)]
    return {
        "submitted_gw": phase.get("submitted_gw"),
        "submitted_chip": submitted_chip,
        "submitted_chip_source": "official_fpl_picks.active_chip",
        "chip_used_this_submitted_gw": submitted_chip != "NONE",
        "historical_used_chips": used_names,
        "planning_gw": phase.get("planning_gw"),
        "planning_chip": "NONE",
        "planning_chip_source": "decision_pipeline_default_until_explicit_user_plan",
        "phase_semantics": "submitted_chip_is_historical_truth_after_deadline; planning_chip_is_future_decision_state",
    }


def run():
    started = perf_counter()
    raw = read_json(SNAPSHOT, {})
    enrichment = read_json(ENRICHMENT, {})
    if raw.get("schema") != "snapshot.v1" or enrichment.get("schema") != "enrichment.v1":
        raise RuntimeError("snapshot.v1 and enrichment.v1 required")
    snapshot_sha = file_digest(SNAPSHOT)
    if enrichment.get("lineage", {}).get("snapshot_sha256") != snapshot_sha:
        raise RuntimeError("enrichment lineage does not match snapshot")

    official = raw["official"]
    phase = raw["phase"]
    bootstrap = official["bootstrap"]
    fixtures = official.get("fixtures") or []
    generated = iso_now()

    t = perf_counter()
    predictions = build_predictions(bootstrap, fixtures, generated, stats_gw=enrichment.get("stats_gw"))
    base_prediction_ms = round((perf_counter() - t) * 1000, 2)
    cache_status = prediction_cache_status()

    t = perf_counter()
    competitive_load = read_json(DATA / "competitive_load_v4.json", {})
    predictions = attach_xmins_evidence(predictions, competitive_load)
    xmins_evidence_ms = round((perf_counter() - t) * 1000, 2)

    atomic_json(DATA / "predictions_v4.json", predictions)
    atomic_json(DATA / "universe.json", {"generated_at": generated, "players": enrichment["universe"]})
    atomic_json(DATA / "health.json", raw["endpoint_health"])

    chip_summary = _chip_state_summary(official, phase)
    atomic_json(DATA / "chips.json", {
        "generated_at": generated, "used": (official.get("history") or {}).get("chips", []), "current": chip_summary,
    })
    ledger, squad, itb = raw["team_value_ledger"], raw["squad"], raw.get("itb_tenths")
    value_totals = _team_value_totals(ledger, itb)
    team_payload = {
        "generated_at": generated,
        "team_id": raw["team_id"],
        "squad_authority": raw["squad_authority"],
        "projection_baseline": raw.get("projection_baseline") or {},
        "squad": squad,
        "team_value_ledger": ledger,
        "totals": value_totals,
        "chip_summary": chip_summary,
        "free_transfers": None,
        "free_transfer_source": "AUTHENTICATED_MY_TEAM_REQUIRED_NOT_AVAILABLE_IN_PUBLIC_SNAPSHOT",
    }
    atomic_json(DATA / "team.json", team_payload)

    live_payload = {
        "generated_at": generated,
        "official_snapshot_at": raw.get("generated_at"),
        "status": "IDLE",
        "scoring_gw": phase.get("scoring_gw"),
        "submitted_gw": phase.get("submitted_gw"),
        "players": [],
    }
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
            detail.append({
                "element": pick["element"], "name": player.get("web_name"), "team": teams.get(player.get("team")),
                "position": POSITION_BY_TYPE.get(player.get("element_type")), "pick_position": pick.get("position"),
                "multiplier": pick.get("multiplier"), "captain": pick.get("is_captain"),
                "vice": pick.get("is_vice_captain"), **stats,
            })
        hit = (picks.get("entry_history") or {}).get("event_transfers_cost", 0)
        live_payload.update({
            "status": "PROVISIONAL" if phase.get("is_live_event") else "RECONCILED_OR_IDLE",
            "gross_points": gross, "hit": hit, "net_points": gross - hit, "players": detail,
            "active_chip": picks.get("active_chip"), "automatic_subs": picks.get("automatic_subs") or [],
            "native_submitted_facts_preserved": True,
        })
    atomic_json(DATA / "live.json", live_payload)

    price_context = refresh_price_context()
    confirmed = price_context.get("confirmed_changes") or []
    momentum = price_context.get("top_buy_pressure") or []
    next_price_update = next(
        (row.get("next_official_price_update_at") for row in price_context.get("players") or [] if row.get("next_official_price_update_at")),
        None,
    )
    enrichment_sha = file_digest(ENRICHMENT)
    prediction_ms = round((perf_counter() - started) * 1000, 2)
    raw_snapshot_ms = float(raw.get("duration_ms") or 0)
    enrichment_ms = float(enrichment.get("duration_ms") or 0)
    official_context = _official_context_summary(bootstrap, fixtures)
    source_sweep_status = build_source_sweep_status(raw.get("endpoint_health") or {})

    latest = {
        "schema_version": 496,
        "engine_version": "4.9.6-official-first-reporting",
        "generated_at": generated,
        "official_snapshot_at": raw.get("generated_at"),
        "runtime_publish_at": None,
        "mode": raw["mode"],
        "checkpoint_context": raw["checkpoint_context"],
        "team_id": raw["team_id"],
        "phase": phase,
        "endpoint_health": raw["endpoint_health"],
        "source_sweep_status": source_sweep_status,
        "squad_authority": raw["squad_authority"],
        "projection_baseline": raw.get("projection_baseline") or {},
        "advanced_stats_sync": enrichment["advanced_stats_sync"],
        "competitive_load_summary": enrichment.get("competitive_load") or {},
        "official_context": official_context,
        "prediction_summary": {"model": predictions["model_version"], "players": len(predictions["players"]), "top_5gw": predictions["players"][:10]},
        "team_summary": value_totals,
        "chip_summary": chip_summary,
        "live_summary": {
            "status": live_payload["status"], "gross_points": live_payload.get("gross_points"),
            "net_points": live_payload.get("net_points"), "active_live_fixture_count": phase.get("active_live_fixture_count"),
            "is_live_match": phase.get("is_live_match"),
        },
        "price_summary": {
            "health": price_context.get("health"),
            "confirmed_changes": confirmed,
            "top_buy_pressure": momentum[:10],
            "next_official_price_update_wib": next_price_update,
            "all15": price_context.get("all15_actionable_price_radar") or [],
            "all20_stage": "JOINED_READ_ONLY_AFTER_GOVERNED_DSS_WATCHLIST_DISCOVERY",
            "summary": "Harga resmi dipakai untuk timing, affordability, optionality, dan perlindungan sell value; bukan sebagai alasan mandiri untuk BUY/SELL/HIT.",
        },
        "market_context": {
            "price": {
                "status": (price_context.get("health") or {}).get("status"),
                "source": price_context.get("source"),
                "contract": price_context.get("contract"),
                "policy_id": price_context.get("policy_id"),
                "next_official_price_update_wib": next_price_update,
            }
        },
        "lineage": {"snapshot_sha256": snapshot_sha, "enrichment_sha256": enrichment_sha},
        "files": {
            "team": "data/team.json", "live": "data/live.json", "prices": "data/prices.json", "price_context": "data/prices.json", "health": "data/health.json",
            "universe": "data/universe.json", "chips": "data/chips.json", "predictions": "data/predictions_v4.json",
            "competitive_load": "data/competitive_load_v4.json", "tactical_serving": "data/tactical_serving_v4.json",
            "decision_arbitration": "data/decision_arbitration_v4.json", "effective_plan": "data/effective_plan_v4.json",
            "gw_scorecard": "data/gw_scorecard_v4.json", "checkpoint_decision": "data/checkpoint_decision_v4.json",
            "serving_payload": "data/serving_payload_v4.json", "serving_benchmark": "data/serving_benchmark_v4.json",
            "service_orchestration": "data/service_orchestration_v4.json",
        },
        "performance": {
            "raw_snapshot_ms": raw_snapshot_ms,
            "enrichment_ms": enrichment_ms,
            "prediction_ms": prediction_ms,
            "base_prediction_ms": base_prediction_ms,
            "xmins_evidence_ms": xmins_evidence_ms,
            "prediction_base_cache_hit": bool(cache_status.get("hit")),
            "prediction_base_cache_reason": cache_status.get("reason"),
            "engine_before_snapshot_write_ms": round(raw_snapshot_ms + enrichment_ms + prediction_ms, 2),
        },
        "meta": {
            "direct_fpl_api_authority": False, "raw_snapshot_is_official_api_authority": True,
            "official_fpl_first_for_available_fields": True, "fail_closed": True, "prediction_point_in_time": True,
            "advanced_stats_are_community_enrichment": True, "leakage_guard_required_for_predictive_training": True,
            "parallel_fetch_is_single_snapshot_not_polling": True, "checkpoint_policy_registry_driven": True,
            "simulation_never_authorizes_action": True, "service_contract_compatible": True,
            "service_boundaries_registry_driven": True, "engine_recommendations_are_advisory": True,
            "human_effective_plan_is_separate_contract": True, "source_governance_names_do_not_imply_runtime_adapters": True,
            "team_value_labels_are_semantically_explicit": True, "legacy_team_value_aliases_are_machine_contract_only": True,
            "chip_state_is_phase_aware": True, "submitted_native_match_facts_preserved": True,
            "prediction_base_cache_exact_semantic_only": True,
            "competitive_load_reattached_after_base_cache": True,
            "official_price_predictor_runtime_wired": True,
            "price_predictor_no_network_refetch": True,
            "price_signal_subordinate_to_football": True,
            "price_predictor_canonical_module": "src.engines.price_radar",
            "price_artifact_single_writer": "prediction",
        },
    }
    freshness = evaluate_freshness(latest)
    latest["freshness"] = freshness
    latest["source_age_minutes"] = freshness.get("source_age_minutes")
    latest["freshness_state"] = freshness.get("freshness_state")
    atomic_json(DATA / "latest.json", latest)
    gw = phase.get("submitted_gw") or phase.get("planning_gw")
    if gw:
        atomic_json(DATA / "gw" / f"{gw:02d}.json", latest)
    append_jsonl(DATA / "history.jsonl", latest)
    print(json.dumps({
        "service": "prediction", "engine": latest["engine_version"], "players": len(predictions["players"]),
        "freshness_state": latest["freshness_state"], "source_age_minutes": latest["source_age_minutes"],
        "source_sweep_runtime_wired": source_sweep_status.get("runtime_wired_sources"),
        "prediction_base_cache_hit": bool(cache_status.get("hit")),
        "base_prediction_ms": base_prediction_ms,
        "xmins_evidence_ms": xmins_evidence_ms,
        "price_context_health": (price_context.get("health") or {}).get("status"),
        "duration_ms": prediction_ms,
    }))
    return latest


if __name__ == "__main__":
    run()
