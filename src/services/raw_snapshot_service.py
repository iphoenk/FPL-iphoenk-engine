from __future__ import annotations

import argparse
import json
from time import perf_counter

from src.engine import TEAM_ID, _parallel_official_get, detect_phase, maps, resolve_locked_player
from src.engines.checkpoint_policy import resolve_checkpoint
from src.engines.team_value import build_transfer_spells, sell_cost
from src.sources.official_fpl import get_json
from src.utils import CONFIG, DATA, atomic_json, iso_now, parse_dt, read_json, utcnow

RUNTIME = DATA / "runtime"
OUTFILE = RUNTIME / "snapshot.v1.json"


def run(mode: str = "daily", as_of: str | None = None) -> dict:
    """Acquire the sole official-FPL snapshot and finish price reconstruction."""
    started = perf_counter()
    report_as_of = parse_dt(as_of) if isinstance(as_of, str) else as_of
    if report_as_of is not None and report_as_of.tzinfo is None:
        raise RuntimeError("--as-of must include timezone offset")
    bootstrap, bootstrap_health = get_json("bootstrap-static/")
    if not bootstrap:
        raise RuntimeError("bootstrap unavailable")
    phase = detect_phase(bootstrap, report_as_of or utcnow())
    checkpoint = resolve_checkpoint(mode, phase.get("deadline_time"), phase.get("is_live_event", False), as_of=report_as_of, simulated=report_as_of is not None)
    submitted_gw, scoring_gw = phase["submitted_gw"], phase["scoring_gw"]
    specs = [("fixtures", "fixtures/", 3), ("event_status", "event-status/", 3), ("entry", f"entry/{TEAM_ID}/", 3), ("history", f"entry/{TEAM_ID}/history/", 3), ("transfers", f"entry/{TEAM_ID}/transfers/", 3)]
    if submitted_gw:
        specs.append(("picks", f"entry/{TEAM_ID}/event/{submitted_gw}/picks/", 3))
    if scoring_gw:
        specs.append(("event_live", f"event/{scoring_gw}/live/", 3))
    fetched = _parallel_official_get(specs)
    payloads = {key: pair[0] for key, pair in fetched.items()}
    health = {"bootstrap": bootstrap_health, **{key: pair[1] for key, pair in fetched.items()}}
    teams, positions, by_id = maps(bootstrap)
    lock = read_json(CONFIG / "locked_squad.json", {})
    use_lock = bool(lock.get("wildcard_active")) and phase["planning_gw"] != submitted_gw
    squad = []
    if use_lock:
        for row in lock.get("players", []):
            player = resolve_locked_player(row, by_id, teams, positions)
            squad.append({"element": player["id"], "name": player["web_name"], "position": positions[player["element_type"]], "purchase_cost": row.get("purchase_cost"), "source": "locked_squad_element_id"})
    else:
        for pick in (payloads.get("picks") or {}).get("picks", []):
            player = by_id.get(pick["element"])
            if player:
                squad.append({"element": player["id"], "name": player["web_name"], "position": positions[player["element_type"]], "purchase_cost": pick.get("purchase_price"), "selling_price": pick.get("selling_price"), "source": "official_picks"})
    if squad and len(squad) != 15:
        raise RuntimeError(f"FAIL CLOSED: squad count {len(squad)}")
    spells = build_transfer_spells(payloads.get("transfers") or [])
    need_gw1 = any(row.get("purchase_cost") is None and (spells.get(row["element"]) or {}).get("purchase_cost") is None for row in squad)
    gw1_ids: set[int] = set()
    if need_gw1:
        # Conditional reconstruction is part of acquisition, never a downstream fetch.
        gw1, gw1_health = get_json(f"entry/{TEAM_ID}/event/1/picks/", retries=1)
        health["gw1_picks"] = gw1_health
        payloads["gw1_picks"] = gw1
        gw1_ids = {row["element"] for row in (gw1 or {}).get("picks", [])}
    ledger = []
    for row in squad:
        player = by_id[row["element"]]
        purchase, source = row.get("purchase_cost"), row.get("source")
        if purchase is None and (spells.get(player["id"]) or {}).get("purchase_cost") is not None:
            purchase, source = spells[player["id"]]["purchase_cost"], "entry/transfers"
        elif purchase is None and player["id"] in gw1_ids:
            purchase, source = player["now_cost"] - player.get("cost_change_start", 0), "gw1_reconstruction"
        selling = row.get("selling_price")
        if selling is None and purchase is not None:
            selling = sell_cost(player["now_cost"], int(purchase))
        ledger.append({"element": player["id"], "name": player["web_name"], "team": teams[player["team"]], "position": positions[player["element_type"]], "purchase_cost": purchase, "now_cost": player["now_cost"], "sell_cost": selling, "purchase_source": source, "ownership": player.get("selected_by_percent"), "status": player.get("status")})
    out = {"schema": "snapshot.v1", "schema_version": 481, "generated_at": iso_now(), "mode": mode, "as_of": as_of, "checkpoint_context": checkpoint, "phase": phase, "team_id": TEAM_ID, "official": {"bootstrap": bootstrap, **payloads}, "endpoint_health": health, "squad_authority": "LOCKED_PRE_DEADLINE" if use_lock else "OFFICIAL_SUBMITTED", "squad": squad, "team_value_ledger": ledger, "itb_tenths": lock.get("itb_tenths") if use_lock else (payloads.get("entry") or {}).get("last_deadline_bank"), "gw1_reconstruction_requested": need_gw1, "duration_ms": round((perf_counter() - started) * 1000, 2)}
    atomic_json(OUTFILE, out)
    print(json.dumps({"service": "raw_snapshot", "schema": "snapshot.v1", "duration_ms": out["duration_ms"]}))
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("daily", "deadline", "live"))
    parser.add_argument("--as-of")
    args = parser.parse_args()
    return run(args.mode, args.as_of)


if __name__ == "__main__":
    cli()
