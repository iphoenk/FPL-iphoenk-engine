from __future__ import annotations

from typing import Any, Iterable

from src.engines import price_radar as canonical
from src.v5.finance import sell_cost


def _squeeze_policy() -> tuple[tuple[int, ...], frozenset[str], int]:
    policy = canonical.load_policy().get("squeeze_policy")
    if not isinstance(policy, dict):
        raise RuntimeError("price radar policy missing squeeze_policy")
    raw_steps = policy.get("scenario_steps_tenths")
    raw_levels = policy.get("material_urgency_levels")
    worst = policy.get("worst_reasonable_short_horizon_tenths")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RuntimeError("price radar squeeze_policy.scenario_steps_tenths must be a non-empty list")
    steps = tuple(sorted({int(value) for value in raw_steps}))
    if any(value <= 0 for value in steps):
        raise RuntimeError("price radar squeeze scenario steps must be positive tenths")
    if not isinstance(raw_levels, list) or not raw_levels:
        raise RuntimeError("price radar squeeze_policy.material_urgency_levels must be a non-empty list")
    levels = frozenset(str(value) for value in raw_levels)
    worst_step = int(worst) if worst is not None else 0
    if worst_step <= 0:
        raise RuntimeError("price radar squeeze_policy.worst_reasonable_short_horizon_tenths must be positive")
    return steps, levels, worst_step


def _scenario_matrix(steps: tuple[int, ...]) -> tuple[tuple[str, int, int], ...]:
    rows: list[tuple[str, int, int]] = [("BASE", 0, 0)]
    for step in steps:
        suffix = f"0_{step}"
        rows.extend(
            (
                (f"OUTGOING_FALL_{suffix}", step, 0),
                (f"INCOMING_RISE_{suffix}", 0, step),
                (f"BOTH_SQUEEZE_{suffix}", step, step),
            )
        )
    return tuple(rows)


def _price_players(price: dict[str, Any]) -> dict[int, dict[str, Any]]:
    prices = price.get("prices") if isinstance(price.get("prices"), dict) else price
    rows = prices.get("players") if isinstance(prices, dict) else []
    return {
        int(row["element_id"] if row.get("element_id") is not None else row["element"]): row
        for row in rows or []
        if isinstance(row, dict) and (row.get("element_id") is not None or row.get("element") is not None)
    }


def _finance_players(team: dict[str, Any]) -> dict[int, dict[str, Any]]:
    finance = team.get("finance") if isinstance(team.get("finance"), dict) else {}
    return {
        int(row["element"]): row
        for row in finance.get("players") or []
        if isinstance(row, dict) and row.get("element") is not None
    }


def _bank(team: dict[str, Any]) -> int | None:
    finance = team.get("finance") if isinstance(team.get("finance"), dict) else {}
    value = finance.get("bank")
    return int(value) if value is not None else None


def _scenario(
    name: str,
    *,
    outgoing: dict[str, Any],
    incoming: dict[str, Any],
    ledger: dict[str, Any],
    bank: int | None,
    outgoing_drop: int,
    incoming_rise: int,
) -> dict[str, Any]:
    outgoing_now = canonical._int(outgoing.get("now_cost"))
    incoming_now = canonical._int(incoming.get("now_cost"))
    governed_sell = canonical._int(ledger.get("sell_cost"))
    purchase = canonical._int(ledger.get("purchase_cost"))
    if bank is None or incoming_now is None or governed_sell is None:
        return {
            "scenario": name,
            "affordable": None,
            "remaining_bank": None,
            "required_extra_budget": None,
            "sell_value_impact": None,
            "structural_flexibility_impact": None,
            "limitation": "BANK_OR_GOVERNED_SELL_VALUE_UNAVAILABLE",
        }
    if outgoing_drop and (outgoing_now is None or purchase is None):
        return {
            "scenario": name,
            "affordable": None,
            "remaining_bank": None,
            "required_extra_budget": None,
            "sell_value_impact": None,
            "structural_flexibility_impact": None,
            "limitation": "PURCHASE_COST_REQUIRED_FOR_FUTURE_SELL_VALUE_SCENARIO",
        }

    future_sell = governed_sell
    if outgoing_drop:
        future_sell = sell_cost(max(0, int(outgoing_now) - int(outgoing_drop)), int(purchase))
    future_incoming = int(incoming_now) + int(incoming_rise)
    remaining = int(bank) + int(future_sell) - future_incoming
    base_remaining = int(bank) + int(governed_sell) - int(incoming_now)
    return {
        "scenario": name,
        "affordable": remaining >= 0,
        "remaining_bank": remaining,
        "required_extra_budget": max(0, -remaining),
        "sell_value_impact": int(future_sell) - int(governed_sell),
        "structural_flexibility_impact": remaining - base_remaining,
        "outgoing_future_sell_value": int(future_sell),
        "incoming_future_price": future_incoming,
        "limitation": None,
    }


