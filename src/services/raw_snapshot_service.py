from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from src.engines.checkpoint_policy import resolve_checkpoint
from src.engines.fpl_legality import squad_legality_checks
from src.engines.fpl_rules_2026 import POSITION_BY_TYPE
from src.engines.team_value import build_transfer_spells, sell_cost
from src.sources.official_fpl import get_json
from src.utils import CONFIG, DATA, atomic_json, iso_now, parse_dt, read_json, utcnow

RUNTIME = DATA / "runtime"
OUTFILE = RUNTIME / "snapshot.v1.json"
_ENGINE_CONFIG = read_json(CONFIG / "engine.json", {})
TEAM_ID = int(_ENGINE_CONFIG.get("team_id") or 0)
API_RETRIES = int(_ENGINE_CONFIG.get("api_retries") or 0)
if TEAM_ID <= 0 or API_RETRIES <= 0:
    raise RuntimeError("engine config must provide positive team_id and api_retries")


def _parallel_official_get(specs: list[tuple[str, str, int]]) -> dict:
    """Fetch one point-in-time Official FPL wave concurrently."""
    if not specs:
        return {}

    def fetch(item):
        key, path, retries = item
        return key, get_json(path, retries=retries)

    with ThreadPoolExecutor(max_workers=min(6, len(specs)), thread_name_prefix="fpl-api") as pool:
        return dict(pool.map(fetch, specs))


def detect_phase(bootstrap: dict, as_of=None) -> dict:
    now = as_of or utcnow()
    events = bootstrap.get("events", [])
    current = next((event for event in events if event.get("is_current")), None)
    nxt = next((event for event in events if event.get("is_next")), None)
    finished = [event for event in events if event.get("finished")]
    last = max(finished, key=lambda event: event["id"]) if finished else None
    if current:
        deadline = parse_dt(current.get("deadline_time"))
        planning = current if deadline and deadline > now else (nxt or current)
    else:
        planning = nxt
    return {
        "current_gw": current["id"] if current else None,
        "next_gw": nxt["id"] if nxt else None,
        "last_finished_gw": last["id"] if last else None,
        "planning_gw": planning["id"] if planning else None,
        "submitted_gw": (current or last or {}).get("id"),
        "scoring_gw": current["id"] if current else None,
        "deadline_time": planning.get("deadline_time") if planning else None,
        "is_live_event": bool(current and not current.get("finished")),
    }


def maps(bootstrap: dict) -> tuple[dict, dict, dict]:
    teams = {team["id"]: team["name"] for team in bootstrap["teams"]}
    by_id = {player["id"]: player for player in bootstrap["elements"]}
    return teams, POSITION_BY_TYPE, by_id


def resolve_locked_player(row: dict, by_id: dict, teams: dict, positions: dict) -> dict:
    element = row.get("element")
    player = by_id.get(int(element)) if element is not None else None
    if not player:
        raise RuntimeError(f"FAIL CLOSED: locked element {element} missing")
    if row.get("position") and positions.get(player.get("element_type")) != row["position"]:
        raise RuntimeError(f"FAIL CLOSED: position mismatch {element}")
    if row.get("expected_web_name") and player.get("web_name") != row["expected_web_name"]:
        raise RuntimeError(f"FAIL CLOSED: name mismatch {element}")
    if row.get("expected_team") and teams.get(player.get("team")) != row["expected_team"]:
        raise RuntimeError(f"FAIL CLOSED: team mismatch {element}")
    return player


def _validate_authoritative_squad(squad: list[dict], by_id: dict[int, dict]) -> None:
    if not squad:
        return
    for row in squad:
        element = int(row.get("element") or -1)
        player = by_id.get(element)
        if not player:
            raise RuntimeError(f"FAIL CLOSED: squad element {element} missing")
        actual_position = POSITION_BY_TYPE.get(player.get("element_type"))
        if not actual_position or row.get("position") != actual_position:
            raise RuntimeError(f"FAIL CLOSED: position mismatch {element}")
        if row.get("team_id") != player.get("team"):
            raise RuntimeError(f"FAIL CLOSED: team mismatch {element}")
    failed = {
        name: detail
        for name, (passed, detail) in squad_legality_checks(squad).items()
        if not passed
    }
    if failed:
        raise RuntimeError(f"FAIL CLOSED: authoritative squad illegal {failed}")


