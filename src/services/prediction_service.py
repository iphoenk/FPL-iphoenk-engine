from __future__ import annotations

import json
from time import perf_counter

from src.engine import expanded_live
from src.engines.v4_runner import build_predictions
from src.services.contracts import file_digest
from src.utils import DATA, append_jsonl, atomic_json, iso_now, read_json

RUNTIME = DATA / "runtime"
SNAPSHOT = RUNTIME / "snapshot.v1.json"
ENRICHMENT = RUNTIME / "enrichment.v1.json"


def _write_price_artifacts(bootstrap: dict, generated: str) -> tuple[list[dict], list[dict]]:
    previous = read_json(DATA / "price_cache.json", {}).get("players", {})
    current: dict[str, dict] = {}
    confirmed: list[dict] = []
    momentum: list[dict] = []
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
    atomic_json(DATA / "team.json", {"generated_at": generated, "team_id": raw["team_id"], "squad_authority": raw["squad_authority"], "squad": squad, "team_value_ledger": ledger, "totals": {"market_value": sum(x["now_cost"] for x in ledger), "sell_value": sum(x["sell_cost"] for x in ledger if x["sell_cost"] is not None), "itb": itb}})
    live_payload = {"generated_at": generated, "status": "IDLE", "scoring_gw": phase.get("scoring_gw"), "players": []}
    picks, live = official.get("picks"), official.get("event_live")
    if picks and live:
        by_id = {p["id"]: p for p in bootstrap["elements"]}; teams = {t["id"]: t["name"] for t in bootstrap.get("teams", [])}; positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}; live_by_id = {p["id"]: p for p in live.get("elements", [])}; detail = []; gross = 0
        for pick in picks.get("picks", []):
            stats = expanded_live(live_by_id.get(pick["element"], {})); raw_points = stats.get("total_points", 0) or 0; gross += raw_points * max(0, pick.get("multiplier", 0)); player = by_id.get(pick["element"], {})
            detail.append({"element": pick["element"], "name": player.get("web_name"), "team": teams.get(player.get("team")), "position": positions.get(player.get("element_type")), "pick_position": pick.get("position"), "multiplier": pick.get("multiplier"), "captain": pick.get("is_captain"), "vice": pick.get("is_vice_captain"), **stats})
        hit = (picks.get("entry_history") or {}).get("event_transfers_cost", 0); live_payload.update({"status": "PROVISIONAL" if phase.get("is_live_event") else "RECONCILED_OR_IDLE", "gross_points": gross, "hit": hit, "net_points": gross-hit, "players": detail})
    atomic_json(DATA / "live.json", live_payload)
    confirmed, momentum = _write_price_artifacts(bootstrap, generated)
    enrichment_sha = file_digest(ENRICHMENT)
    prediction_ms = round((perf_counter() - started) * 1000, 2)
    raw_snapshot_ms = float(raw.get("duration_ms") or 0)
    enrichment_ms = float(enrichment.get("duration_ms") or 0)
    latest = {"schema_version": 491, "engine_version": "4.9.1-independent-services", "generated_at": generated, "mode": raw["mode"], "checkpoint_context": raw["checkpoint_context"], "team_id": raw["team_id"], "phase": phase, "endpoint_health": raw["endpoint_health"], "squad_authority": raw["squad_authority"], "advanced_stats_sync": enrichment["advanced_stats_sync"], "prediction_summary": {"model": predictions["model_version"], "players": len(predictions["players"]), "top_5gw": predictions["players"][:10]}, "team_summary": {"itb": itb, "market_value": sum(x["now_cost"] for x in ledger), "sell_value": sum(x["sell_cost"] for x in ledger if x["sell_cost"] is not None)}, "live_summary": {"status": live_payload["status"], "gross_points": live_payload.get("gross_points"), "net_points": live_payload.get("net_points")}, "price_summary": {"confirmed_changes": confirmed, "top_buy_pressure": momentum[:10]}, "lineage": {"snapshot_sha256": snapshot_sha, "enrichment_sha256": enrichment_sha}, "files": {"team": "data/team.json", "live": "data/live.json", "prices": "data/prices.json", "health": "data/health.json", "universe": "data/universe.json", "chips": "data/chips.json", "predictions": "data/predictions_v4.json", "checkpoint_decision": "data/checkpoint_decision_v4.json", "service_orchestration": "data/service_orchestration_v4.json"}, "performance": {"raw_snapshot_ms": raw_snapshot_ms, "enrichment_ms": enrichment_ms, "prediction_ms": prediction_ms, "engine_before_snapshot_write_ms": round(raw_snapshot_ms + enrichment_ms + prediction_ms, 2)}, "meta": {"direct_fpl_api_authority": False, "raw_snapshot_is_official_api_authority": True, "fail_closed": True, "prediction_point_in_time": True, "advanced_stats_are_community_enrichment": True, "leakage_guard_required_for_predictive_training": True, "parallel_fetch_is_single_snapshot_not_polling": True, "checkpoint_policy_registry_driven": True, "simulation_never_authorizes_action": True, "service_contract_compatible": True, "service_boundaries_registry_driven": True}}
    atomic_json(DATA / "latest.json", latest)
    gw = phase.get("submitted_gw") or phase.get("planning_gw")
    if gw:
        atomic_json(DATA / "gw" / f"{gw:02d}.json", latest)
    append_jsonl(DATA / "history.jsonl", latest)
    print(json.dumps({"service": "prediction", "engine": latest["engine_version"], "players": len(predictions["players"]), "duration_ms": latest["performance"]["prediction_ms"]}))
    return latest


if __name__ == "__main__":
    run()
