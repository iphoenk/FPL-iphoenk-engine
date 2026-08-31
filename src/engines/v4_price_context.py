from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from src.engines.price_radar import (
    _normalise_player,
    _overall_health,
    _parse_dt,
    _position_map,
    _raw_payload_hash,
    _served_evidence,
    canonical_contract,
)
from src.engines.team_value import sell_cost
from src.utils import DATA, atomic_json, read_json, utcnow

RUNTIME = DATA / "runtime"
SNAPSHOT = RUNTIME / "snapshot.v1.json"


def _confirmed_changes(raw_rows: list[dict], previous_cache: dict) -> tuple[list[dict], dict]:
    previous = (previous_cache or {}).get("players") or {}
    confirmed: list[dict] = []
    current: dict[str, dict] = {}
    for raw in raw_rows:
        element = int(raw.get("id") or 0)
        now_cost = raw.get("now_cost")
        if not element:
            continue
        key = str(element)
        current[key] = {"now_cost": now_cost, "ownership": raw.get("selected_by_percent")}
        old = previous.get(key) or {}
        if old.get("now_cost") is None or now_cost is None:
            continue
        if int(old["now_cost"]) != int(now_cost):
            confirmed.append({
                "element": element,
                "name": raw.get("web_name"),
                "previous": int(old["now_cost"]),
                "current": int(now_cost),
                "delta": int(now_cost) - int(old["now_cost"]),
                "state": "CONFIRMED_PRICE_CHANGE",
            })
    return confirmed, {"generated_at": utcnow().isoformat(), "players": current}


def _pressure(rows: list[dict], total_players: int) -> tuple[list[dict], list[dict]]:
    enriched = []
    for row in rows:
        ownership = float(row.get("ownership_pct") or 0.0)
        owners = max(1, int(total_players * ownership / 100.0))
        net = row.get("net_transfers")
        net = int(net) if net is not None else 0
        enriched.append({**row, "momentum": net / owners})
    buys = sorted(enriched, key=lambda row: (row["momentum"], int(row.get("net_transfers") or 0)), reverse=True)[:25]
    sells = sorted(enriched, key=lambda row: (row["momentum"], int(row.get("net_transfers") or 0)))[:25]
    return buys, sells


def build_market_context(
    bootstrap: dict,
    *,
    observed_at: datetime | str | None,
    now: datetime | None = None,
    previous_cache: dict | None = None,
    owned_ids: set[int] | None = None,
    watchlist_ids: Iterable[int] | None = None,
    transport_health: dict | None = None,
) -> dict:
    current = now or utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    observed = _parse_dt(observed_at)
    raw_rows = [row for row in bootstrap.get("elements") or [] if isinstance(row, dict)]
    position_by_type = _position_map(bootstrap.get("element_types") or [])
    raw_hash = _raw_payload_hash(raw_rows)
    confirmed, price_cache = _confirmed_changes(raw_rows, previous_cache or {})
    confirmed_by_id = {int(row["element"]): row for row in confirmed}
    rows = [
        _normalise_player(
            raw,
            position_by_type=position_by_type,
            observed_at=observed,
            now=current,
            raw_payload_hash=raw_hash,
            confirmed_change=confirmed_by_id.get(int(raw.get("id") or -1)),
        )
        for raw in raw_rows
    ]
    health = _overall_health(rows, transport_health or {"status": "SNAPSHOT_DERIVED"})
    by_id = {int(row["element_id"]): row for row in rows if row.get("element_id") is not None}
    owned_set = {int(element) for element in (owned_ids or set())}
    all15 = [_served_evidence(by_id[element], owned=True) for element in sorted(owned_set) if element in by_id]
    watch = [
        _served_evidence(by_id[int(element)], owned=False)
        for element in (watchlist_ids or [])
        if int(element) in by_id and int(element) not in owned_set
    ][:20]
    contract = canonical_contract()
    buys, sells = _pressure(rows, int(bootstrap.get("total_players") or 0))
    return {
        "schema_version": 1,
        "contract": contract,
        "policy_id": contract["model_id"],
        "generated_at": current.isoformat(),
        "source": "OFFICIAL_FPL",
        "authority_rank": contract["source_authority"],
        "health": health,
        "players": rows,
        "all15_actionable_price_radar": all15,
        "all20_external_dss_watchlist": watch,
        "confirmed_changes": confirmed,
        "top_buy_pressure": buys,
        "top_sell_pressure": sells,
        "price_cache": price_cache,
        "market_context_role": "TIMING_AFFORDABILITY_OPTIONALITY_ONLY",
        "football_decision_authority": "SUBORDINATE",
        "v3_v4_canonical_parity": {
            "module": "src.engines.price_radar",
            "model_id": contract["model_id"],
            "schema_version": contract["schema_version"],
            "raw_likelihood_preserved": True,
            "no_intra_cycle_crossing_eta": True,
            "dst_safe_london_update_clock": True,
        },
    }


