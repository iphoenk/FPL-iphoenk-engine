from __future__ import annotations

import json
from typing import Any

from src.engines.base_state import bootstrap_maps
from src.settings import PRICE_PRESSURE_LIST_SIZE
from src.utils import DATA, atomic_json, iso_now, read_json

OFFICIAL = DATA / "official_snapshot.json"
CACHE_OUT = DATA / "price_cache.json"
PRICES_OUT = DATA / "prices.json"
UNIVERSE_OUT = DATA / "universe.json"

PREDICTOR_RAW_FIELDS = (
    "id",
    "first_name",
    "second_name",
    "web_name",
    "team",
    "element_type",
    "now_cost",
    "selected_by_percent",
    "transfers_in",
    "transfers_in_event",
    "transfers_out",
    "transfers_out_event",
    "price_change_percent",
    "price_change_hourly_rate",
    "price_change_projections",
    "price_change_locked_until",
    "price_change_calibrating",
)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _predictor_raw(player: dict[str, Any]) -> dict[str, Any]:
    # Preserve the Official acquisition names exactly and omit truly absent keys.
    # This lets the governed adapter distinguish FIELD_MISSING from a real null/zero.
    return {key: player[key] for key in PREDICTOR_RAW_FIELDS if key in player}


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
    universe: list[dict] = []
    predictor_raw: list[dict[str, Any]] = []
    total_players = _optional_int(bootstrap.get("total_players"))

    for player in bootstrap.get("elements") or []:
        predictor_raw.append(_predictor_raw(player))
        element = int(player["id"])
        now_cost = int(player["now_cost"])
        ownership = _optional_float(player.get("selected_by_percent"))
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

        transfers_in_event = _optional_int(player.get("transfers_in_event"))
        transfers_out_event = _optional_int(player.get("transfers_out_event"))
        net = (
            transfers_in_event - transfers_out_event
            if transfers_in_event is not None and transfers_out_event is not None
            else None
        )
        estimated_owners = None
        if total_players is not None and ownership is not None:
            estimated_owners = max(1, int(total_players * ownership / 100.0))
        momentum_value = net / estimated_owners if net is not None and estimated_owners is not None else None
        momentum.append({
            "element": element,
            "name": player["web_name"],
            "net_transfers": net,
            "ownership_pct": ownership,
            "momentum": momentum_value,
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

    momentum.sort(key=lambda row: float(row["momentum"]) if row.get("momentum") is not None else float("-inf"), reverse=True)
    generated_at = iso_now()
    bootstrap_health = (official.get("endpoint_health") or {}).get("bootstrap") or {}
    prices = {
        "generated_at": generated_at,
        "confirmed_changes": confirmed,
        "top_buy_pressure": momentum[:PRICE_PRESSURE_LIST_SIZE],
        "top_sell_pressure": list(reversed(momentum[-PRICE_PRESSURE_LIST_SIZE:])),
        "official_predictor_raw": predictor_raw,
        "official_predictor_observed_at": bootstrap_health.get("fetched_at") or official.get("generated_at"),
        "official_predictor_transport_health": bootstrap_health,
        "official_element_types": bootstrap.get("element_types") or [],
        "official_price_fields": {
            "authority": "Official FPL bootstrap native fields",
            "source": "OFFICIAL_FPL",
            "endpoint": "bootstrap-static/",
            "fact_fields": list(PREDICTOR_RAW_FIELDS),
            "model_interpretation_separate": True,
        },
        "official_predictor_raw_contract": {
            "source": "OFFICIAL_FPL",
            "endpoint": "bootstrap-static/",
            "field_names_preserved": True,
            "raw_fields": list(PREDICTOR_RAW_FIELDS),
            "auth_required": False,
            "ui_scraping": False,
        },
    }
    atomic_json(CACHE_OUT, {"generated_at": generated_at, "players": current})
    atomic_json(PRICES_OUT, prices)
    atomic_json(UNIVERSE_OUT, {"generated_at": generated_at, "players": universe})
    return {
        "generated_at": generated_at,
        "confirmed_changes": len(confirmed),
        "universe_players": len(universe),
        "official_predictor_raw_players": len(predictor_raw),
        "top_buy_pressure": len(prices["top_buy_pressure"]),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
