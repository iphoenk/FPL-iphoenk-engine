from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Iterable

from src.engines.fpl_rules_2026 import BUDGET_TENTHS, MAX_PER_CLUB, POSITION_COUNTS
from src.engines.team_value import sell_cost
from src.engines.v4_optimizer_primitives import gw_value as _gw_value
from src.utils import CONFIG, read_json


@dataclass(frozen=True)
class Candidate:
    element: int
    name: str
    position: str
    team_id: int
    team: str
    cost: int
    x3: float
    x5: float
    x10: float
    x15: float
    uncertainty: float
    objective: float
    gw_xpts: tuple[float, ...]


def _f(v, default=0.0) -> float:
    try:
        return float(v if v is not None else default)
    except Exception:
        return float(default)


@lru_cache(maxsize=1)
def _value_config() -> dict:
    return read_json(CONFIG / "prediction_quality_registry.json", {}).get("value") or {}


def player_objective(pred: dict) -> float:
    x3 = _f(pred.get("xpts_3")) / 3.0
    x5 = _f(pred.get("xpts_5")) / 5.0
    x10 = _f(pred.get("xpts_10")) / 10.0
    x15 = _f(pred.get("xpts_15")) / 15.0
    uncertainty = _f(pred.get("uncertainty"))
    value = _f((pred.get("value") or {}).get("xpts5_per_million"))
    value_term = _f(_value_config().get("objective_weight"), 0.02) * min(6.0, value)
    return 0.25 * x3 + 0.50 * x5 + 0.15 * x10 + 0.10 * x15 - 0.08 * uncertainty + value_term


def build_candidates(predictions: dict, universe: dict) -> list[Candidate]:
    by_element = {int(player["element"]): player for player in universe.get("players", [])}
    out: list[Candidate] = []
    for pred in predictions.get("players", []):
        element = int(pred.get("element"))
        universe_player = by_element.get(element)
        if not universe_player:
            continue
        position = universe_player.get("position") or pred.get("position")
        if position not in POSITION_COUNTS or universe_player.get("status") in {"u", "s"}:
            continue
        fixtures = tuple(_f(row.get("xpts")) for row in pred.get("fixtures", [])[:15])
        out.append(Candidate(
            element,
            universe_player.get("name") or pred.get("name") or str(element),
            position,
            int(universe_player.get("team_id")),
            universe_player.get("team") or str(universe_player.get("team_id")),
            int(universe_player.get("now_cost") or 0),
            _f(pred.get("xpts_3")),
            _f(pred.get("xpts_5")),
            _f(pred.get("xpts_10")),
            _f(pred.get("xpts_15")),
            _f(pred.get("uncertainty")),
            player_objective(pred),
            fixtures,
        ))
    return out


def reconcile_owned_costs(candidates: list[Candidate], locked: dict) -> tuple[list[Candidate], dict]:
    """Use selling prices for owned players and current prices for unowned players."""
    by_id = {player.element: player for player in candidates}
    owned_costs: dict[int, int] = {}
    ledger: list[dict] = []
    for row in locked.get("players", []):
        element = int(row.get("element"))
        candidate = by_id.get(element)
        if candidate is None:
            raise RuntimeError(f"owned player absent from candidate universe: {element}")
        explicit = row.get("selling_price", row.get("sell_cost"))
        purchase = row.get("purchase_cost")
        if explicit is not None:
            selling = int(explicit)
            source = "official_or_locked_selling_price"
        elif purchase is not None:
            selling = sell_cost(candidate.cost, int(purchase))
            source = "reconstructed_from_purchase_cost"
        else:
            raise RuntimeError(f"owned player {element} lacks purchase/selling price evidence")
        if selling <= 0 or selling > candidate.cost:
            raise RuntimeError(
                f"invalid selling price for owned player {element}: sell={selling}, now={candidate.cost}"
            )
        owned_costs[element] = selling
        ledger.append({
            "element": element,
            "purchase_cost": int(purchase) if purchase is not None else None,
            "now_cost": candidate.cost,
            "sell_cost": selling,
            "source": source,
        })

    effective = [replace(player, cost=owned_costs.get(player.element, player.cost)) for player in candidates]
    bank = int(locked.get("itb_tenths") or 0)
    sell_value = sum(owned_costs.values())
    return effective, {
        "price_basis": "owned_sell_cost_unowned_now_cost",
        "owned_players": len(owned_costs),
        "owned_sell_value_tenths": sell_value,
        "bank_tenths": bank,
        "available_budget_tenths": sell_value + bank,
        "ledger": ledger,
        "fail_closed_on_missing_purchase_price": True,
    }