def _normalize_endpoint_health(health: dict, payloads: dict, submitted_gw: int | None, scoring_gw: int | None, is_live_event: bool) -> None:
    if submitted_gw:
        health.setdefault("picks", {})["status"] = "LIVE" if payloads.get("picks") else "NOT_YET_AVAILABLE"
    if scoring_gw and health.get("event_live", {}).get("status") == "LIVE" and not is_live_event:
        health["event_live"]["status"] = "IDLE"


def _projection_baseline_authority(lock: dict, phase: dict) -> dict:
    """Resolve planning squad authority without allowing a stale draft into later GWs."""
    planning_gw = int(phase.get("planning_gw") or 0) or None
    submitted_gw = int(phase.get("submitted_gw") or 0) or None
    override_requested = bool(lock.get("planning_override_active") or lock.get("wildcard_active"))
    target_raw = lock.get("target_gw")
    if override_requested and target_raw is None:
        raise RuntimeError("FAIL CLOSED: active planning override missing target_gw")
    target_gw = int(target_raw) if target_raw is not None else None
    override_applied = bool(override_requested and planning_gw is not None and target_gw == planning_gw and planning_gw != submitted_gw)
    source = str(lock.get("authority_source") or "USER_PLANNING_OVERRIDE") if override_applied else "OFFICIAL_FPL_PICKS"
    return {
        "planning_gw": planning_gw,
        "baseline_gw": submitted_gw,
        "default_rule": "PLANNING_GW_FROM_PREVIOUS_OFFICIAL_SUBMITTED_SQUAD",
        "default_authority": "OFFICIAL_SUBMITTED",
        "override_requested": override_requested,
        "override_target_gw": target_gw,
        "override_applied": override_applied,
        "effective_authority": "LOCKED_PRE_DEADLINE" if override_applied else "OFFICIAL_SUBMITTED",
        "authority_source": source,
        "stale_override_rejected": bool(override_requested and not override_applied and target_gw != planning_gw),
    }