def _material_short_horizon_risk(
    row: dict[str, Any],
    direction: str,
    material_urgency_levels: frozenset[str],
) -> bool:
    return bool(
        row.get("direction") == direction
        and (
            row.get("predicted_change_cycle") == "NEXT_UPDATE"
            or str(row.get("model_urgency")) in material_urgency_levels
        )
    )


def price_squeeze(
    outgoing: dict[str, Any],
    incoming: dict[str, Any],
    ledger: dict[str, Any],
    bank: int | None,
) -> dict[str, Any]:
    steps, material_levels, worst_step = _squeeze_policy()
    scenarios = [
        _scenario(
            name,
            outgoing=outgoing,
            incoming=incoming,
            ledger=ledger,
            bank=bank,
            outgoing_drop=out_drop,
            incoming_rise=in_rise,
        )
        for name, out_drop, in_rise in _scenario_matrix(steps)
    ]
    outgoing_risk = _material_short_horizon_risk(outgoing, "FALL", material_levels)
    incoming_risk = _material_short_horizon_risk(incoming, "RISE", material_levels)
    worst = _scenario(
        "WORST_REASONABLE_SHORT_HORIZON",
        outgoing=outgoing,
        incoming=incoming,
        ledger=ledger,
        bank=bank,
        outgoing_drop=worst_step if outgoing_risk else 0,
        incoming_rise=worst_step if incoming_risk else 0,
    )
    scenarios.append(worst)
    base = scenarios[0]
    affordability_loss = base.get("affordable") is True and worst.get("affordable") is False
    flexibility_loss = (
        worst.get("structural_flexibility_impact") is not None
        and int(worst["structural_flexibility_impact"]) < 0
    )
    return {
        "outgoing": {
            "element": outgoing.get("element_id") or outgoing.get("element"),
            "name": outgoing.get("player_name") or outgoing.get("name"),
            "current_price": outgoing.get("now_cost"),
            "sell_value": ledger.get("sell_cost"),
            "sell_value_source": ledger.get("finance_source"),
            "sell_value_exact": ledger.get("finance_exact"),
            "current_progress": outgoing.get("current_progress_percent"),
            "offset0": outgoing.get("projection_offset_0_percent"),
            "raw_likelihood": outgoing.get("projection_offset_0_likelihood"),
            "direction": outgoing.get("direction"),
            "urgency": outgoing.get("model_urgency"),
        },
        "incoming": {
            "element": incoming.get("element_id") or incoming.get("element"),
            "name": incoming.get("player_name") or incoming.get("name"),
            "current_price": incoming.get("now_cost"),
            "current_progress": incoming.get("current_progress_percent"),
            "offset0": incoming.get("projection_offset_0_percent"),
            "raw_likelihood": incoming.get("projection_offset_0_likelihood"),
            "direction": incoming.get("direction"),
            "urgency": incoming.get("model_urgency"),
        },
        "bank": bank,
        "next_official_price_update_at": incoming.get("next_official_price_update_at") or outgoing.get("next_official_price_update_at"),
        "eta_to_next_price_update_seconds": (
            incoming.get("eta_to_next_price_update_seconds")
            if incoming.get("eta_to_next_price_update_seconds") is not None
            else outgoing.get("eta_to_next_price_update_seconds")
        ),
        "scenarios": scenarios,
        "affordability_loss_risk": affordability_loss,
        "structural_flexibility_loss_risk": flexibility_loss,
        "official_next_cycle_material_risk": outgoing_risk or incoming_risk,
        "price_only_execution_authorized": False,
        "governance": {
            "market_price_is_not_sell_value": True,
            "future_sell_value_uses_governed_purchase_cost": True,
            "unresolved_sell_value_is_never_fabricated": True,
            "price_signal_may_change_timing_not_football_merit": True,
            "scenario_policy_registry": "config/intelligence/price_radar.json#squeeze_policy",
            "scenario_steps_tenths": list(steps),
            "material_urgency_levels": sorted(material_levels),
            "worst_reasonable_short_horizon_tenths": worst_step,
        },
    }