def validate_squad(players: Iterable[Candidate], budget: int = BUDGET_TENTHS) -> tuple[bool, str]:
    rows = list(players)
    if len(rows) != 15:
        return False, "squad_count"
    counts = Counter(player.position for player in rows)
    if any(counts.get(position, 0) != expected for position, expected in POSITION_COUNTS.items()):
        return False, "position_structure"
    if sum(player.cost for player in rows) > budget:
        return False, "budget"
    clubs = Counter(player.team_id for player in rows)
    if clubs and max(clubs.values()) > MAX_PER_CLUB:
        return False, "club_limit"
    if len({player.element for player in rows}) != 15:
        return False, "duplicate"
    return True, "ok"


def _pool(candidates: list[Candidate], locked_ids: set[int], pool_size: int) -> list[Candidate]:
    ranked = sorted(candidates, key=lambda player: (player.objective, player.x5, -player.cost), reverse=True)
    pool = ranked[:pool_size]
    seen = {player.element for player in pool}
    pool.extend(player for player in ranked if player.element in locked_ids and player.element not in seen)
    return pool


def best_xi(players: Iterable[Candidate], gw_index: int) -> tuple[float, list[int]]:
    rows = list(players)
    by_position = {
        position: sorted(
            [player for player in rows if player.position == position],
            key=lambda player: _gw_value(player, gw_index),
            reverse=True,
        )
        for position in POSITION_COUNTS
    }
    if any(len(by_position[position]) < POSITION_COUNTS[position] for position in POSITION_COUNTS):
        return 0.0, []
    goalkeeper = by_position["GK"][0]
    best_score = -1.0
    best_ids: list[int] = []
    for defenders in range(3, 6):
        for midfielders in range(2, 6):
            forwards = 10 - defenders - midfielders
            if not 1 <= forwards <= 3:
                continue
            chosen = (
                [goalkeeper]
                + by_position["DEF"][:defenders]
                + by_position["MID"][:midfielders]
                + by_position["FWD"][:forwards]
            )
            score = sum(_gw_value(player, gw_index) for player in chosen)
            if score > best_score:
                best_score = score
                best_ids = [player.element for player in chosen]
    return max(0.0, best_score), best_ids


def _group_by_position(players: Iterable[Candidate]) -> dict[str, list[Candidate]]:
    grouped = {position: [] for position in POSITION_COUNTS}
    for player in players:
        grouped[player.position].append(player)
    return grouped


def _best_xi_score_grouped(by_position: dict[str, list[Candidate]], gw_index: int) -> float:
    goalkeeper = max((_gw_value(player, gw_index) for player in by_position["GK"]), default=0.0)
    defence = sorted((_gw_value(player, gw_index) for player in by_position["DEF"]), reverse=True)
    midfield = sorted((_gw_value(player, gw_index) for player in by_position["MID"]), reverse=True)
    forward = sorted((_gw_value(player, gw_index) for player in by_position["FWD"]), reverse=True)
    defence_prefix = [0.0]
    midfield_prefix = [0.0]
    forward_prefix = [0.0]
    for value in defence:
        defence_prefix.append(defence_prefix[-1] + value)
    for value in midfield:
        midfield_prefix.append(midfield_prefix[-1] + value)
    for value in forward:
        forward_prefix.append(forward_prefix[-1] + value)
    return max(
        goalkeeper + defence_prefix[3] + midfield_prefix[4] + forward_prefix[3],
        goalkeeper + defence_prefix[3] + midfield_prefix[5] + forward_prefix[2],
        goalkeeper + defence_prefix[4] + midfield_prefix[3] + forward_prefix[3],
        goalkeeper + defence_prefix[4] + midfield_prefix[4] + forward_prefix[2],
        goalkeeper + defence_prefix[4] + midfield_prefix[5] + forward_prefix[1],
        goalkeeper + defence_prefix[5] + midfield_prefix[2] + forward_prefix[3],
        goalkeeper + defence_prefix[5] + midfield_prefix[3] + forward_prefix[2],
        goalkeeper + defence_prefix[5] + midfield_prefix[4] + forward_prefix[1],
    )


