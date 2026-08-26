from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.rules import FINANCE_RULES
from src.v5.config_cache import load_json_config

REGISTRY_CONFIG = "config/v5_finance_registry.json"


@dataclass(frozen=True)
class SellValueResolution:
    sell_cost: int | None
    purchase_cost: int | None
    source: str
    exact: bool


def _registry() -> dict[str, Any]:
    data = load_json_config(REGISTRY_CONFIG)
    if not isinstance(data.get("owned_sell_value"), dict):
        raise RuntimeError("invalid V5 finance registry")
    return data


def sell_cost(now_cost: int, purchase_cost: int) -> int:
    configured = str(_registry()["owned_sell_value"].get("fallback_method", ""))
    official = str((FINANCE_RULES.get("sell_value") or {}).get("method") or "")
    if configured != "official_half_profit_floor" or official != configured:
        raise RuntimeError(
            f"unsupported or inconsistent sell-value method: configured={configured!r}, official={official!r}"
        )
    now = int(now_cost)
    purchase = int(purchase_cost)
    if now <= purchase:
        return now
    return purchase + ((now - purchase) // 2)


def build_transfer_spells(transfers: list[dict]) -> dict[int, dict[str, Any]]:
    spells: dict[int, dict[str, Any]] = {}
    for tr in sorted(transfers, key=lambda x: (x.get("event", 0), x.get("time", ""))):
        out_id = tr.get("element_out")
        in_id = tr.get("element_in")
        try:
            out_key = int(out_id) if out_id is not None else None
        except (TypeError, ValueError):
            out_key = None
        try:
            in_key = int(in_id) if in_id is not None else None
        except (TypeError, ValueError):
            in_key = None
        if out_key is not None:
            spells.pop(out_key, None)
        if in_key is not None:
            cost = tr.get("element_in_cost")
            spells[in_key] = {
                "purchase_cost": int(cost) if cost is not None else None,
                "event": tr.get("event"),
                "time": tr.get("time"),
                "source": "entry_transfer_history",
            }
    return spells


def reconstruct_purchase_cost(
    element_id: int,
    transfers: list[dict],
    initial_purchase_costs: Mapping[int, int] | None = None,
) -> tuple[int | None, str]:
    eid = int(element_id)
    spell = build_transfer_spells(transfers).get(eid)
    if spell and spell.get("purchase_cost") is not None:
        return int(spell["purchase_cost"]), "entry_transfer_history"
    baseline = initial_purchase_costs or {}
    if eid in baseline:
        return int(baseline[eid]), "initial_squad_baseline"
    return None, "unresolved"


def resolve_sell_value(
    *,
    element_id: int,
    now_cost: int,
    authenticated_selling_price: int | None = None,
    authenticated_purchase_price: int | None = None,
    transfers: list[dict] | None = None,
    initial_purchase_costs: Mapping[int, int] | None = None,
) -> SellValueResolution:
    if authenticated_selling_price is not None:
        purchase = int(authenticated_purchase_price) if authenticated_purchase_price is not None else None
        return SellValueResolution(int(authenticated_selling_price), purchase, "authenticated_selling_price", True)
    if authenticated_purchase_price is not None:
        purchase = int(authenticated_purchase_price)
        return SellValueResolution(sell_cost(now_cost, purchase), purchase, "authenticated_purchase_price", True)
    purchase, source = reconstruct_purchase_cost(
        int(element_id), transfers or [], initial_purchase_costs=initial_purchase_costs
    )
    if purchase is None:
        return SellValueResolution(None, None, source, False)
    return SellValueResolution(sell_cost(now_cost, purchase), purchase, source, False)


def build_squad_ledger(
    squad: Iterable[dict],
    *,
    now_costs: Mapping[int, int],
    transfers: list[dict] | None = None,
    authenticated_prices: Iterable[dict] | None = None,
    initial_purchase_costs: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    """Build the owned-player ledger in one pass. Transfer spells are indexed once per run."""
    spells = build_transfer_spells(transfers or [])
    auth = {int(row["element"]): row for row in (authenticated_prices or []) if row.get("element") is not None}
    baseline = {int(k): int(v) for k, v in (initial_purchase_costs or {}).items()}
    ledger = []
    for squad_row in squad:
        eid = int(squad_row["element"])
        if eid not in now_costs:
            raise RuntimeError(f"missing current price for owned element {eid}")
        now = int(now_costs[eid])
        auth_row = auth.get(eid, {})
        if auth_row.get("selling_price") is not None:
            resolution = SellValueResolution(
                int(auth_row["selling_price"]),
                int(auth_row["purchase_price"]) if auth_row.get("purchase_price") is not None else None,
                "authenticated_selling_price",
                True,
            )
        elif auth_row.get("purchase_price") is not None:
            purchase = int(auth_row["purchase_price"])
            resolution = SellValueResolution(sell_cost(now, purchase), purchase, "authenticated_purchase_price", True)
        else:
            spell = spells.get(eid)
            if spell and spell.get("purchase_cost") is not None:
                purchase = int(spell["purchase_cost"])
                resolution = SellValueResolution(sell_cost(now, purchase), purchase, "entry_transfer_history", False)
            elif eid in baseline:
                purchase = int(baseline[eid])
                resolution = SellValueResolution(sell_cost(now, purchase), purchase, "initial_squad_baseline", False)
            else:
                resolution = SellValueResolution(None, None, "unresolved", False)
        ledger.append(
            {
                **dict(squad_row),
                "now_cost": now,
                "purchase_cost": resolution.purchase_cost,
                "sell_cost": resolution.sell_cost,
                "finance_source": resolution.source,
                "finance_exact": resolution.exact,
            }
        )
    market_value = sum(int(row["now_cost"]) for row in ledger)
    complete = all(row["sell_cost"] is not None for row in ledger)
    return {
        "players": ledger,
        "market_value": market_value,
        "sell_value": sum(int(row["sell_cost"]) for row in ledger) if complete else None,
        "sell_value_complete": complete,
        "exact_count": sum(bool(row["finance_exact"]) for row in ledger),
        "unresolved_elements": [int(row["element"]) for row in ledger if row["sell_cost"] is None],
    }


def affordability_cost(*, owned: bool, now_cost: int, sell_value: int | None = None) -> int:
    if not owned:
        return int(now_cost)
    if sell_value is None:
        raise RuntimeError("owned-player affordability requires resolved sell value")
    return int(sell_value)
