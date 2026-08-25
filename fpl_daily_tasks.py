"""
FPL iphoenk Engine - Enhanced Public API Collector
===================================================

Read-only public FPL utility for Team ID 3462711.

Features:
  1. Automatic current/next Gameweek detection
  2. Endpoint health panel
  3. Price change tracker with safe cache semantics
  4. Price momentum heuristic + calibration log
  5. Element-ID resolver
  6. Public purchase-price & sell-value reconstruction
  7. Team-value ledger
  8. Chip state tracker
  9. Personalised live score (RAW / PROVISIONAL)
 10. Persistent per-GW snapshot
 11. Baseline reconciliation helper
 12. Universal API-first player dump / screening base

Install:
    pip install requests

Examples:
    python fpl_daily_tasks.py current-gw
    python fpl_daily_tasks.py health
    python fpl_daily_tasks.py price-check
    python fpl_daily_tasks.py price-predict --top 10
    python fpl_daily_tasks.py team-value
    python fpl_daily_tasks.py chip-state
    python fpl_daily_tasks.py live-score
    python fpl_daily_tasks.py live-score --gw 5
    python fpl_daily_tasks.py snapshot
    python fpl_daily_tasks.py universe --top 30

Notes:
- Public endpoints do not require login.
- my-team/{id}/ and write actions remain private/authenticated.
- Live score is provisional until autosubs, vice-captain fallback, bonus and
  event processing are final.
- Price predictor is a heuristic momentum ranking, NOT an official probability.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE_URL = "https://fantasy.premierleague.com/api"
DEFAULT_TEAM_ID = 3462711
TIMEOUT = 15

HERE = os.path.dirname(os.path.abspath(__file__))
PRICE_CACHE_FILE = os.path.join(HERE, "fpl_price_cache.json")
PREDICTOR_LOG_FILE = os.path.join(HERE, "fpl_price_predict_log.jsonl")
SNAPSHOT_FILE = os.path.join(HERE, "fpl_season_snapshots.jsonl")

# Current authoritative pre-deadline WC lock ledger.
# Values are in FPL integer tenths (£4.5m => 45).
# This is used ONLY when the public transfer ledger cannot yet represent
# the current unsubmitted/active-WC draft ownership spell.
LOCKED_15_PURCHASE_LEDGER = {
    "Tzolakis": 45,
    "Verbruggen": 45,
    "De Cuyper": 45,
    "Calafiori": 55,
    "Kayode": 45,
    "Robinson": 45,
    "Aina": 45,
    "Bruno Fernandes": 120,
    "Ødegaard": 65,
    "Tzolis": 65,
    "Rogers": 75,
    "Sangaré": 55,
    "Haaland": 155,
    "João Pedro": 75,
    "Calvert-Lewin": 60,
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def api_get(path: str) -> Any:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def safe_api_get(path: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return api_get(path), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json_atomic(path: str, payload: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_jsonl(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def money(cost: Optional[int]) -> str:
    if cost is None:
        return "N/A"
    return f"£{cost/10:.1f}m"


def team_maps(bootstrap: Dict[str, Any]) -> Tuple[Dict[int, str], Dict[int, str]]:
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    pos = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    return teams, pos


def player_maps(bootstrap: Dict[str, Any]) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_id = {p["id"]: p for p in bootstrap["elements"]}
    by_name = {}
    for p in bootstrap["elements"]:
        keys = {
            p.get("web_name", ""),
            f'{p.get("first_name","")} {p.get("second_name","")}'.strip(),
            p.get("second_name", ""),
        }
        for k in keys:
            if k:
                by_name[k.casefold()] = p
    return by_id, by_name


# ---------------------------------------------------------------------------
# GW detection
# ---------------------------------------------------------------------------

def detect_gw(bootstrap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    bootstrap = bootstrap or api_get("bootstrap-static/")
    events = bootstrap.get("events", [])
    current = next((e for e in events if e.get("is_current")), None)
    next_ev = next((e for e in events if e.get("is_next")), None)
    finished = [e for e in events if e.get("finished")]

    # During the gap after a GW is finished and before the next deadline,
    # FPL can expose no is_current event. Prefer next event for team planning.
    active_for_planning = current or next_ev
    last_finished = max(finished, key=lambda x: x["id"]) if finished else None

    return {
        "current": current,
        "next": next_ev,
        "planning": active_for_planning,
        "last_finished": last_finished,
    }


def print_current_gw() -> None:
    bootstrap = api_get("bootstrap-static/")
    state = detect_gw(bootstrap)
    print("=== FPL Gameweek State ===")
    for label in ("current", "next", "planning", "last_finished"):
        ev = state[label]
        if not ev:
            print(f"{label:13}: N/A")
            continue
        print(
            f"{label:13}: GW{ev['id']} | {ev['name']} | "
            f"deadline={ev.get('deadline_time')} | finished={ev.get('finished')}"
        )


# ---------------------------------------------------------------------------
# Endpoint health
# ---------------------------------------------------------------------------

def endpoint_health(team_id: int = DEFAULT_TEAM_ID) -> Dict[str, Any]:
    bootstrap, b_err = safe_api_get("bootstrap-static/")
    gw = None
    if bootstrap:
        state = detect_gw(bootstrap)
        ev = state["current"] or state["next"] or state["last_finished"]
        gw = ev["id"] if ev else None

    paths = {
        "bootstrap-static": "bootstrap-static/",
        "fixtures": "fixtures/",
        "entry": f"entry/{team_id}/",
        "history": f"entry/{team_id}/history/",
        "transfers": f"entry/{team_id}/transfers/",
        "event-status": "event-status/",
    }
    if gw:
        paths["picks"] = f"entry/{team_id}/event/{gw}/picks/"
        paths["event-live"] = f"event/{gw}/live/"

    results = {}
    if b_err:
        results["bootstrap-static"] = {"status": "FAILED", "error": b_err, "refreshed": now_iso()}
    else:
        results["bootstrap-static"] = {"status": "LIVE", "error": None, "refreshed": now_iso()}

    for name, path in paths.items():
        if name == "bootstrap-static":
            continue
        data, err = safe_api_get(path)
        if err:
            status = "NOT YET AVAILABLE" if name == "picks" else "FAILED"
            if name == "event-live" and gw and bootstrap:
                ev = next((e for e in bootstrap["events"] if e["id"] == gw), None)
                if ev and not ev.get("is_current"):
                    status = "IDLE"
            results[name] = {"status": status, "error": err, "refreshed": now_iso()}
        else:
            status = "LIVE"
            if name == "event-live" and gw and bootstrap:
                ev = next((e for e in bootstrap["events"] if e["id"] == gw), None)
                if ev and not ev.get("is_current"):
                    status = "IDLE"
            results[name] = {"status": status, "error": None, "refreshed": now_iso()}

    results["_gw"] = gw
    return results


def print_endpoint_health(team_id: int = DEFAULT_TEAM_ID) -> None:
    results = endpoint_health(team_id)
    print(f"=== Endpoint Health | Team {team_id} | GW={results.get('_gw')} ===")
    for name, row in results.items():
        if name.startswith("_"):
            continue
        msg = f"{name:16}: {row['status']:18} | {row['refreshed']}"
        if row["error"]:
            msg += f" | {row['error']}"
        print(msg)


# ---------------------------------------------------------------------------
# Price tracker
# ---------------------------------------------------------------------------

def price_check() -> None:
    bootstrap = api_get("bootstrap-static/")
    players = bootstrap["elements"]
    current = {
        str(p["id"]): {
            "now_cost": p["now_cost"],
            "selected_by_percent": p.get("selected_by_percent"),
            "transfers_in_event": p.get("transfers_in_event", 0),
            "transfers_out_event": p.get("transfers_out_event", 0),
            "status": p.get("status"),
            "web_name": p.get("web_name"),
        }
        for p in players
    }

    previous = read_json(PRICE_CACHE_FILE, {})
    if not previous:
        write_json_atomic(PRICE_CACHE_FILE, {"timestamp": now_iso(), "players": current})
        print("BASELINE CREATED: belum ada snapshot sebelumnya; tidak ada price change yang boleh disimpulkan.")
        return

    prev_players = previous.get("players", previous)  # backwards-compatible with old cache
    changes = []
    for pid, cur in current.items():
        prev = prev_players.get(pid)
        if prev is None:
            continue
        old_cost = prev["now_cost"] if isinstance(prev, dict) else prev
        if old_cost != cur["now_cost"]:
            changes.append((cur["web_name"], old_cost, cur["now_cost"]))

    if not changes:
        print("NO CONFIRMED PRICE CHANGE sejak snapshot terakhir.")
    else:
        print(f"CONFIRMED PRICE CHANGES: {len(changes)}")
        for name, old, new in sorted(changes, key=lambda x: abs(x[2]-x[1]), reverse=True):
            delta = new - old
            arrow = "↑" if delta > 0 else "↓"
            print(f"  {name:20} {money(old)} -> {money(new)} {arrow}{abs(delta)/10:.1f}")

    write_json_atomic(PRICE_CACHE_FILE, {"timestamp": now_iso(), "players": current})


# ---------------------------------------------------------------------------
# Price predictor heuristic + calibration logging
# ---------------------------------------------------------------------------

def price_predictions(top_n: int = 10, min_owners: int = 1000) -> None:
    data = api_get("bootstrap-static/")
    total_players = data["total_players"]
    candidates = []

    for p in data["elements"]:
        if p.get("cost_change_event", 0) != 0:
            continue
        pct = p.get("selected_by_percent")
        owners = (float(pct) / 100 * total_players) if pct else 0
        if owners < min_owners:
            continue
        net = p.get("transfers_in_event", 0) - p.get("transfers_out_event", 0)
        momentum = net / owners if owners else 0.0
        candidates.append({
            "id": p["id"],
            "name": p["web_name"],
            "price": p["now_cost"],
            "owners": int(owners),
            "net": net,
            "momentum": momentum,
        })

    risers = sorted(candidates, key=lambda x: x["momentum"], reverse=True)[:top_n]
    fallers = sorted(candidates, key=lambda x: x["momentum"])[:top_n]

    print("=== BUY PRESSURE | HEURISTIC ONLY ===")
    for c in risers:
        print(f"{c['name']:20} {money(c['price'])} | net {c['net']:+,} | owners ~{c['owners']:,} | momentum {c['momentum']:.5f}")

    print("\n=== SELL PRESSURE | HEURISTIC ONLY ===")
    for c in fallers:
        print(f"{c['name']:20} {money(c['price'])} | net {c['net']:+,} | owners ~{c['owners']:,} | momentum {c['momentum']:.5f}")

    append_jsonl(PREDICTOR_LOG_FILE, {
        "timestamp": now_iso(),
        "total_players": total_players,
        "top_risers": risers,
        "top_fallers": fallers,
    })


def price_predict_calibration() -> None:
    if not os.path.exists(PREDICTOR_LOG_FILE):
        print("Belum ada predictor log. Jalankan price-predict beberapa hari dulu.")
        return

    current = api_get("bootstrap-static/")
    by_id = {p["id"]: p for p in current["elements"]}

    logs = []
    with open(PREDICTOR_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                logs.append(json.loads(line))
            except Exception:
                pass

    if not logs:
        print("Predictor log kosong.")
        return

    # Simple retrospective: compare logged price with current price.
    # This is not a perfect next-day calibration unless run daily, but is useful.
    samples = []
    for log in logs:
        for direction, key in (("rise", "top_risers"), ("fall", "top_fallers")):
            for row in log.get(key, []):
                p = by_id.get(row["id"])
                if not p:
                    continue
                moved = p["now_cost"] - row["price"]
                hit = moved > 0 if direction == "rise" else moved < 0
                samples.append((direction, hit, row["momentum"], row["owners"]))

    if not samples:
        print("Belum cukup data untuk calibration.")
        return

    for direction in ("rise", "fall"):
        subset = [s for s in samples if s[0] == direction]
        hits = sum(1 for s in subset if s[1])
        rate = hits / len(subset) if subset else 0
        print(f"{direction.upper():5}: {hits}/{len(subset)} hit | crude hit-rate {rate:.1%}")
    print("Catatan: ini crude calibration sejak timestamp log sampai sekarang, bukan exact next-day probability.")


# ---------------------------------------------------------------------------
# Transfer history / purchase price / sell value
# ---------------------------------------------------------------------------

def sell_cost_from_purchase(now_cost: int, purchase_cost: int) -> int:
    """Exact FPL sell-price formula in integer tenths."""
    if now_cost <= purchase_cost:
        return now_cost
    profit = now_cost - purchase_cost
    return purchase_cost + (profit // 2)


def fetch_transfer_history(team_id: int) -> List[Dict[str, Any]]:
    data = api_get(f"entry/{team_id}/transfers/")
    return data if isinstance(data, list) else []


def latest_submitted_gw(team_id: int, bootstrap: Dict[str, Any]) -> Optional[int]:
    state = detect_gw(bootstrap)
    candidates = []
    if state["current"]:
        candidates.append(state["current"]["id"])
    if state["last_finished"]:
        candidates.append(state["last_finished"]["id"])
    if state["next"]:
        candidates.append(state["next"]["id"])
    for gw in sorted(set(candidates), reverse=True):
        data, err = safe_api_get(f"entry/{team_id}/event/{gw}/picks/")
        if not err and data and data.get("picks"):
            return gw
    return None


def get_current_public_owned_ids(team_id: int, bootstrap: Dict[str, Any]) -> Tuple[Optional[int], List[int]]:
    gw = latest_submitted_gw(team_id, bootstrap)
    if gw is None:
        return None, []
    picks = api_get(f"entry/{team_id}/event/{gw}/picks/")
    return gw, [p["element"] for p in picks.get("picks", [])]


def build_transfer_spells(transfers: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """
    Returns latest permanent-looking purchase record per element_in.
    This is deliberately conservative: transfer history is chronological and the
    latest element_in record wins. Free Hit ambiguity is handled later using chip
    state; pre-deadline active-WC draft can require lock-ledger fallback.
    """
    spells: Dict[int, Dict[str, Any]] = {}
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
                "source": "entry/transfers element_in_cost",
            }
    return spells


def original_gw1_ids(team_id: int) -> List[int]:
    data, err = safe_api_get(f"entry/{team_id}/event/1/picks/")
    if err or not data:
        return []
    return [p["element"] for p in data.get("picks", [])]


def resolve_locked_purchase_by_name(player: Dict[str, Any]) -> Optional[int]:
    candidates = [
        player.get("web_name", ""),
        f'{player.get("first_name","")} {player.get("second_name","")}'.strip(),
        player.get("second_name", ""),
    ]
    for name in candidates:
        if name in LOCKED_15_PURCHASE_LEDGER:
            return LOCKED_15_PURCHASE_LEDGER[name]
    # tolerant special cases
    for lock_name, cost in LOCKED_15_PURCHASE_LEDGER.items():
        for name in candidates:
            if name and (name.casefold() in lock_name.casefold() or lock_name.casefold() in name.casefold()):
                return cost
    return None


def reconstruct_purchase_cost(
    player: Dict[str, Any],
    current_public_owned: bool,
    gw1_ids: set,
    spells: Dict[int, Dict[str, Any]],
    allow_lock_fallback: bool = True,
) -> Tuple[Optional[int], str, str]:
    pid = player["id"]

    if pid in spells and spells[pid].get("purchase_cost") is not None:
        return spells[pid]["purchase_cost"], spells[pid]["source"], "HIGH"

    if pid in gw1_ids and current_public_owned:
        # Accurate only for a player continuously owned from GW1.
        # If he was sold/rebought, a current spell would normally exist in transfers.
        start_cost = player["now_cost"] - player.get("cost_change_start", 0)
        return start_cost, "GW1 continuous: now_cost - cost_change_start", "HIGH"

    if allow_lock_fallback:
        lock_cost = resolve_locked_purchase_by_name(player)
        if lock_cost is not None:
            return lock_cost, "authoritative pre-deadline LOCK ledger", "MEDIUM-HIGH"

    return None, "unresolved", "LOW"


def team_value_ledger(team_id: int = DEFAULT_TEAM_ID) -> List[Dict[str, Any]]:
    bootstrap = api_get("bootstrap-static/")
    by_id, _ = player_maps(bootstrap)
    teams, pos = team_maps(bootstrap)

    submitted_gw, owned_ids = get_current_public_owned_ids(team_id, bootstrap)
    owned_set = set(owned_ids)
    gw1_set = set(original_gw1_ids(team_id))
    transfers = fetch_transfer_history(team_id)
    spells = build_transfer_spells(transfers)

    # If current public picks are previous-GW and user has an active pre-deadline WC,
    # also surface players from authoritative lock ledger.
    lock_ids = []
    for p in bootstrap["elements"]:
        if resolve_locked_purchase_by_name(p) is not None:
            lock_ids.append(p["id"])

    candidate_ids = sorted(set(owned_ids) | set(lock_ids))
    ledger = []

    for pid in candidate_ids:
        p = by_id.get(pid)
        if not p:
            continue
        public_owned = pid in owned_set
        purchase, source, confidence = reconstruct_purchase_cost(
            p, public_owned, gw1_set, spells, allow_lock_fallback=True
        )
        sell = sell_cost_from_purchase(p["now_cost"], purchase) if purchase is not None else None
        embedded = (p["now_cost"] - purchase) if purchase is not None else None

        ledger.append({
            "id": pid,
            "name": p["web_name"],
            "team": teams.get(p["team"], str(p["team"])),
            "position": pos.get(p["element_type"], str(p["element_type"])),
            "public_owned_in_latest_picks": public_owned,
            "submitted_gw": submitted_gw,
            "purchase_cost": purchase,
            "now_cost": p["now_cost"],
            "sell_cost": sell,
            "embedded_market_gain": embedded,
            "purchase_source": source,
            "confidence": confidence,
        })

    return ledger


def print_team_value_ledger(team_id: int = DEFAULT_TEAM_ID) -> None:
    rows = team_value_ledger(team_id)
    print(f"=== Team-Value Ledger | Team {team_id} ===")
    print("Note: pre-deadline active-WC lock players may use authoritative lock-ledger fallback.")
    total_market = total_sell = 0
    for r in rows:
        total_market += r["now_cost"]
        if r["sell_cost"] is not None:
            total_sell += r["sell_cost"]
        owned_tag = "PUBLIC" if r["public_owned_in_latest_picks"] else "LOCK"
        print(
            f"{r['position']:3} {r['name']:20} {r['team'][:12]:12} "
            f"buy {money(r['purchase_cost']):7} | now {money(r['now_cost']):7} | "
            f"sell {money(r['sell_cost']):7} | src={r['purchase_source']} | "
            f"{owned_tag} | conf={r['confidence']}"
        )
    print(f"Market value of displayed ledger: {money(total_market)}")
    print(f"Reconstructed sell value:          {money(total_sell)}")


# ---------------------------------------------------------------------------
# Chip tracker
# ---------------------------------------------------------------------------

def chip_state(team_id: int = DEFAULT_TEAM_ID) -> Dict[str, Any]:
    history = api_get(f"entry/{team_id}/history/")
    chips = history.get("chips", [])
    used = [{"name": c.get("name"), "event": c.get("event"), "time": c.get("time")} for c in chips]

    # FPL chip names can change across seasons; do not hard-code "remaining"
    # beyond known chips unless exposed. We provide observed-used ledger.
    return {
        "team_id": team_id,
        "used": used,
        "note": "Remaining chips depend on current-season rules; derive only from known rule-set + observed used chips.",
    }


def print_chip_state(team_id: int = DEFAULT_TEAM_ID) -> None:
    state = chip_state(team_id)
    print(f"=== Chip State | Team {team_id} ===")
    if not state["used"]:
        print("No used-chip record exposed yet.")
    for c in state["used"]:
        print(f"  {c['name']}: GW{c['event']} | {c.get('time')}")
    print(state["note"])


# ---------------------------------------------------------------------------
# Live score
# ---------------------------------------------------------------------------

def live_score(team_id: int = DEFAULT_TEAM_ID, gw: Optional[int] = None) -> None:
    bootstrap = api_get("bootstrap-static/")
    if gw is None:
        state = detect_gw(bootstrap)
        ev = state["current"] or state["planning"] or state["last_finished"]
        if not ev:
            raise RuntimeError("Tidak bisa menentukan Gameweek otomatis.")
        gw = ev["id"]

    picks = api_get(f"entry/{team_id}/event/{gw}/picks/")
    live = api_get(f"event/{gw}/live/")
    status, _ = safe_api_get("event-status/")

    by_id, _ = player_maps(bootstrap)
    points_by_id = {el["id"]: el["stats"].get("total_points", 0) for el in live.get("elements", [])}

    raw_total = 0
    print(f"=== RAW LIVE SCORE | Team {team_id} | GW{gw} ===")
    for pick in picks.get("picks", []):
        pid = pick["element"]
        mult = pick.get("multiplier", 0)
        p = by_id.get(pid, {})
        name = p.get("web_name", str(pid))
        raw = points_by_id.get(pid, 0)
        pts = raw * mult
        if mult > 0:
            raw_total += pts

        tags = []
        if pick.get("is_captain"):
            tags.append("C")
        if pick.get("is_vice_captain"):
            tags.append("VC")
        if mult == 0:
            tags.append("BENCH")
        tag = f" ({','.join(tags)})" if tags else ""
        print(f"{name:20}{tag:12} raw={raw:2} x{mult} => {pts:2}")

    entry_hist = picks.get("entry_history", {})
    hit = entry_hist.get("event_transfers_cost", 0)
    net = raw_total - hit

    bonus_added = None
    if status:
        stat = status.get("status", [])
        if stat:
            bonus_added = all(s.get("bonus_added") for s in stat)

    print(f"\nRAW LIVE gross points : {raw_total}")
    print(f"Transfer cost / hit   : -{hit}")
    print(f"RAW LIVE net points   : {net}")
    print(f"Bonus processing final: {bonus_added if bonus_added is not None else 'N/A'}")
    print("Status                 : PROVISIONAL until autosubs/VC/bonus/event processing reconcile.")


# ---------------------------------------------------------------------------
# Baseline reconciliation + snapshot
# ---------------------------------------------------------------------------

def baseline_reconcile(team_id: int = DEFAULT_TEAM_ID, gw: Optional[int] = None) -> Dict[str, Any]:
    bootstrap = api_get("bootstrap-static/")
    if gw is None:
        submitted = latest_submitted_gw(team_id, bootstrap)
        if submitted is None:
            return {"status": "NOT YET AVAILABLE", "gw": None}
        gw = submitted

    picks = api_get(f"entry/{team_id}/event/{gw}/picks/")
    by_id, _ = player_maps(bootstrap)

    submitted_names = [by_id.get(p["element"], {}).get("web_name", str(p["element"])) for p in picks["picks"]]
    locked_names = list(LOCKED_15_PURCHASE_LEDGER.keys())

    def norm(s: str) -> str:
        return s.casefold().replace("-", "").replace(" ", "")

    sub_norm = {norm(x): x for x in submitted_names}
    lock_norm = {norm(x): x for x in locked_names}

    missing_from_submitted = [name for key, name in lock_norm.items() if key not in sub_norm]
    extra_in_submitted = [name for key, name in sub_norm.items() if key not in lock_norm]

    cap = next((p for p in picks["picks"] if p.get("is_captain")), None)
    vice = next((p for p in picks["picks"] if p.get("is_vice_captain")), None)

    return {
        "status": "MATCH" if not missing_from_submitted and not extra_in_submitted else "DIFF",
        "gw": gw,
        "submitted": submitted_names,
        "missing_from_submitted_vs_lock": missing_from_submitted,
        "extra_in_submitted_vs_lock": extra_in_submitted,
        "captain": by_id.get(cap["element"], {}).get("web_name") if cap else None,
        "vice": by_id.get(vice["element"], {}).get("web_name") if vice else None,
        "active_chip": picks.get("active_chip"),
    }


def print_baseline_reconcile(team_id: int = DEFAULT_TEAM_ID, gw: Optional[int] = None) -> None:
    r = baseline_reconcile(team_id, gw)
    print(f"=== Baseline Reconciliation | {r['status']} | GW={r.get('gw')} ===")
    if r["status"] == "NOT YET AVAILABLE":
        return
    print(f"Captain: {r['captain']} | Vice: {r['vice']} | Chip: {r['active_chip']}")
    print(f"Missing vs LOCK: {r['missing_from_submitted_vs_lock']}")
    print(f"Extra vs LOCK  : {r['extra_in_submitted_vs_lock']}")


def snapshot(team_id: int = DEFAULT_TEAM_ID, gw: Optional[int] = None) -> None:
    bootstrap = api_get("bootstrap-static/")
    if gw is None:
        submitted = latest_submitted_gw(team_id, bootstrap)
        if submitted is None:
            raise RuntimeError("Belum ada submitted picks yang bisa di-snapshot.")
        gw = submitted

    entry = api_get(f"entry/{team_id}/")
    picks = api_get(f"entry/{team_id}/event/{gw}/picks/")
    by_id, _ = player_maps(bootstrap)

    payload = {
        "timestamp": now_iso(),
        "team_id": team_id,
        "gw": gw,
        "entry": entry,
        "entry_history": picks.get("entry_history"),
        "active_chip": picks.get("active_chip"),
        "automatic_subs": picks.get("automatic_subs", []),
        "picks": [
            {
                **p,
                "name": by_id.get(p["element"], {}).get("web_name", str(p["element"])),
            }
            for p in picks.get("picks", [])
        ],
        "team_value_ledger": team_value_ledger(team_id),
    }
    append_jsonl(SNAPSHOT_FILE, payload)
    print(f"Snapshot GW{gw} appended to {SNAPSHOT_FILE}")


# ---------------------------------------------------------------------------
# API-first universe
# ---------------------------------------------------------------------------

def universe(top_n: int = 30) -> None:
    bootstrap = api_get("bootstrap-static/")
    teams, pos = team_maps(bootstrap)
    rows = []
    for p in bootstrap["elements"]:
        rows.append({
            "id": p["id"],
            "name": p["web_name"],
            "team": teams.get(p["team"], str(p["team"])),
            "pos": pos.get(p["element_type"], str(p["element_type"])),
            "price": p["now_cost"],
            "ownership": float(p.get("selected_by_percent") or 0),
            "points": p.get("total_points", 0),
            "transfers_in_event": p.get("transfers_in_event", 0),
            "transfers_out_event": p.get("transfers_out_event", 0),
            "status": p.get("status"),
        })

    # This is intentionally only an API-first ingestion view, not DSS ranking.
    rows = sorted(rows, key=lambda r: (r["points"], r["ownership"]), reverse=True)[:top_n]
    print(f"=== API-FIRST UNIVERSE SAMPLE | top {top_n} by current points ===")
    for r in rows:
        print(
            f"{r['pos']:3} {r['name']:20} {r['team'][:14]:14} {money(r['price']):7} "
            f"pts={r['points']:3} own={r['ownership']:5.1f}% status={r['status']}"
        )
    print("Note: this is ingestion only. Final watchlist must run full DSS + tactical/news overlays.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="FPL iphoenk Enhanced Public API Engine")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("current-gw", help="Auto-detect current/next Gameweek")
    sub.add_parser("health", help="Endpoint health panel")
    sub.add_parser("price-check", help="Confirmed price changes vs previous local snapshot")

    pp = sub.add_parser("price-predict", help="Heuristic transfer-momentum ranking")
    pp.add_argument("--top", type=int, default=10)
    pp.add_argument("--min-owners", type=int, default=1000)

    sub.add_parser("price-calibration", help="Crude retrospective calibration of local price heuristic")

    tv = sub.add_parser("team-value", help="Reconstruct purchase/sell values and print team-value ledger")
    tv.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID)

    cs = sub.add_parser("chip-state", help="Show used chip ledger from public history")
    cs.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID)

    ls = sub.add_parser("live-score", help="Personalised raw/provisional live score")
    ls.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID)
    ls.add_argument("--gw", type=int, default=None, help="Optional; auto-detected when omitted")

    br = sub.add_parser("reconcile", help="Compare latest submitted picks vs authoritative locked 15")
    br.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID)
    br.add_argument("--gw", type=int, default=None)

    sn = sub.add_parser("snapshot", help="Append current submitted GW snapshot to local JSONL")
    sn.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID)
    sn.add_argument("--gw", type=int, default=None)

    uv = sub.add_parser("universe", help="Dump API-first player universe sample")
    uv.add_argument("--top", type=int, default=30)

    args = parser.parse_args()

    try:
        if args.command == "current-gw":
            print_current_gw()
        elif args.command == "health":
            print_endpoint_health(DEFAULT_TEAM_ID)
        elif args.command == "price-check":
            price_check()
        elif args.command == "price-predict":
            price_predictions(args.top, args.min_owners)
        elif args.command == "price-calibration":
            price_predict_calibration()
        elif args.command == "team-value":
            print_team_value_ledger(args.team_id)
        elif args.command == "chip-state":
            print_chip_state(args.team_id)
        elif args.command == "live-score":
            live_score(args.team_id, args.gw)
        elif args.command == "reconcile":
            print_baseline_reconcile(args.team_id, args.gw)
        elif args.command == "snapshot":
            snapshot(args.team_id, args.gw)
        elif args.command == "universe":
            universe(args.top)
    except requests.HTTPError as exc:
        print(f"API HTTP ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
    except requests.RequestException as exc:
        print(f"API NETWORK ERROR: {exc}", file=sys.stderr)
        sys.exit(3)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