def serve_price_evidence(prices: dict, element_ids: Iterable[int], *, owned: bool, limit: int | None = None) -> list[dict]:
    by_id = {int(row["element_id"]): row for row in prices.get("players") or [] if row.get("element_id") is not None}
    out: list[dict] = []
    seen: set[int] = set()
    for raw_element in element_ids:
        element = int(raw_element or 0)
        if element <= 0 or element in seen or element not in by_id:
            continue
        seen.add(element)
        out.append(_served_evidence(by_id[element], owned=owned))
        if limit is not None and len(out) >= limit:
            break
    return out


def _scenario(
    name: str,
    *,
    outgoing: dict,
    incoming: dict,
    ledger_row: dict,
    bank: int,
    outgoing_drop: int = 0,
    incoming_rise: int = 0,
) -> dict:
    purchase = ledger_row.get("purchase_cost")
    governed_sell = ledger_row.get("sell_cost")
    if purchase is None or governed_sell is None:
        return {
            "scenario": name,
            "affordable": None,
            "remaining_bank": None,
            "required_extra_budget": None,
            "sell_value_impact": None,
            "structural_flexibility_impact": None,
            "limitation": "AUTHORITATIVE_OR_RECONSTRUCTED_SELL_VALUE_UNAVAILABLE",
        }
    outgoing_now = int(outgoing.get("now_cost") or 0)
    incoming_now = int(incoming.get("now_cost") or 0)
    future_outgoing = max(0, outgoing_now - outgoing_drop)
    future_incoming = incoming_now + incoming_rise
    future_sell = sell_cost(future_outgoing, int(purchase))
    funds = int(bank) + future_sell
    remaining = funds - future_incoming
    base_remaining = int(bank) + int(governed_sell) - incoming_now
    return {
        "scenario": name,
        "affordable": remaining >= 0,
        "remaining_bank": remaining,
        "required_extra_budget": max(0, -remaining),
        "sell_value_impact": future_sell - int(governed_sell),
        "structural_flexibility_impact": remaining - base_remaining,
        "outgoing_future_sell_value": future_sell,
        "incoming_future_price": future_incoming,
    }


