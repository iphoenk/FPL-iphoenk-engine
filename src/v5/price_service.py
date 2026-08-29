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


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / max(1, denominator), 4)


def build_transfer_momentum_evidence(
    bootstrap: dict[str, Any],
    price_rows: list[dict[str, Any]],
    *,
    minimum_coverage_ratio: float = 0.95,
) -> dict[str, Any]:
    """Verify DSS-42 from Official transfer counts linked to current governed prices.

    This does not predict price changes and does not invent external thresholds. The
    threshold here is data-contract coverage only: whether enough Official rows can be
    linked to the price snapshot generated from the same refresh.
    """
    elements = [row for row in bootstrap.get("elements") or [] if isinstance(row, dict) and row.get("id") is not None]
    prices = {int(row["element"]): row for row in price_rows if isinstance(row, dict) and row.get("element") is not None}
    covered = linked = price_matches = active = total_in = total_out = 0
    for player in elements:
        eid = int(player["id"])
        has_counts = player.get("transfers_in_event") is not None and player.get("transfers_out_event") is not None
        if has_counts:
            covered += 1
            tin = int(player.get("transfers_in_event") or 0)
            tout = int(player.get("transfers_out_event") or 0)
            total_in += tin
            total_out += tout
            if tin != tout:
                active += 1
        price = prices.get(eid)
        if isinstance(price, dict):
            linked += 1
            if price.get("now_cost") is not None and player.get("now_cost") is not None and int(price["now_cost"]) == int(player["now_cost"]):
                price_matches += 1
    n = len(elements)
    count_ratio = _ratio(covered, n)
    linkage_ratio = _ratio(linked, n)
    price_match_ratio = _ratio(price_matches, n)
    available = bool(n) and min(count_ratio, linkage_ratio, price_match_ratio) >= float(minimum_coverage_ratio)
    return {
        "evidence_state": "AVAILABLE" if available else "INSUFFICIENT",
        "players": n,
        "transfer_count_covered": covered,
        "transfer_count_coverage_ratio": count_ratio,
        "price_snapshot_linked": linked,
        "price_snapshot_linkage_ratio": linkage_ratio,
        "current_price_matches": price_matches,
        "current_price_match_ratio": price_match_ratio,
        "players_with_nonzero_net_momentum": active,
        "total_transfers_in_event": total_in,
        "total_transfers_out_event": total_out,
        "net_transfers_event": total_in - total_out,
        "source": "Official FPL bootstrap transfer counts + V5 governed current-price snapshot",
        "external_threshold_invented": False,
        "predicted_price_change_invented": False,
        "coverage_threshold_is_data_contract_only": True,
    }


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
    rising = sorted((row for row in enriched if row.get("risk_direction") == "RISE"), key=risk_sort_key, reverse=True)
    falling = sorted((row for row in enriched if row.get("risk_direction") == "FALL"), key=risk_sort_key, reverse=True)
    owned = {int(x) for x in owned_ids}
    alert_rows = alerts(enriched, owned)
    external_watch = [row for row in sorted(enriched, key=risk_sort_key, reverse=True) if int(row["element"]) not in owned][: market_watch_capacity()]
    prior_players = (previous_state or {}).get("players", {})
    confirmed = []
    for row in enriched:
        prior = prior_players.get(str(row["element"])) or {}
        old = prior.get("now_cost"); current = row.get("now_cost")
        if old is not None and current is not None and int(old) != int(current):
            confirmed.append({"element":row["element"],"name":row.get("name"),"previous":int(old),"current":int(current),"delta":int(current)-int(old)})
    limit = int(load_json_config(PRICE_CONFIG)["filters"]["top_pressure_limit"])
    transfer_momentum = build_transfer_momentum_evidence(bootstrap, enriched)
    return {
        "prices": {"generated_at":generated_at.isoformat(),"confirmed_changes":confirmed,"players":enriched,"top_buy_pressure":buy,"top_sell_pressure":sell,"top_rise_risk":rising[:limit],"top_fall_risk":falling[:limit],"market_noise":{"buy":buy_noise,"sell":sell_noise}},
        "trajectory_state": new_state,
        "alerts": {"generated_at":generated_at.isoformat(),"alerts":alert_rows,"market_watch_candidates":external_watch},
        "transfer_momentum": transfer_momentum,
    }