def squad_utility_fast(players: Iterable[Candidate], horizon: int = 5, bench_weight: float = 0.12) -> float:
    rows = list(players)
    grouped = _group_by_position(rows)
    total = 0.0
    for index in range(horizon):
        xi = _best_xi_score_grouped(grouped, index)
        squad_total = sum(_gw_value(player, index) for player in rows)
        total += xi + bench_weight * (squad_total - xi)
    return total


def squad_utility(players: Iterable[Candidate], horizon: int = 5, bench_weight: float = 0.12) -> float:
    """Reference scoring path used only to verify fast utility equivalence in tests."""
    rows = list(players)
    total = 0.0
    for index in range(horizon):
        xi, ids = best_xi(rows, index)
        id_set = set(ids)
        bench = sum(_gw_value(player, index) for player in rows if player.element not in id_set)
        total += xi + bench_weight * bench
    return total


# Two bits per team encode counts 0..3; these are shared by the exact-fast search.
def _club_shift(team_id: int) -> int:
    return (team_id - 1) * 2


def _club_count(signature: int, team_id: int) -> int:
    return (signature >> _club_shift(team_id)) & 0b11


def _club_add(signature: int, team_id: int) -> int:
    return signature + (1 << _club_shift(team_id))


def optimize_squad(
    candidates: list[Candidate],
    locked_ids: set[int] | None = None,
    budget: int = BUDGET_TENTHS,
    pool_sizes: dict[str, int] | None = None,
    beam_size: int = 6000,
) -> dict:
    """Compatibility entry point delegated to the single exact-fast search owner."""
    from src.engines.v4_wc_optimizer_fast import optimize_squad_fast

    return optimize_squad_fast(
        candidates,
        locked_ids=locked_ids,
        budget=budget,
        pool_sizes=pool_sizes,
        beam_size=beam_size,
    )


def squad_metrics(players: Iterable[Candidate]) -> dict:
    rows = list(players)
    xi5 = 0.0
    detail = []
    for index in range(5):
        score, ids = best_xi(rows, index)
        xi5 += score
        detail.append({"gw_offset": index + 1, "xpts": round(score, 2), "elements": ids})
    return {
        "cost": sum(player.cost for player in rows),
        "objective": round(sum(player.objective for player in rows), 4),
        "squad_xpts_3": round(sum(player.x3 for player in rows), 2),
        "squad_xpts_5": round(sum(player.x5 for player in rows), 2),
        "squad_xpts_10": round(sum(player.x10 for player in rows), 2),
        "squad_xpts_15": round(sum(player.x15 for player in rows), 2),
        "best_xi_xpts_5": round(xi5, 2),
        "bench_adjusted_utility_5": round(squad_utility_fast(rows, 5), 2),
        "best_xi_by_gw": detail,
    }


def classify_gain(delta_utility: float, delta_xi5: float) -> str:
    if delta_xi5 >= 4.0 and delta_utility >= 4.5:
        return "MATERIAL_UPGRADE"
    if delta_xi5 >= 1.5 and delta_utility >= 2.0:
        return "OPTIONAL_IMPROVEMENT"
    return "KEEP_15"


def decision_report(predictions: dict, universe: dict, locked: dict, budget: int | None = None) -> dict:
    return decision_report_from_candidates(build_candidates(predictions, universe), locked, budget)


def decision_report_from_candidates(candidates: list[Candidate], locked: dict, budget: int | None = None) -> dict:
    """Compatibility entry point delegated to the canonical exact-fast report."""
    from src.engines.v4_wc_optimizer_fast import decision_report_from_candidates_fast

    return decision_report_from_candidates_fast(candidates, locked, budget)
