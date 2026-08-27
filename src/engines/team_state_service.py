from __future__ import annotations

import json
from typing import Any

from src.engines.base_state import bootstrap_maps, native_entry_summary, resolve_locked_player
from src.engines.team_value import build_transfer_spells, sell_cost
from src.rules import SQUAD_RULES, build_chip_ledger, ruleset_metadata
from src.settings import FAIL_CLOSED, TEAM_ID
from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json

OFFICIAL = DATA / "official_snapshot.json"
TEAM_OUT = DATA / "team.json"
CHIPS_OUT = DATA / "chips.json"


def _validate_squad(squad: list[dict[str, Any]], by_id: dict[int, dict[str, Any]], teams: dict[int, str]) -> None:
    expected_size = int(SQUAD_RULES["squad_size"])
    expected_counts = {str(key): int(value) for key, value in dict(SQUAD_RULES["position_counts"]).items()}
    if len(squad) != expected_size:
        raise RuntimeError(f"FAIL CLOSED: squad count {len(squad)} expected {expected_size}")
    counts = {position: sum(1 for row in squad if row["position"] == position) for position in expected_counts}
    if counts != expected_counts:
        raise RuntimeError(f"FAIL CLOSED: position counts {counts} expected {expected_counts}")
    ids = [int(row["element"]) for row in squad]
    if len(ids) != len(set(ids)):
        raise RuntimeError("FAIL CLOSED: duplicate player in squad")
    club_counts: dict[str, int] = {}
    for row in squad:
        player = by_id[int(row["element"])]
        club = teams[int(player["team"])]
        club_counts[club] = club_counts.get(club, 0) + 1
    limit = int(SQUAD_RULES["max_players_per_club"])
    if max(club_counts.values(), default=0) > limit:
        raise RuntimeError(f"FAIL CLOSED: club limit exceeded {club_counts}; max={limit}")


def run() -> dict[str, Any]:
    official = read_json(OFFICIAL, {})
    bootstrap = official.get("bootstrap") or {}
    if not bootstrap:
        raise RuntimeError("official_snapshot missing bootstrap")
    phase = official.get("phase") or {}
    teams, positions, by_id = bootstrap_maps(bootstrap)
    entry = official.get("entry") or {}
    history = official.get("history") or {}
    transfers = list(official.get("transfers") or [])
    picks = official.get("picks") or {}
    health = official.get("endpoint_health") or {}

    lock = read_json(CONFIG / "locked_squad.json", {})
    use_lock = bool(lock.get("wildcard_active")) and phase.get("planning_gw") != phase.get("submitted_gw")
    squad: list[dict[str, Any]] = []
    if use_lock:
        seen: set[int] = set()
        for row in lock.get("players") or []:
            player = resolve_locked_player(row, by_id, teams, positions)
            element = int(player["id"])
            if element in seen:
                raise RuntimeError(f"FAIL CLOSED: duplicate locked element ID {element}")
            seen.add(element)
            squad.append({
                "element": element,
                "name": player["web_name"],
                "position": positions[player["element_type"]],
                "purchase_cost": row.get("purchase_cost"),
                "source": "locked_squad_element_id",
            })
    elif picks:
        for pick in picks.get("picks") or []:
            player = by_id.get(int(pick["element"]))
            if player:
                squad.append({
                    "element": int(player["id"]),
                    "name": player["web_name"],
                    "position": positions[player["element_type"]],
                    "source": "official_picks",
                })

    if FAIL_CLOSED:
        _validate_squad(squad, by_id, teams)

    spells = build_transfer_spells(transfers)
    baseline = official.get("purchase_baseline") or {}
    baseline_gw = int(baseline.get("gw") or 1)
    baseline_ids = {int(row["element"]) for row in ((baseline.get("picks") or {}).get("picks") or [])}
    ledger: list[dict[str, Any]] = []
    for row in squad:
        player = by_id[int(row["element"])]
        purchase = row.get("purchase_cost")
        purchase_source = row.get("source")
        if purchase is None:
            spell = spells.get(int(player["id"])) or {}
            if spell.get("purchase_cost") is not None:
                purchase = spell["purchase_cost"]
                purchase_source = "entry/transfers"
            elif int(player["id"]) in baseline_ids:
                purchase = int(player["now_cost"]) - int(player.get("cost_change_start") or 0)
                purchase_source = f"gw{baseline_gw}_reconstruction"
        ledger.append({
            "element": int(player["id"]),
            "name": player["web_name"],
            "team": teams[int(player["team"])],
            "position": positions[player["element_type"]],
            "purchase_cost": purchase,
            "now_cost": int(player["now_cost"]),
            "sell_cost": sell_cost(int(player["now_cost"]), purchase) if purchase is not None else None,
            "purchase_source": purchase_source,
            "ownership": player.get("selected_by_percent"),
            "status": player.get("status"),
        })

    fetched_at = (health.get("entry") or {}).get("fetched_at")
    entry_summary = native_entry_summary(entry, fetched_at)
    used_chips = list(history.get("chips") or [])
    planning_gw = phase.get("planning_gw") or phase.get("current_gw")
    chip_ledger = build_chip_ledger(used_chips, planning_gw)
    ruleset = ruleset_metadata()
    itb = lock.get("itb_tenths") if use_lock else entry.get("last_deadline_bank")
    totals = {
        "market_value": sum(int(row["now_cost"]) for row in ledger),
        "sell_value": sum(int(row["sell_cost"]) for row in ledger if row.get("sell_cost") is not None),
        "itb": itb,
    }
    authority = "LOCKED_PRE_DEADLINE" if use_lock else "OFFICIAL_SUBMITTED"
    generated_at = iso_now()
    team = {
        "generated_at": generated_at,
        "team_id": TEAM_ID,
        "entry": entry_summary,
        "squad_authority": authority,
        "squad": squad,
        "team_value_ledger": ledger,
        "totals": totals,
        "governance": {
            "ruleset_id": ruleset["id"],
            "sell_value_formula_owned_by_team_value_engine": True,
            "squad_identity_is_element_id_authoritative": True,
        },
    }
    chips = {
        "generated_at": generated_at,
        "used": used_chips,
        "ledger": chip_ledger,
        "ruleset_id": ruleset["id"],
    }
    atomic_json(TEAM_OUT, team)
    atomic_json(CHIPS_OUT, chips)
    return team


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "team_id": out.get("team_id"),
        "squad_authority": out.get("squad_authority"),
        "players": len(out.get("team_value_ledger") or []),
        "totals": out.get("totals"),
    }, ensure_ascii=False))