def attach_watchlist_price_evidence(watchlist: dict[str, Any], price: dict[str, Any], owned_ids: Iterable[int]) -> dict[str, Any]:
    prices = _price_players(price)
    owned = {int(value) for value in owned_ids}
    positions: dict[str, list[dict[str, Any]]] = {}
    resolved = 0
    total = 0
    for position, raw_rows in (watchlist.get("positions") or {}).items():
        rows: list[dict[str, Any]] = []
        for raw in raw_rows or []:
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            total += 1
            element = canonical._int(row.get("element"))
            evidence = prices.get(element) if element is not None else None
            if evidence is not None:
                row["price_evidence"] = canonical._served_evidence(evidence, owned=element in owned)
                resolved += 1
            else:
                row["price_evidence"] = {
                    "element": element,
                    "source": None,
                    "evidence_state": "UNAVAILABLE",
                    "action": "Bukti harga resmi belum tersedia; keputusan DSS tidak diubah.",
                }
            rows.append(row)
        positions[str(position)] = rows
    return {
        **watchlist,
        "positions": positions,
        "price_evidence_coverage": {"expected": total, "resolved": resolved, "complete": resolved == total},
        "governance": {
            **(watchlist.get("governance") or {}),
            "price_evidence_bound_after_watchlist_selection": True,
            "price_evidence_may_not_change_membership": True,
            "price_evidence_may_not_change_rank": True,
            "fresh_official_price_evidence_cannot_be_overridden": True,
        },
    }


def annotate_comparator(
    comparator: dict[str, Any],
    *,
    price: dict[str, Any],
    team: dict[str, Any],
    transfer_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prices = _price_players(price)
    finance = _finance_players(team)
    bank = _bank(team)
    state = transfer_state if isinstance(transfer_state, dict) else {}
    pairs: list[dict[str, Any]] = []
    alternatives_evaluated = int(comparator.get("candidate_count") or 0) > 1
    for raw in comparator.get("pairs") or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        owned = row.get("owned") if isinstance(row.get("owned"), dict) else {}
        challenger = row.get("challenger") if isinstance(row.get("challenger"), dict) else {}
        out_id = canonical._int(owned.get("element"))
        in_id = canonical._int(challenger.get("element"))
        squeeze = None
        if out_id is not None and in_id is not None and out_id in prices and in_id in prices and out_id in finance:
            squeeze = price_squeeze(prices[out_id], prices[in_id], finance[out_id], bank)
        row["price_squeeze"] = squeeze or {
            "status": "UNAVAILABLE",
            "reason": "PRICE_OR_FINANCE_EVIDENCE_MISSING",
            "price_only_execution_authorized": False,
        }
        h5 = ((row.get("horizons") or {}).get("5") or {}) if isinstance(row.get("horizons"), dict) else {}
        football_valid = str(row.get("classification")) in {"LEAN_TRANSFER", "STRONG_TRANSFER"}
        structural_benefit = canonical._float(h5.get("raw_gain")) is not None and float(h5.get("raw_gain")) > 0
        material_budget_risk = bool(
            isinstance(squeeze, dict)
            and (squeeze.get("affordability_loss_risk") or squeeze.get("structural_flexibility_loss_risk"))
        )
        official_risk = bool(isinstance(squeeze, dict) and squeeze.get("official_next_cycle_material_risk"))
        ft_known = bool(
            state.get("wildcard_active")
            or state.get("free_hit_active")
            or state.get("free_transfers") is not None
        )
        news_risk_acceptable = state.get("injury_news_risk_acceptable") is True
        criteria = {
            "football_valid_target": football_valid,
            "structural_or_multi_gw_benefit": structural_benefit,
            "waiting_materially_risks_affordability_or_optionality": material_budget_risk,
            "official_next_cycle_price_risk_material": official_risk,
            "injury_news_match_risk_acceptable": news_risk_acceptable,
            "ft_or_hit_state_known": ft_known,
            "alternatives_evaluated": alternatives_evaluated,
        }
        row["execution_timing"] = {
            "criteria": criteria,
            "early_execution_review_eligible": all(criteria.values()),
            "price_only_execution_authorized": False,
            "classification_mutated_by_price": False,
            "narrative": (
                "Risiko harga dapat mempersempit ruang anggaran; percepatan hanya layak ditinjau setelah seluruh syarat sepak bola dan risiko eksekusi terpenuhi."
                if official_risk or material_budget_risk
                else "Belum ada tekanan harga yang cukup untuk mempercepat transfer."
            ),
        }
        pairs.append(row)
    result = {**comparator, "pairs": pairs, "top_comparisons": pairs[:8]}
    result["governance"] = {
        **(comparator.get("governance") or {}),
        "price_changes_timing_not_football_merit": True,
        "classification_mutated_by_price": False,
        "price_only_buy_sell_hit_forbidden": True,
    }
    return result
