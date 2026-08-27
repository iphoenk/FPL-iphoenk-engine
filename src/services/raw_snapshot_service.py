from __future__ import annotations

import argparse
import json
from collections import Counter
from time import perf_counter

from src.engine import TEAM_ID, _parallel_official_get, detect_phase, maps, resolve_locked_player
from src.engines.checkpoint_policy import resolve_checkpoint
from src.engines.team_value import build_transfer_spells, sell_cost
from src.sources.official_fpl import get_json
from src.utils import CONFIG, DATA, atomic_json, iso_now, parse_dt, read_json, utcnow

RUNTIME = DATA / "runtime"
OUTFILE = RUNTIME / "snapshot.v1.json"
POSITION_BY_TYPE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
POSITION_COUNTS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}


def _validate_authoritative_squad(squad: list[dict], by_id: dict[int, dict]) -> None:
    if not squad:
        return
    if len(squad) != 15:
        raise RuntimeError(f"FAIL CLOSED: squad count {len(squad)}")
    element_ids = [int(row.get("element") or -1) for row in squad]
    if len(element_ids) != len(set(element_ids)):
        raise RuntimeError("FAIL CLOSED: duplicate squad element")
    positions: Counter[str] = Counter()
    clubs: Counter[int] = Counter()
    for row in squad:
        element = int(row.get("element") or -1)
        player = by_id.get(element)
        if not player:
            raise RuntimeError(f"FAIL CLOSED: squad element {element} missing")
        actual_position = POSITION_BY_TYPE.get(player.get("element_type"))
        if not actual_position or row.get("position") != actual_position:
            raise RuntimeError(f"FAIL CLOSED: position mismatch {element}")
        positions[actual_position] += 1
        clubs[int(player.get("team") or 0)] += 1
    if dict(positions) != POSITION_COUNTS:
        raise RuntimeError(f"FAIL CLOSED: positions {dict(positions)}")
    if max(clubs.values(), default=0) > 3:
        raise RuntimeError(f"FAIL CLOSED: club limit {dict(clubs)}")


def _normalize_endpoint_health(health: dict, payloads: dict, submitted_gw: int | None, scoring_gw: int | None, is_live_event: bool) -> None:
    if submitted_gw:
        health.setdefault("picks", {})["status"] = "LIVE" if payloads.get("picks") else "NOT_YET_AVAILABLE"
    if scoring_gw and health.get("event_live", {}).get("status") == "LIVE" and not is_live_event:
        health["event_live"]["status"] = "IDLE"


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
    _normalize_endpoint_health(health, payloads, submitted_gw, scoring_gw, bool(phase.get("is_live_event")))
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
    _validate_authoritative_squad(squad, by_id)
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
    out = {"schema": "snapshot.v1", "schema_version": 491, "generated_at": iso_now(), "mode": mode, "as_of": as_of, "checkpoint_context": checkpoint, "phase": phase, "team_id": TEAM_ID, "official": {"bootstrap": bootstrap, **payloads}, "endpoint_health": health, "squad_authority": "LOCKED_PRE_DEADLINE" if use_lock else "OFFICIAL_SUBMITTED", "squad": squad, "team_value_ledger": ledger, "itb_tenths": lock.get("itb_tenths") if use_lock else (payloads.get("entry") or {}).get("last_deadline_bank"), "gw1_reconstruction_requested": need_gw1, "duration_ms": round((perf_counter() - started) * 1000, 2)}
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
