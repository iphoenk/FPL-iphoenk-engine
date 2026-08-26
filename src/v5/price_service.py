from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from src.v5.config_cache import load_json_config
from src.v5.price_trajectory import (
    alerts,
    build_trajectory,
    filtered_pressure,
    market_watch_capacity,
    price_row,
    risk_sort_key,
)

PRICE_CONFIG = "config/v5_price_trajectory_registry.json"


def build_price_snapshot(
    bootstrap: dict,
    *,
    previous_state: dict | None = None,
    owned_ids: Iterable[int] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    generated_at = now or datetime.now(timezone.utc)
    total_players = int(bootstrap.get("total_players") or 0)
    raw_rows = [price_row(player, total_players) for player in bootstrap.get("elements", [])]
    enriched, new_state = build_trajectory(raw_rows, previous_state or {}, generated_at)
    buy, buy_noise = filtered_pressure(enriched, "buy")
    sell, sell_noise = filtered_pressure(enriched, "sell")
    rising = sorted(
        (row for row in enriched if row.get("risk_direction") == "RISE"),
        key=risk_sort_key,
        reverse=True,
    )
    falling = sorted(
        (row for row in enriched if row.get("risk_direction") == "FALL"),
        key=risk_sort_key,
        reverse=True,
    )
    owned = {int(x) for x in owned_ids}
    alert_rows = alerts(enriched, owned)
    external_watch = [
        row
        for row in sorted(enriched, key=risk_sort_key, reverse=True)
        if int(row["element"]) not in owned
    ][: market_watch_capacity()]
    prior_players = (previous_state or {}).get("players", {})
    confirmed = []
    for row in enriched:
        prior = prior_players.get(str(row["element"])) or {}
        old = prior.get("now_cost")
        current = row.get("now_cost")
        if old is not None and current is not None and int(old) != int(current):
            confirmed.append(
                {
                    "element": row["element"],
                    "name": row.get("name"),
                    "previous": int(old),
                    "current": int(current),
                    "delta": int(current) - int(old),
                }
            )
    limit = int(load_json_config(PRICE_CONFIG)["filters"]["top_pressure_limit"])
    return {
        "prices": {
            "generated_at": generated_at.isoformat(),
            "confirmed_changes": confirmed,
            "players": enriched,
            "top_buy_pressure": buy,
            "top_sell_pressure": sell,
            "top_rise_risk": rising[:limit],
            "top_fall_risk": falling[:limit],
            "market_noise": {"buy": buy_noise, "sell": sell_noise},
        },
        "trajectory_state": new_state,
        "alerts": {
            "generated_at": generated_at.isoformat(),
            "alerts": alert_rows,
            "market_watch_candidates": external_watch,
        },
    }