def price_squeeze(outgoing: dict, incoming: dict, ledger_row: dict, bank: int) -> dict:
    scenarios = [
        _scenario("BASE", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank),
        _scenario("OUTGOING_FALL_0_1", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, outgoing_drop=1),
        _scenario("INCOMING_RISE_0_1", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, incoming_rise=1),
        _scenario("BOTH_SQUEEZE_0_1", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, outgoing_drop=1, incoming_rise=1),
        _scenario("OUTGOING_FALL_0_2", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, outgoing_drop=2),
        _scenario("INCOMING_RISE_0_2", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, incoming_rise=2),
        _scenario("BOTH_SQUEEZE_0_2", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, outgoing_drop=2, incoming_rise=2),
    ]
    outgoing_risk = outgoing.get("direction") == "FALL" and outgoing.get("model_urgency") in {"WATCH", "HIGH", "CRITICAL"}
    incoming_risk = incoming.get("direction") == "RISE" and incoming.get("model_urgency") in {"WATCH", "HIGH", "CRITICAL"}
    scenarios.append(_scenario(
        "WORST_REASONABLE_SHORT_HORIZON",
        outgoing=outgoing,
        incoming=incoming,
        ledger_row=ledger_row,
        bank=bank,
        outgoing_drop=2 if outgoing_risk else 0,
        incoming_rise=2 if incoming_risk else 0,
    ))
    return {
        "outgoing": {
            "element": outgoing.get("element_id"),
            "name": outgoing.get("player_name"),
            "now_cost": outgoing.get("now_cost"),
            "sell_value": ledger_row.get("sell_cost"),
            "current_progress": outgoing.get("current_progress_percent"),
            "offset0": outgoing.get("projection_offset_0_percent"),
            "raw_likelihood": outgoing.get("projection_offset_0_likelihood"),
            "direction": outgoing.get("direction"),
        },
        "incoming": {
            "element": incoming.get("element_id"),
            "name": incoming.get("player_name"),
            "now_cost": incoming.get("now_cost"),
            "current_progress": incoming.get("current_progress_percent"),
            "offset0": incoming.get("projection_offset_0_percent"),
            "raw_likelihood": incoming.get("projection_offset_0_likelihood"),
            "direction": incoming.get("direction"),
        },
        "bank": int(bank),
        "next_official_price_update_at": incoming.get("next_official_price_update_at") or outgoing.get("next_official_price_update_at"),
        "eta_seconds": incoming.get("eta_to_next_price_update_seconds") if incoming.get("eta_to_next_price_update_seconds") is not None else outgoing.get("eta_to_next_price_update_seconds"),
        "scenarios": scenarios,
        "price_only_execution_authorized": False,
    }


def squeeze_for_pairs(prices: dict, pairs: Iterable[tuple[int, int]], ledger: list[dict], bank: int) -> list[dict]:
    by_id = {int(row["element_id"]): row for row in prices.get("players") or [] if row.get("element_id") is not None}
    ledger_by_id = {int(row["element"]): row for row in ledger if row.get("element") is not None}
    out = []
    for outgoing_id, incoming_id in pairs:
        outgoing = by_id.get(int(outgoing_id))
        incoming = by_id.get(int(incoming_id))
        ledger_row = ledger_by_id.get(int(outgoing_id))
        if outgoing and incoming and ledger_row:
            out.append(price_squeeze(outgoing, incoming, ledger_row, bank))
    return out


def refresh_price_context() -> dict:
    """Prediction-stage owner for the canonical price artifact.

    This function may write only the governed price cache/artifact. It deliberately
    does not mutate data/latest.json, which is locked after Prediction completes.
    The current DSS watchlist is discovered later by Optimization and is joined
    read-only through serve_price_evidence().
    """
    raw = read_json(SNAPSHOT, {})
    team = read_json(DATA / "team.json", {})
    bootstrap = ((raw.get("official") or {}).get("bootstrap") or {})
    if not bootstrap.get("elements"):
        raise RuntimeError("Official bootstrap required for V4 price context")

    owned_ids = {int(row.get("element") or 0) for row in team.get("squad") or [] if row.get("element") is not None}
    previous_cache = read_json(DATA / "price_cache.json", {})
    context = build_market_context(
        bootstrap,
        observed_at=raw.get("generated_at"),
        now=utcnow(),
        previous_cache=previous_cache,
        owned_ids=owned_ids,
        watchlist_ids=(),
        transport_health=((raw.get("endpoint_health") or {}).get("bootstrap") or {"status": "SNAPSHOT_DERIVED"}),
    )
    atomic_json(DATA / "price_cache.json", context.pop("price_cache"))
    atomic_json(DATA / "prices.json", context)
    return context


if __name__ == "__main__":
    result = refresh_price_context()
    print({
        "service": "v4_price_context",
        "health": (result.get("health") or {}).get("status"),
        "players": len(result.get("players") or []),
        "all15": len(result.get("all15_actionable_price_radar") or []),
        "all20": len(result.get("all20_external_dss_watchlist") or []),
        "canonical_model": (result.get("contract") or {}).get("model_id"),
    })
