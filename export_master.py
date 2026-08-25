#!/usr/bin/env python3
"""
Export a single persisted bridge snapshot for FPL Master Monitor.

Output:
    data/latest.json
    data/history.jsonl

This script uses only public FPL endpoints and Team ID 3462711.
"""
import json
import os
from datetime import datetime, timezone

import requests

BASE_URL = "https://fantasy.premierleague.com/api"
TEAM_ID = 3462711
TIMEOUT = 20

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
LATEST = os.path.join(DATA_DIR, "latest.json")
HISTORY = os.path.join(DATA_DIR, "history.jsonl")


def get(path):
    r = requests.get(f"{BASE_URL}/{path.lstrip('/')}", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def safe(path):
    try:
        return get(path), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def money_int(value):
    return value if value is None else int(value)


def detect_event(bootstrap):
    events = bootstrap.get("events", [])
    current = next((e for e in events if e.get("is_current")), None)
    nxt = next((e for e in events if e.get("is_next")), None)
    finished = [e for e in events if e.get("finished")]
    last_finished = max(finished, key=lambda e: e["id"]) if finished else None

    now = datetime.now(timezone.utc)

    if current:
        deadline_raw = current.get("deadline_time")
        deadline = None

        if deadline_raw:
            try:
                deadline = datetime.fromisoformat(
                    deadline_raw.replace("Z", "+00:00")
                )
            except ValueError:
                deadline = None

        if deadline is not None and deadline > now:
            planning = current
        else:
            planning = nxt or current
    else:
        planning = nxt

    return current, nxt, last_finished, planning


def sell_cost(now_cost, purchase_cost):
    if purchase_cost is None:
        return None
    if now_cost <= purchase_cost:
        return now_cost
    return purchase_cost + ((now_cost - purchase_cost) // 2)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    health = {}

    bootstrap, err = safe("bootstrap-static/")
    health["bootstrap"] = {"status": "LIVE" if not err else "FAILED", "error": err}
    if not bootstrap:
        raise RuntimeError(f"bootstrap-static unavailable: {err}")

    fixtures, err = safe("fixtures/")
    health["fixtures"] = {"status": "LIVE" if not err else "FAILED", "error": err}

    event_status, err = safe("event-status/")
    health["event_status"] = {"status": "LIVE" if not err else "FAILED", "error": err}

    entry, err = safe(f"entry/{TEAM_ID}/")
    health["entry"] = {"status": "LIVE" if not err else "FAILED", "error": err}

    history, err = safe(f"entry/{TEAM_ID}/history/")
    health["history"] = {"status": "LIVE" if not err else "FAILED", "error": err}

    transfers, err = safe(f"entry/{TEAM_ID}/transfers/")
    health["transfers"] = {"status": "LIVE" if not err else "FAILED", "error": err}
    transfers = transfers or []

    current, nxt, last_finished, planning = detect_event(bootstrap)
    gw = (current or nxt or last_finished or {}).get("id")

    picks = None
    live = None
    if gw:
        picks, err = safe(f"entry/{TEAM_ID}/event/{gw}/picks/")
        health["picks"] = {
            "status": "LIVE" if not err else "NOT_YET_AVAILABLE",
            "error": err
        }
        live, err = safe(f"event/{gw}/live/")
        if current:
            live_status = "LIVE" if not err else "FAILED"
        else:
            live_status = "IDLE" if not err else "IDLE"
        health["event_live"] = {"status": live_status, "error": err}
    else:
        health["picks"] = {"status": "NOT_YET_AVAILABLE", "error": None}
        health["event_live"] = {"status": "IDLE", "error": None}

    players = {p["id"]: p for p in bootstrap["elements"]}
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    pos = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

    # Public transfer-ledger purchase costs for current ownership spells.
    spells = {}
    for tr in sorted(transfers, key=lambda x: (x.get("event", 0), x.get("time", ""))):
        out_id = tr.get("element_out")
        in_id = tr.get("element_in")
        if out_id in spells:
            spells.pop(out_id, None)
        if in_id is not None:
            spells[in_id] = {
                "purchase_cost": tr.get("element_in_cost"),
                "event": tr.get("event"),
                "time": tr.get("time"),
                "source": "entry/transfers"
            }

    gw1, _ = safe(f"entry/{TEAM_ID}/event/1/picks/")
    gw1_ids = {p["element"] for p in (gw1 or {}).get("picks", [])}

    owned_ids = [p["element"] for p in (picks or {}).get("picks", [])]
    ledger = []
    for pid in owned_ids:
        p = players.get(pid, {})
        purchase = None
        source = "unresolved"

        if pid in spells and spells[pid].get("purchase_cost") is not None:
            purchase = spells[pid]["purchase_cost"]
            source = "entry/transfers element_in_cost"
        elif pid in gw1_ids:
            purchase = p.get("now_cost", 0) - p.get("cost_change_start", 0)
            source = "GW1 continuous reconstruction"

        now_cost = p.get("now_cost")
        ledger.append({
            "element": pid,
            "name": p.get("web_name"),
            "team": teams.get(p.get("team")),
            "position": pos.get(p.get("element_type")),
            "purchase_cost": money_int(purchase),
            "now_cost": money_int(now_cost),
            "sell_cost": sell_cost(now_cost, purchase) if now_cost is not None else None,
            "purchase_source": source,
            "ownership": p.get("selected_by_percent"),
            "status": p.get("status"),
        })

    live_score = None
    if picks and live:
        live_points = {e["id"]: e.get("stats", {}).get("total_points", 0) for e in live.get("elements", [])}
        gross = 0
        detail = []
        for pick in picks.get("picks", []):
            pid = pick["element"]
            mult = pick.get("multiplier", 0)
            raw = live_points.get(pid, 0)
            total = raw * mult
            if mult > 0:
                gross += total
            detail.append({
                "element": pid,
                "name": players.get(pid, {}).get("web_name"),
                "multiplier": mult,
                "captain": pick.get("is_captain"),
                "vice": pick.get("is_vice_captain"),
                "raw_points": raw,
                "multiplied_points": total,
            })
        hit = (picks.get("entry_history") or {}).get("event_transfers_cost", 0)
        live_score = {
            "status": "PROVISIONAL" if current else "RECONCILED_OR_IDLE",
            "gross": gross,
            "hit": hit,
            "net": gross - hit,
            "players": detail,
        }

    chip_ledger = []
    if history:
        for c in history.get("chips", []):
            chip_ledger.append({
                "name": c.get("name"),
                "event": c.get("event"),
                "time": c.get("time"),
            })

    # Full API-first universe, compact fields only.
    universe = []
    for p in bootstrap["elements"]:
        universe.append({
            "element": p["id"],
            "name": p.get("web_name"),
            "team": teams.get(p.get("team")),
            "position": pos.get(p.get("element_type")),
            "now_cost": p.get("now_cost"),
            "ownership": p.get("selected_by_percent"),
            "status": p.get("status"),
            "points": p.get("total_points"),
            "transfers_in_event": p.get("transfers_in_event"),
            "transfers_out_event": p.get("transfers_out_event"),
            "cost_change_start": p.get("cost_change_start"),
            "cost_change_event": p.get("cost_change_event"),
        })

    snapshot = {
        "schema_version": 1,
        "generated_at": ts,
        "team_id": TEAM_ID,
        "phase": {
            "current_gw": current["id"] if current else None,
            "next_gw": nxt["id"] if nxt else None,
            "last_finished_gw": last_finished["id"] if last_finished else None,
            "planning_gw": planning["id"] if planning else None,
            "deadline_time": planning.get("deadline_time") if planning else None,
        },
        "endpoint_health": health,
        "entry": entry,
        "chip_ledger": chip_ledger,
        "picks": picks,
        "team_value_ledger": ledger,
        "live_score": live_score,
        "universe": universe,
        "meta": {
            "fpl_native_fields_authority": "direct public FPL API",
            "live_data_status": "PROVISIONAL" if current else "IDLE/FINAL",
            "sell_value_note": "Exact only when current ownership-spell purchase cost is reconstructable.",
        }
    }

    tmp = LATEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LATEST)

    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "generated_at": ts,
            "team_id": TEAM_ID,
            "phase": snapshot["phase"],
            "entry_summary": {
                "name": (entry or {}).get("name"),
                "summary_overall_points": (entry or {}).get("summary_overall_points"),
                "summary_overall_rank": (entry or {}).get("summary_overall_rank"),
            },
            "chip_ledger": chip_ledger,
            "team_value_ledger": ledger,
            "live_score": live_score,
        }, ensure_ascii=False) + "\n")

    print(f"Wrote {LATEST}")
    print(f"Appended {HISTORY}")


if __name__ == "__main__":
    main()
