from __future__ import annotations

import json

from src.engines.base_state import bootstrap_maps
from src.settings import PRICE_PRESSURE_LIST_SIZE
from src.utils import DATA, atomic_json, iso_now, read_json

OFFICIAL = DATA / "official_snapshot.json"
CACHE_OUT = DATA / "price_cache.json"
MARKET_PRICES_OUT = DATA / "market_prices.json"
UNIVERSE_OUT = DATA / "universe.json"


def run() -> dict:
    official = read_json(OFFICIAL, {})
    bootstrap = official.get("bootstrap") or {}
    if not bootstrap:
        raise RuntimeError("official_snapshot missing bootstrap")
    teams, positions, _ = bootstrap_maps(bootstrap)
    previous = read_json(CACHE_OUT, {}).get("players") or {}
    current: dict[str, dict] = {}
    confirmed: list[dict] = []
    momentum: list[dict] = []
    total_players = int(bootstrap.get("total_players") or 0)
    universe: list[dict] = []

    for player in bootstrap.get("elements") or []:
        element = int(player["id"])
        now_cost = int(player["now_cost"])
        ownership = float(player.get("selected_by_percent") or 0)
        current[str(element)] = {"now_cost": now_cost, "ownership": player.get("selected_by_percent")}
        old = previous.get(str(element)) or {}
        if old.get("now_cost") is not None and int(old["now_cost"]) != now_cost:
            confirmed.append({
                "element": element,
                "name": player["web_name"],
                "previous": int(old["now_cost"]),
                "current": now_cost,
                "delta": now_cost - int(old["now_cost"]),
            })
        estimated_owners = max(1, int(total_players * ownership / 100.0))
        net = int(player.get("transfers_in_event") or 0) - int(player.get("transfers_out_event") or 0)
        momentum.append({
            "element": element,
            "name": player["web_name"],
            "net_transfers": net,
            "ownership_pct": ownership,
            "momentum": net / estimated_owners,
        })
        universe.append({
            "element": element,
            "name": player["web_name"],
            "team": teams[int(player["team"])],
            "team_id": int(player["team"]),
            "position": positions[player["element_type"]],
            "element_type": int(player["element_type"]),
            "now_cost": now_cost,
            "ownership": player.get("selected_by_percent"),
            "status": player.get("status"),
            "points": player.get("total_points"),
            "minutes": player.get("minutes"),
            "transfers_in_event": player.get("transfers_in_event"),
            "transfers_out_event": player.get("transfers_out_event"),
        })

    momentum.sort(key=lambda row: float(row["momentum"]), reverse=True)
    generated_at = iso_now()
    market_prices = {
        "generated_at": generated_at,
        "contract": "MARKET_PRICE_FACTS_V1",
        "authority": "Official FPL snapshot",
        "confirmed_changes": confirmed,
        "top_buy_pressure": momentum[:PRICE_PRESSURE_LIST_SIZE],
        "top_sell_pressure": list(reversed(momentum[-PRICE_PRESSURE_LIST_SIZE:])),
    }
    atomic_json(CACHE_OUT, {"generated_at": generated_at, "players": current})
    atomic_json(MARKET_PRICES_OUT, market_prices)
    atomic_json(UNIVERSE_OUT, {"generated_at": generated_at, "players": universe})
    return {
        "generated_at": generated_at,
        "confirmed_changes": len(confirmed),
        "universe_players": len(universe),
        "top_buy_pressure": len(market_prices["top_buy_pressure"]),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