def run(mode: str = "daily", as_of: str | None = None) -> dict:
    """Acquire the sole Official FPL snapshot and finish purchase/sell-value reconstruction."""
    started = perf_counter()
    report_as_of = parse_dt(as_of) if isinstance(as_of, str) else as_of
    if report_as_of is not None and report_as_of.tzinfo is None:
        raise RuntimeError("--as-of must include timezone offset")

    initial_specs = [
        ("bootstrap", "bootstrap-static/", API_RETRIES),
        ("fixtures", "fixtures/", API_RETRIES),
        ("event_status", "event-status/", API_RETRIES),
        ("entry", f"entry/{TEAM_ID}/", API_RETRIES),
        ("history", f"entry/{TEAM_ID}/history/", API_RETRIES),
        ("transfers", f"entry/{TEAM_ID}/transfers/", API_RETRIES),
    ]
    wave_started = perf_counter()
    initial = _parallel_official_get(initial_specs)
    initial_wave_ms = round((perf_counter() - wave_started) * 1000, 2)
    bootstrap = (initial.get("bootstrap") or (None, {}))[0]
    if not bootstrap:
        raise RuntimeError("bootstrap unavailable")

    phase = detect_phase(bootstrap, report_as_of or utcnow())
    checkpoint = resolve_checkpoint(mode, phase.get("deadline_time"), phase.get("is_live_event", False), as_of=report_as_of, simulated=report_as_of is not None)
    submitted_gw, scoring_gw = phase["submitted_gw"], phase["scoring_gw"]

    dependent_specs = []
    if submitted_gw:
        dependent_specs.append(("picks", f"entry/{TEAM_ID}/event/{submitted_gw}/picks/", API_RETRIES))
    if scoring_gw:
        dependent_specs.append(("event_live", f"event/{scoring_gw}/live/", API_RETRIES))
    wave_started = perf_counter()
    dependent = _parallel_official_get(dependent_specs)
    dependent_wave_ms = round((perf_counter() - wave_started) * 1000, 2)

    fetched = {**initial, **dependent}
    payloads = {key: pair[0] for key, pair in fetched.items()}
    health = {key: pair[1] for key, pair in fetched.items()}
    _normalize_endpoint_health(health, payloads, submitted_gw, scoring_gw, bool(phase.get("is_live_event")))

    teams, positions, by_id = maps(bootstrap)
    lock = read_json(CONFIG / "locked_squad.json", {})
    projection_baseline = _projection_baseline_authority(lock, phase)
    use_lock = projection_baseline["override_applied"]
    squad = []
    if use_lock:
        for row in lock.get("players", []):
            player = resolve_locked_player(row, by_id, teams, positions)
            squad.append({
                "element": player["id"],
                "name": player["web_name"],
                "team_id": player["team"],
                "position": positions[player["element_type"]],
                "purchase_cost": row.get("purchase_cost"),
                "source": "locked_squad_element_id",
            })
    else:
        for pick in (payloads.get("picks") or {}).get("picks", []):
            player = by_id.get(pick["element"])
            if player:
                squad.append({
                    "element": player["id"],
                    "name": player["web_name"],
                    "team_id": player["team"],
                    "position": positions[player["element_type"]],
                    "purchase_cost": pick.get("purchase_price"),
                    "selling_price": pick.get("selling_price"),
                    "source": "official_picks",
                })
    _validate_authoritative_squad(squad, by_id)

    spells = build_transfer_spells(payloads.get("transfers") or [])
    need_gw1 = any(row.get("purchase_cost") is None and (spells.get(row["element"]) or {}).get("purchase_cost") is None for row in squad)
    gw1_ids: set[int] = set()
    gw1_ms = 0.0
    if need_gw1:
        wave_started = perf_counter()
        gw1, gw1_health = get_json(f"entry/{TEAM_ID}/event/1/picks/", retries=1)
        gw1_ms = round((perf_counter() - wave_started) * 1000, 2)
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
        ledger.append({
            "element": player["id"],
            "name": player["web_name"],
            "team": teams[player["team"]],
            "team_id": player["team"],
            "position": positions[player["element_type"]],
            "purchase_cost": purchase,
            "now_cost": player["now_cost"],
            "sell_cost": selling,
            "purchase_source": source,
            "ownership": player.get("selected_by_percent"),
            "status": player.get("status"),
        })

    total_ms = round((perf_counter() - started) * 1000, 2)
    out = {
        "schema": "snapshot.v1",
        "schema_version": 492,
        "generated_at": iso_now(),
        "mode": mode,
        "as_of": as_of,
        "checkpoint_context": checkpoint,
        "phase": phase,
        "team_id": TEAM_ID,
        "official": payloads,
        "endpoint_health": health,
        "squad_authority": projection_baseline["effective_authority"],
        "projection_baseline": projection_baseline,
        "squad": squad,
        "team_value_ledger": ledger,
        "itb_tenths": lock.get("itb_tenths") if use_lock else (payloads.get("entry") or {}).get("last_deadline_bank"),
        "gw1_reconstruction_requested": need_gw1,
        "acquisition_timing": {
            "initial_parallel_ms": initial_wave_ms,
            "dependent_parallel_ms": dependent_wave_ms,
            "gw1_conditional_ms": gw1_ms,
            "initial_requests": len(initial_specs),
            "dependent_requests": len(dependent_specs),
            "bootstrap_overlapped_with_independent_official_endpoints": True,
        },
        "duration_ms": total_ms,
    }
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "service": "raw_snapshot",
        "schema": "snapshot.v1",
        "duration_ms": out["duration_ms"],
        "initial_parallel_ms": initial_wave_ms,
        "dependent_parallel_ms": dependent_wave_ms,
        "planning_gw": projection_baseline["planning_gw"],
        "baseline_gw": projection_baseline["baseline_gw"],
        "squad_authority": out["squad_authority"],
        "override_applied": projection_baseline["override_applied"],
    }))
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("daily", "deadline", "live"))
    parser.add_argument("--as-of")
    args = parser.parse_args()
    return run(args.mode, args.as_of)


if __name__ == "__main__":
    cli()
