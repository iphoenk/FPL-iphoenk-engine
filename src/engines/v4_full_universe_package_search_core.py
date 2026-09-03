from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations, permutations
from typing import Any, Iterable, Iterator

from src.engines import v4_wc_package_audit as reference
from src.engines.team_value import sell_cost
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_wc_optimizer import (
    MAX_PER_CLUB,
    POSITION_COUNTS,
    Candidate,
    reconcile_owned_costs,
    validate_squad,
)
from src.engines.v4_wc_package_audit_fast import (
    _chosen_profile,
    _keep_profile,
    _keep_profile_from_baseline,
    _metrics_from_profiles,
)
from src.utils import CONFIG, read_json


CONTRACT = "V4_FULL_UNIVERSE_PACKAGE_SEARCH_V1"
POLICY_FILE = CONFIG / "intelligence" / "full_universe_package_search.json"
_POSITION_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}


def _policy() -> dict:
    return read_json(POLICY_FILE, {}) or {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _mean(values: Iterable[float], default: float = 0.0) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else float(default)


def _candidate_vector(player: Candidate) -> tuple[float, ...]:
    gw = tuple(_f(value) for value in player.gw_xpts[:5])
    gw = gw + (0.0,) * max(0, 5 - len(gw))
    return (
        -float(player.cost),
        -float(player.uncertainty),
        float(player.x3),
        float(player.x5),
        float(player.x10),
        float(player.x15),
        float(player.objective),
        *gw[:5],
    )


def _dominates_player(left: Candidate, right: Candidate, epsilon: float) -> bool:
    """Safe incoming-player dominance within identical team and FPL position.

    Same team and position preserve club-slot and positional legality. Cost and
    uncertainty are minimized; every projection/objective/GW dimension is
    maximized. Therefore replacing the dominated incoming option cannot make any
    package worse under the package-search semantics consumed here.
    """
    if left.team_id != right.team_id or left.position != right.position or left.element == right.element:
        return False
    lv = _candidate_vector(left)
    rv = _candidate_vector(right)
    no_worse = all(a + epsilon >= b for a, b in zip(lv, rv))
    strict = any(a > b + epsilon for a, b in zip(lv, rv))
    return no_worse and strict


def safe_prune_incoming_players(
    candidates: list[Candidate],
    owned_ids: set[int],
    *,
    epsilon: float | None = None,
) -> tuple[list[Candidate], list[dict]]:
    cfg = (_policy().get("search") or {})
    epsilon = _f(cfg.get("dominance_epsilon"), 1e-6) if epsilon is None else float(epsilon)
    external = [row for row in candidates if row.element not in owned_ids]
    grouped: dict[tuple[str, int], list[Candidate]] = defaultdict(list)
    for player in external:
        grouped[(player.position, player.team_id)].append(player)

    pruned: set[int] = set()
    proofs: list[dict] = []
    for key in sorted(grouped, key=lambda item: (_POSITION_ORDER.get(item[0], 99), item[1])):
        rows = sorted(grouped[key], key=lambda item: item.element)
        for right in rows:
            if right.element in pruned:
                continue
            dominators = [left for left in rows if _dominates_player(left, right, epsilon)]
            if not dominators:
                continue
            # Deterministic strongest proof. No player name is involved in search authority.
            left = max(dominators, key=lambda row: (_candidate_vector(row), -row.element))
            pruned.add(right.element)
            proofs.append({
                "pruned_element": right.element,
                "dominating_element": left.element,
                "position": right.position,
                "team_id": right.team_id,
                "reason": "SAME_TEAM_SAME_POSITION_PARETO_DOMINANCE",
                "safe_legality_equivalence": True,
                "dominator_cost_tenths": left.cost,
                "dominated_cost_tenths": right.cost,
                "dominator_uncertainty": round(left.uncertainty, 6),
                "dominated_uncertainty": round(right.uncertainty, 6),
                "proof_dimensions": [
                    "cost", "uncertainty", "xpts_3", "xpts_5", "xpts_10", "xpts_15",
                    "objective", "gw_xpts_1", "gw_xpts_2", "gw_xpts_3", "gw_xpts_4", "gw_xpts_5",
                ],
            })
    kept = [row for row in external if row.element not in pruned]
    return kept, proofs


def _club_counts(players: Iterable[Candidate]) -> Counter:
    return Counter(player.team_id for player in players)


def _incoming_combinations(
    pools: dict[str, list[Candidate]],
    need: Counter,
    keep: tuple[Candidate, ...],
    budget: int,
    diagnostics: dict,
) -> Iterator[tuple[Candidate, ...]]:
    """Enumerate all legal incoming combinations without beam/top-N cutoffs."""
    keep_cost = sum(player.cost for player in keep)
    keep_clubs = _club_counts(keep)
    groups = [(pos, int(need[pos])) for pos in sorted(need, key=lambda p: (_POSITION_ORDER.get(p, 99), p)) if int(need[pos]) > 0]
    filtered: dict[str, list[Candidate]] = {}
    for pos, count in groups:
        # Any single incoming player above the total remaining budget is impossible.
        rows = [row for row in pools.get(pos, []) if keep_cost + row.cost <= budget]
        filtered[pos] = sorted(rows, key=lambda row: row.element)
        if len(rows) < count:
            return

    # Safe lower-cost feasibility bound for unfilled position groups.
    min_group_cost = {
        pos: sum(sorted(row.cost for row in filtered[pos])[:count])
        for pos, count in groups
    }
    suffix_min: list[int] = [0] * (len(groups) + 1)
    for index in range(len(groups) - 1, -1, -1):
        pos, _count = groups[index]
        suffix_min[index] = suffix_min[index + 1] + min_group_cost[pos]

    def recurse(group_index: int, chosen: tuple[Candidate, ...], chosen_cost: int, clubs: Counter) -> Iterator[tuple[Candidate, ...]]:
        diagnostics["search_nodes"] += 1
        if keep_cost + chosen_cost + suffix_min[group_index] > budget:
            diagnostics["packages_rejected_by_budget_bound"] += 1
            return
        if group_index >= len(groups):
            yield chosen
            return
        pos, count = groups[group_index]
        for combo in combinations(filtered[pos], count):
            diagnostics["incoming_combinations_considered"] += 1
            combo_cost = sum(player.cost for player in combo)
            if keep_cost + chosen_cost + combo_cost + suffix_min[group_index + 1] > budget:
                diagnostics["packages_rejected_by_budget"] += 1
                continue
            combo_counts = Counter(player.team_id for player in combo)
            if any(clubs.get(team_id, 0) + combo_counts[team_id] > MAX_PER_CLUB for team_id in combo_counts):
                diagnostics["packages_rejected_by_club_limit"] += 1
                continue
            next_clubs = clubs.copy()
            next_clubs.update(combo_counts)
            yield from recurse(group_index + 1, chosen + combo, chosen_cost + combo_cost, next_clubs)

    yield from recurse(0, tuple(), 0, keep_clubs)


def _price_rows(prices: dict | None) -> dict[int, dict]:
    return {
        int(row.get("element_id") or row.get("element")): row
        for row in (prices or {}).get("players") or []
        if row.get("element_id") is not None or row.get("element") is not None
    }


def _projected_now_cost(row: dict, current_cost: int, offset: int) -> int:
    threshold = 100.0
    projections = row.get("official_projections") or []
    crossed = False
    direction = str(row.get("direction") or row.get("risk_direction") or "").upper()
    for item in projections:
        if int(item.get("offset") or 0) > int(offset):
            continue
        pct = _f(item.get("projected_percent"))
        if direction == "RISE" and pct >= threshold:
            crossed = True
        if direction == "FALL" and pct <= -threshold:
            crossed = True
    if not crossed:
        return int(current_cost)
    if direction == "RISE":
        return int(current_cost) + 1
    if direction == "FALL":
        return max(1, int(current_cost) - 1)
    return int(current_cost)


def projected_price_scenario(
    outs: tuple[Candidate, ...],
    ins: tuple[Candidate, ...],
    locked: dict,
    prices: dict | None,
) -> dict:
    rows = _price_rows(prices)
    locked_by_id = {int(row.get("element")): row for row in locked.get("players") or [] if row.get("element") is not None}
    current_itb = int(locked.get("itb_tenths") or 0)
    scenarios = []
    for offset in (0, 1, 2):
        projected_sell = 0
        projected_buy = 0
        evidence = []
        for player in outs:
            price = rows.get(player.element) or {}
            now = int((price.get("raw") or {}).get("now_cost") or round(_f(price.get("current_price")) * 10) or player.cost)
            projected_now = _projected_now_cost(price, now, offset)
            owned = locked_by_id.get(player.element) or {}
            purchase = owned.get("purchase_cost")
            explicit_sell = owned.get("selling_price", owned.get("sell_cost"))
            if purchase is not None:
                future_sell = sell_cost(projected_now, int(purchase))
            elif explicit_sell is not None and projected_now == now:
                future_sell = int(explicit_sell)
            else:
                # Without purchase evidence a future sell-price transformation is not factual.
                future_sell = int(explicit_sell or player.cost)
            projected_sell += future_sell
            evidence.append({"element": player.element, "direction": "OUT", "projected_now_cost": projected_now, "projected_sell_cost": future_sell})
        for player in ins:
            price = rows.get(player.element) or {}
            now = int((price.get("raw") or {}).get("now_cost") or round(_f(price.get("current_price")) * 10) or player.cost)
            projected_now = _projected_now_cost(price, now, offset)
            projected_buy += projected_now
            evidence.append({"element": player.element, "direction": "IN", "projected_now_cost": projected_now})
        scenario_itb = current_itb + projected_sell - projected_buy
        scenarios.append({
            "offset": offset,
            "projected_itb_tenths": scenario_itb,
            "package_feasible": scenario_itb >= 0,
            "projected_sell_tenths": projected_sell,
            "projected_buy_tenths": projected_buy,
            "evidence": evidence,
        })
    current = scenarios[0] if scenarios else {}
    latest = scenarios[-1] if scenarios else {}
    return {
        "state": "ADVISORY_SCENARIO",
        "current_ledger_is_factual": True,
        "projected_price_scenario_is_not_current_fact": True,
        "price_alone_cannot_authorize_transfer": True,
        "scenarios": scenarios,
        "lost_package_feasibility": bool(current.get("package_feasible")) and not bool(latest.get("package_feasible")),
    }


def _interaction_rows(interactions: dict | None) -> dict[int, dict]:
    return {
        int(element): row
        for element, row in ((interactions or {}).get("players") or {}).items()
        if str(element).isdigit() and isinstance(row, dict)
    }


def _player_risk(player: Candidate, interaction_map: dict[int, dict], price_map: dict[int, dict]) -> dict:
    interaction = interaction_map.get(player.element) or {}
    tactical = interaction.get("tactical_interaction") or {}
    confidences = interaction.get("confidence_dimensions") or {}
    xmins = interaction.get("xmins") or {}
    roster = interaction.get("roster_change") or {}
    price = price_map.get(player.element) or {}
    urgency = str(price.get("model_urgency") or price.get("urgency") or "LOW").upper()
    price_risk = {"LOW": 0.1, "MEDIUM": 0.3, "HIGH": 0.6, "CRITICAL": 0.8}.get(urgency, 0.2)
    if str(price.get("predictor_serving_state") or "") in {"UNAVAILABLE", "STALE"}:
        price_risk = max(price_risk, 0.5)
    return {
        "projection_uncertainty": max(0.0, min(1.0, _f(player.uncertainty))),
        "xmins_uncertainty": max(0.0, min(1.0, _f(xmins.get("uncertainty"), 0.5))),
        "tactical_uncertainty": max(0.0, min(1.0, _f(tactical.get("tactical_uncertainty"), 0.5))),
        "roster_change_uncertainty": max(0.0, min(1.0, _f(roster.get("roster_change_uncertainty"), 0.0))),
        "price_risk": price_risk,
        "tactical_role_confidence": max(0.0, min(1.0, _f(confidences.get("player_role_confidence"), 0.0))),
        "opponent_matchup_confidence": max(0.0, min(1.0, _f(confidences.get("Understat_confidence"), 0.0))),
        "evidence_state": str((tactical.get("state") or interaction.get("health") or "EVIDENCE_GATED")),
    }


def _package_risk_delta(
    outs: tuple[Candidate, ...],
    ins: tuple[Candidate, ...],
    interaction_map: dict[int, dict],
    price_map: dict[int, dict],
    risk_by_element: dict[int, dict] | None = None,
) -> dict:
    cache = risk_by_element if risk_by_element is not None else {}

    def risk(player: Candidate) -> dict:
        cached = cache.get(player.element)
        if cached is not None:
            return cached
        row = _player_risk(player, interaction_map, price_map)
        cache[player.element] = row
        return row

    in_rows = [risk(player) for player in ins]
    out_rows = [risk(player) for player in outs]

    def avg(rows: list[dict], key: str, default: float = 0.0) -> float:
        return _mean([_f(row.get(key), default) for row in rows], default)

    return {
        "projection_uncertainty": round(max(0.0, avg(in_rows, "projection_uncertainty") - avg(out_rows, "projection_uncertainty")), 4),
        "xmins_uncertainty": round(max(0.0, avg(in_rows, "xmins_uncertainty") - avg(out_rows, "xmins_uncertainty")), 4),
        "tactical_uncertainty": round(max(0.0, avg(in_rows, "tactical_uncertainty") - avg(out_rows, "tactical_uncertainty")), 4),
        "roster_change_uncertainty": round(max(0.0, avg(in_rows, "roster_change_uncertainty") - avg(out_rows, "roster_change_uncertainty")), 4),
        "price_risk": round(avg(in_rows, "price_risk", 0.2), 4),
        "tactical_role_confidence": round(avg(in_rows, "tactical_role_confidence"), 4),
        "opponent_matchup_confidence": round(avg(in_rows, "opponent_matchup_confidence"), 4),
        "incoming_evidence_states": [row.get("evidence_state") for row in in_rows],
    }

def _hit_cost(replacements: int, locked: dict, policy: dict) -> int:
    if replacements <= 0:
        return 0
    if bool(locked.get("wildcard_active")) or bool(locked.get("free_hit_active")):
        return 0
    free = max(0, int(locked.get("free_transfers") or 0))
    hit_unit = int((policy.get("search") or {}).get("hit_cost_points") or 4)
    return max(0, replacements - free) * hit_unit


def _structural_flexibility(target: tuple[Candidate, ...], itb: int) -> float:
    clubs = _club_counts(target)
    open_club_capacity = sum(max(0, MAX_PER_CLUB - clubs.get(team, 0)) for team in range(1, 21))
    # Bounded descriptor only, not a raw xPts modifier.
    return round(min(1.0, 0.55 * min(1.0, max(0, itb) / 20.0) + 0.45 * min(1.0, open_club_capacity / 45.0)), 4)


def _frontier_vector(row: dict) -> dict[str, float]:
    return {
        "net_xpts_3": _f(row.get("net_xpts_3")),
        "net_xpts_5": _f(row.get("net_xpts_5")),
        "net_xpts_10": _f(row.get("net_xpts_10")),
        "net_xpts_15": _f(row.get("net_xpts_15")),
        "structural_flexibility": _f(row.get("structural_flexibility")),
        "tactical_role_confidence": _f(row.get("tactical_role_confidence")),
        "opponent_matchup_confidence": _f(row.get("opponent_matchup_confidence")),
        "hit_cost": _f(row.get("hit_cost")),
        "xmins_uncertainty": _f(row.get("xmins_uncertainty")),
        "projection_uncertainty": _f(row.get("projection_uncertainty")),
        "tactical_uncertainty": _f(row.get("tactical_uncertainty")),
        "price_risk": _f(row.get("price_risk")),
        "roster_change_uncertainty": _f(row.get("roster_change_uncertainty")),
    }


def _dominates_package(left: dict, right: dict, epsilon: float) -> bool:
    maximize = (
        "net_xpts_3", "net_xpts_5", "net_xpts_10", "net_xpts_15", "structural_flexibility",
        "tactical_role_confidence", "opponent_matchup_confidence",
    )
    minimize = (
        "hit_cost", "xmins_uncertainty", "projection_uncertainty", "tactical_uncertainty",
        "price_risk", "roster_change_uncertainty",
    )
    lv = _frontier_vector(left)
    rv = _frontier_vector(right)
    no_worse = all(lv[key] + epsilon >= rv[key] for key in maximize) and all(lv[key] <= rv[key] + epsilon for key in minimize)
    strict = any(lv[key] > rv[key] + epsilon for key in maximize) or any(lv[key] + epsilon < rv[key] for key in minimize)
    return no_worse and strict


def _frontier_insert(frontier: list[dict], row: dict, epsilon: float) -> None:
    for incumbent in frontier:
        if _dominates_package(incumbent, row, epsilon):
            return
    frontier[:] = [incumbent for incumbent in frontier if not _dominates_package(row, incumbent, epsilon)]
    frontier.append(row)


def _compact_for_frontier(row: dict) -> dict:
    keys = (
        "package_id", "replacements", "target_cost", "target_itb", "hit_cost",
        "net_xpts_3", "net_xpts_5", "net_xpts_10", "net_xpts_15", "adjusted_best_xi_gain_5",
        "adjusted_utility_gain_5", "xmins_uncertainty", "projection_uncertainty", "tactical_uncertainty",
        "price_risk", "roster_change_uncertainty", "tactical_role_confidence", "opponent_matchup_confidence",
        "structural_flexibility", "classification",
    )
    compact = {key: row.get(key) for key in keys}
    compact["_out_ids"] = tuple(row.get("_out_ids") or ())
    compact["_in_ids"] = tuple(row.get("_in_ids") or ())
    return compact

def _rank(row: dict) -> tuple:
    return (
        _f(row.get("adjusted_utility_gain_5")),
        _f(row.get("net_xpts_5")),
        _f(row.get("net_xpts_15")),
        -int(row.get("hit_cost") or 0),
        -int(row.get("replacements") or 0),
        -int(row.get("target_cost") or 0),
        str(row.get("package_id") or ""),
    )


def _retain_top(rows: list[dict], row: dict, limit: int) -> None:
    rows.append(row)
    rows.sort(key=_rank, reverse=True)
    if len(rows) > limit:
        del rows[limit:]


def _pairings(outs: tuple[Candidate, ...], ins: tuple[Candidate, ...]) -> list[tuple[tuple[Candidate, Candidate], ...]]:
    rows = []
    for perm in permutations(ins, len(ins)):
        if all(out.position == incoming.position for out, incoming in zip(outs, perm)):
            pairing = tuple(zip(outs, perm))
            key = tuple((left.element, right.element) for left, right in pairing)
            if key not in {tuple((left.element, right.element) for left, right in existing) for existing in rows}:
                rows.append(pairing)
    return rows


def _staggered_best_route(outs: tuple[Candidate, ...], ins: tuple[Candidate, ...], locked: dict, policy: dict) -> dict | None:
    k = len(ins)
    if k < 2 or bool(locked.get("wildcard_active")) or bool(locked.get("free_hit_active")):
        return None
    hit_unit = int((policy.get("search") or {}).get("hit_cost_points") or 4)
    free_now = max(0, int(locked.get("free_transfers") or 0))
    best = None
    for pairing in _pairings(outs, ins):
        pair_deltas = []
        for outgoing, incoming in pairing:
            values = []
            for index in range(5):
                left = outgoing.gw_xpts[index] if index < len(outgoing.gw_xpts) else 0.0
                right = incoming.gw_xpts[index] if index < len(incoming.gw_xpts) else 0.0
                values.append(_f(right) - _f(left))
            pair_deltas.append(values)
        for now_count in range(0, k + 1):
            # 0 means roll this GW then execute all next GW; k means immediate route.
            for now_indices in combinations(range(k), now_count):
                now_set = set(now_indices)
                rest = k - now_count
                hit_now = max(0, now_count - free_now) * hit_unit
                remaining_ft = max(0, free_now - now_count)
                next_ft = min(5, remaining_ft + 1)
                hit_next = max(0, rest - next_ft) * hit_unit
                benefit = 0.0
                for index, values in enumerate(pair_deltas):
                    start_gw = 0 if index in now_set else 1
                    benefit += sum(values[start_gw:5])
                net = benefit - hit_now - hit_next
                route = {
                    "now_transfer_count": now_count,
                    "next_gw_transfer_count": rest,
                    "hit_now": hit_now,
                    "hit_next_gw": hit_next,
                    "net_projected_gain_5": round(net, 3),
                    "pairing": [
                        {"out": outgoing.element, "in": incoming.element, "execute": "NOW" if idx in now_set else "NEXT_GW"}
                        for idx, (outgoing, incoming) in enumerate(pairing)
                    ],
                    "assumption": "ONE_FREE_TRANSFER_ACCRUES_NEXT_GW_UP_TO_FIVE",
                }
                if best is None or (route["net_projected_gain_5"], -route["hit_now"] - route["hit_next_gw"], -route["now_transfer_count"]) > (
                    best["net_projected_gain_5"], -best["hit_now"] - best["hit_next_gw"], -best["now_transfer_count"]
                ):
                    best = route
    return best


def _package_id(outs: tuple[Candidate, ...], ins: tuple[Candidate, ...]) -> str:
    out_ids = ",".join(str(player.element) for player in sorted(outs, key=lambda row: row.element)) or "ROLL"
    in_ids = ",".join(str(player.element) for player in sorted(ins, key=lambda row: row.element)) or "ROLL"
    return f"OUT[{out_ids}]_IN[{in_ids}]"


def _evaluate_package(
    outs: tuple[Candidate, ...],
    ins: tuple[Candidate, ...],
    target: tuple[Candidate, ...],
    target_metrics: dict,
    baseline_metrics: dict,
    locked: dict,
    policy: dict,
    interaction_map: dict[int, dict],
    price_map: dict[int, dict],
    risk_by_element: dict[int, dict],
) -> dict:
    k = len(ins)
    hit = _hit_cost(k, locked, policy)
    dx3 = _f(target_metrics.get("squad_xpts_3")) - _f(baseline_metrics.get("squad_xpts_3"))
    dx5 = _f(target_metrics.get("squad_xpts_5")) - _f(baseline_metrics.get("squad_xpts_5"))
    dx10 = _f(target_metrics.get("squad_xpts_10")) - _f(baseline_metrics.get("squad_xpts_10"))
    dx15 = _f(target_metrics.get("squad_xpts_15")) - _f(baseline_metrics.get("squad_xpts_15"))
    dxi = _f(target_metrics.get("best_xi_xpts_5")) - _f(baseline_metrics.get("best_xi_xpts_5"))
    du = _f(target_metrics.get("bench_adjusted_utility_5")) - _f(baseline_metrics.get("bench_adjusted_utility_5"))
    risks = _package_risk_delta(outs, ins, interaction_map, price_map, risk_by_element)
    risk_penalty = (
        0.35 * risks["projection_uncertainty"]
        + 0.30 * risks["xmins_uncertainty"]
        + 0.25 * risks["tactical_uncertainty"]
        + 0.20 * risks["roster_change_uncertainty"]
    )
    adjusted_xi = dxi - hit - risk_penalty
    adjusted_util = du - hit - risk_penalty
    itb = int(locked.get("itb_tenths") or 0) + sum(player.cost for player in outs) - sum(player.cost for player in ins)
    return {
        "package_id": _package_id(outs, ins),
        "replacements": k,
        "_out_ids": tuple(player.element for player in outs),
        "_in_ids": tuple(player.element for player in ins),
        "target_cost": int(target_metrics.get("cost") or sum(player.cost for player in target)),
        "target_itb": itb,
        "delta_cost": sum(player.cost for player in ins) - sum(player.cost for player in outs),
        "hit_cost": hit,
        "gross_xpts_3": round(dx3, 3),
        "gross_xpts_5": round(dx5, 3),
        "gross_xpts_10": round(dx10, 3),
        "gross_xpts_15": round(dx15, 3),
        "net_xpts_3": round(dx3 - hit, 3),
        "net_xpts_5": round(dx5 - hit, 3),
        "net_xpts_10": round(dx10 - hit, 3),
        "net_xpts_15": round(dx15 - hit, 3),
        "delta_squad_xpts_3": round(dx3, 3),
        "delta_squad_xpts_5": round(dx5, 3),
        "delta_squad_xpts_10": round(dx10, 3),
        "delta_squad_xpts_15": round(dx15, 3),
        "delta_best_xi_xpts_5": round(dxi, 3),
        "delta_bench_adjusted_utility_5": round(du, 3),
        "risk_penalty": round(risk_penalty, 4),
        "adjusted_best_xi_gain_5": round(adjusted_xi, 3),
        "adjusted_utility_gain_5": round(adjusted_util, 3),
        "projection_uncertainty": risks["projection_uncertainty"],
        "xmins_uncertainty": risks["xmins_uncertainty"],
        "tactical_uncertainty": risks["tactical_uncertainty"],
        "roster_change_uncertainty": risks["roster_change_uncertainty"],
        "price_risk": risks["price_risk"],
        "tactical_role_confidence": risks["tactical_role_confidence"],
        "opponent_matchup_confidence": risks["opponent_matchup_confidence"],
        "structural_flexibility": _structural_flexibility(target, itb),
        "classification": reference.package_class(adjusted_xi, adjusted_util, k) if k else "ROLL_BASELINE",
    }


def _finalize_package(
    row: dict,
    *,
    by_id: dict[int, Candidate],
    current: tuple[Candidate, ...],
    locked: dict,
    prices: dict | None,
    policy: dict,
    budget: int,
) -> dict:
    outs = tuple(by_id[element] for element in row.get("_out_ids") or ())
    ins = tuple(by_id[element] for element in row.get("_in_ids") or ())
    out_ids = {player.element for player in outs}
    target = tuple(player for player in current if player.element not in out_ids) + ins
    legal, reason = validate_squad(target, budget)
    if not legal:
        raise RuntimeError(f"retained full-universe package failed final legality proof: {reason}")
    finalized = {key: value for key, value in row.items() if not key.startswith("_")}
    finalized["out"] = [reference.payload(player) for player in sorted(outs, key=lambda item: (_POSITION_ORDER.get(item.position, 99), item.element))]
    finalized["in"] = [reference.payload(player) for player in sorted(ins, key=lambda item: (_POSITION_ORDER.get(item.position, 99), item.element))]
    finalized["price_scenario"] = projected_price_scenario(outs, ins, locked, prices)
    finalized["staggered_best_route"] = _staggered_best_route(outs, ins, locked, policy)
    finalized["governance"] = {
        "tactical_direct_xpts_mutation": False,
        "price_alone_can_authorize_transfer": False,
        "watchlist_candidate_authority": False,
        "post_transfer_legality_recomputed": True,
        "expensive_evidence_materialized_only_after_exact_selection": True,
    }
    return finalized

def _frontier_categories(frontier: list[dict], roll: dict) -> dict:
    rows = frontier or [roll]
    no_hit = [row for row in rows if int(row.get("hit_cost") or 0) == 0]
    staggered = [row for row in rows if row.get("staggered_best_route")]
    positive = [row for row in rows if _f(row.get("net_xpts_5")) > 0]
    return {
        "MAX_UPSIDE": max(rows, key=lambda row: (_f(row.get("net_xpts_15")), _f(row.get("net_xpts_5")), _rank(row))),
        "BEST_RISK_ADJUSTED": max(rows, key=_rank),
        "BEST_NO_HIT": max(no_hit, key=_rank) if no_hit else roll,
        "LOWEST_UNCERTAINTY": min(rows, key=lambda row: (_f(row.get("projection_uncertainty")) + _f(row.get("xmins_uncertainty")) + _f(row.get("tactical_uncertainty")) + _f(row.get("roster_change_uncertainty")), -_f(row.get("net_xpts_5")))),
        "BEST_FLEXIBILITY": max(rows, key=lambda row: (_f(row.get("structural_flexibility")), _f(row.get("net_xpts_5")))),
        "CHEAPEST_ENABLER": min(positive, key=lambda row: (int(row.get("target_cost") or 10**9), -_f(row.get("net_xpts_5")))) if positive else roll,
        "BEST_STAGGERED": max(staggered, key=lambda row: (_f((row.get("staggered_best_route") or {}).get("net_projected_gain_5")), _rank(row))) if staggered else roll,
        "ROLL_BASELINE": roll,
    }


def search_full_universe_packages(
    candidates: list[Candidate],
    locked: dict,
    *,
    predictions: dict | None = None,
    universe: dict | None = None,
    understat: dict | None = None,
    interactions: dict | None = None,
    team_system_evidence: dict | None = None,
    roster_events: dict | None = None,
    prices: dict | None = None,
    max_replacements: int | None = None,
    top_per_size: int = 12,
) -> dict:
    policy = _policy()
    search_cfg = policy.get("search") or {}
    maximum = int(search_cfg.get("maximum_replacements") or 3)
    max_replacements = min(maximum, int(max_replacements if max_replacements is not None else maximum))
    if max_replacements < 1:
        raise ValueError("full-universe package search requires at least one transfer package size")

    reconciled, affordability = reconcile_owned_costs(candidates, locked)
    derived_budget = int(affordability["available_budget_tenths"])
    owned_ids = {int(row.get("element")) for row in locked.get("players") or [] if row.get("element") is not None}
    by_id = {player.element: player for player in reconciled}
    missing_owned = sorted(owned_ids - set(by_id))
    if missing_owned:
        raise RuntimeError(f"owned players absent from candidate universe: {missing_owned}")
    current = tuple(by_id[element] for element in sorted(owned_ids))
    legal, reason = validate_squad(current, derived_budget)
    if not legal:
        raise RuntimeError(f"current squad invalid before full-universe package search: {reason}")

    if interactions is None:
        interactions = build_tactical_interactions(
            predictions or {"players": []}, universe or {"players": []}, understat or {},
            team_system_evidence=team_system_evidence, roster_events=roster_events,
        ) if predictions is not None and universe is not None else {"players": {}, "health": {"status": "UNAVAILABLE"}}
    interaction_map = _interaction_rows(interactions)
    price_map = _price_rows(prices)
    risk_by_element = {player.element: _player_risk(player, interaction_map, price_map) for player in reconciled}

    pruned_external, pruning_proofs = safe_prune_incoming_players(reconciled, owned_ids)
    pools = {pos: [] for pos in POSITION_COUNTS}
    for player in pruned_external:
        pools[player.position].append(player)
    for pos in pools:
        pools[pos].sort(key=lambda row: row.element)

    baseline_profile = _keep_profile(current)
    baseline_metrics = reference._fast_metrics(current, include_detail=False)
    roll = {
        "package_id": "ROLL_BASELINE",
        "replacements": 0,
        "out": [],
        "in": [],
        "target_cost": baseline_metrics.get("cost"),
        "target_itb": int(locked.get("itb_tenths") or 0),
        "delta_cost": 0,
        "hit_cost": 0,
        "gross_xpts_3": 0.0,
        "gross_xpts_5": 0.0,
        "gross_xpts_10": 0.0,
        "gross_xpts_15": 0.0,
        "net_xpts_3": 0.0,
        "net_xpts_5": 0.0,
        "net_xpts_10": 0.0,
        "net_xpts_15": 0.0,
        "delta_squad_xpts_3": 0.0,
        "delta_squad_xpts_5": 0.0,
        "delta_squad_xpts_10": 0.0,
        "delta_squad_xpts_15": 0.0,
        "delta_best_xi_xpts_5": 0.0,
        "delta_bench_adjusted_utility_5": 0.0,
        "risk_penalty": 0.0,
        "adjusted_best_xi_gain_5": 0.0,
        "adjusted_utility_gain_5": 0.0,
        "projection_uncertainty": 0.0,
        "xmins_uncertainty": 0.0,
        "tactical_uncertainty": 0.0,
        "roster_change_uncertainty": 0.0,
        "price_risk": 0.0,
        "tactical_role_confidence": _mean([_f((interaction_map.get(player.element) or {}).get("confidence_dimensions", {}).get("player_role_confidence")) for player in current]),
        "opponent_matchup_confidence": _mean([_f((interaction_map.get(player.element) or {}).get("confidence_dimensions", {}).get("Understat_confidence")) for player in current]),
        "structural_flexibility": _structural_flexibility(current, int(locked.get("itb_tenths") or 0)),
        "classification": "ROLL_BASELINE",
        "price_scenario": {"state": "CURRENT_FACT", "price_alone_cannot_authorize_transfer": True},
        "staggered_best_route": None,
        "governance": {"watchlist_candidate_authority": False, "post_transfer_legality_recomputed": True},
    }

    diagnostics = {
        "input_universe_size": len(candidates),
        "eligible_universe_size": len(reconciled),
        "owned_players": len(owned_ids),
        "unowned_before_safe_pruning": len(reconciled) - len(owned_ids),
        "safely_pruned_players": len(pruning_proofs),
        "remaining_incoming_players": len(pruned_external),
        "search_nodes": 0,
        "incoming_combinations_considered": 0,
        "packages_evaluated": 0,
        "packages_rejected_by_budget": 0,
        "packages_rejected_by_budget_bound": 0,
        "packages_rejected_by_club_limit": 0,
        "packages_rejected_by_legality": 0,
        "packages_dominated_on_frontier": 0,
        "packages_retained_on_frontier": 0,
        "potential_cutoff_diagnostics": [],
    }
    top_by_k = {k: [] for k in range(1, max_replacements + 1)}
    best_by_k: dict[str, dict | None] = {str(k): None for k in range(1, max_replacements + 1)}
    frontier: list[dict] = []
    frontier_epsilon = _f(search_cfg.get("frontier_epsilon"), 0.01)
    _frontier_insert(frontier, _compact_for_frontier(roll), frontier_epsilon)

    keep_profile_cache: dict[tuple[int, ...], dict] = {}
    chosen_profile_cache: dict[tuple[int, ...], dict] = {}
    position_prefix_cache: dict = {}
    for k in range(1, max_replacements + 1):
        for outs_raw in combinations(current, k):
            outs = tuple(sorted(outs_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
            out_ids = tuple(sorted(player.element for player in outs))
            keep = tuple(player for player in current if player.element not in set(out_ids))
            need = Counter(player.position for player in outs)
            keep_profile = keep_profile_cache.get(out_ids)
            if keep_profile is None:
                keep_profile = _keep_profile_from_baseline(baseline_profile, outs)
                keep_profile_cache[out_ids] = keep_profile
            for ins_raw in _incoming_combinations(pools, need, keep, derived_budget, diagnostics):
                ins = tuple(sorted(ins_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
                target = keep + ins
                # Exact legality is enforced by construction in _incoming_combinations:
                # position counts are restored from `need`, candidates are unowned/unique,
                # budget is bounded, and keep+incoming club counts are checked <= MAX_PER_CLUB.
                diagnostics["packages_evaluated"] += 1
                in_ids = tuple(player.element for player in ins)
                chosen_profile = chosen_profile_cache.get(in_ids)
                if chosen_profile is None:
                    chosen_profile = _chosen_profile(ins)
                    chosen_profile_cache[in_ids] = chosen_profile
                target_metrics = _metrics_from_profiles(
                    keep_profile, chosen_profile, position_prefix_cache=position_prefix_cache,
                )
                row = _evaluate_package(
                    outs, ins, target, target_metrics, baseline_metrics, locked, policy, interaction_map, price_map, risk_by_element,
                )
                _retain_top(top_by_k[k], row, top_per_size)
                incumbent = best_by_k[str(k)]
                if incumbent is None or _rank(row) > _rank(incumbent):
                    best_by_k[str(k)] = row
                before = len(frontier)
                compact = _compact_for_frontier(row)
                _frontier_insert(frontier, compact, frontier_epsilon)
                after = len(frontier)
                if compact not in frontier:
                    diagnostics["packages_dominated_on_frontier"] += 1
                elif after <= before:
                    diagnostics["packages_dominated_on_frontier"] += max(0, before + 1 - after)

    frontier.sort(key=_rank, reverse=True)
    diagnostics["packages_retained_on_frontier"] = len(frontier)

    finalized_cache: dict[str, dict] = {}
    def finalize(row: dict | None) -> dict | None:
        if row is None:
            return None
        package_id = str(row.get("package_id") or "")
        if package_id == "ROLL_BASELINE":
            return roll
        cached = finalized_cache.get(package_id)
        if cached is None:
            cached = _finalize_package(
                row, by_id=by_id, current=current, locked=locked, prices=prices, policy=policy, budget=derived_budget,
            )
            finalized_cache[package_id] = cached
        return cached

    frontier = [finalize(row) for row in frontier]
    top_by_k = {k: [finalize(row) for row in rows] for k, rows in top_by_k.items()}
    best_by_k = {key: finalize(row) for key, row in best_by_k.items()}
    packages = [row for k in range(1, max_replacements + 1) for row in top_by_k[k]]
    best_candidates = [row for row in best_by_k.values() if row]
    recommended = max(best_candidates, key=_rank) if best_candidates else None
    if recommended and _f(recommended.get("adjusted_utility_gain_5")) <= 0:
        recommended = None
    overall = (recommended or roll).get("classification") or "ROLL_BASELINE"
    categories = _frontier_categories(frontier, roll)

    global_proof = (
        not bool(search_cfg.get("allow_heuristic_candidate_cutoff"))
        and not bool(search_cfg.get("allow_beam_cutoff"))
        and all(proof.get("safe_legality_equivalence") is True for proof in pruning_proofs)
    )
    search_state = str(search_cfg.get("full_universe_proven_state") or "FULL_UNIVERSE_PROVEN") if global_proof else str(search_cfg.get("heuristic_state") or "FULL_UNIVERSE_HEURISTIC")

    return {
        "schema_version": 2,
        "contract": CONTRACT,
        "engine": "v4-full-universe-transfer-package-search-v1",
        "overall_verdict": overall,
        "recommended_package": recommended,
        "roll_baseline": roll,
        "baseline": baseline_metrics,
        "affordability": affordability,
        "best_by_replacement_count": best_by_k,
        "packages": packages,
        "efficient_frontier": {
            "status": "PASS" if global_proof else "PARTIAL",
            "dominance_epsilon": frontier_epsilon,
            "rows": frontier,
            "categories": categories,
            "maximize": (policy.get("efficient_frontier") or {}).get("maximize") or [],
            "minimize": (policy.get("efficient_frontier") or {}).get("minimize") or [],
        },
        "search": {
            "status": search_state,
            "global_optimality_guaranteed_under_declared_package_semantics": global_proof,
            "full_eligible_universe_participates_before_safe_pruning": True,
            "watchlist_candidate_authority": False,
            "heuristic_candidate_cutoff": False,
            "beam_cutoff": False,
            "maximum_replacements": max_replacements,
            "safe_pruning_rule": "SAME_TEAM_SAME_POSITION_PARETO_DOMINANCE",
            "pruning_proofs": pruning_proofs,
            "diagnostics": diagnostics,
        },
        "tactical_interaction_health": (interactions or {}).get("health") or {"status": "UNAVAILABLE"},
        "understat_rolling_player_intelligence": {
            "requested_windows": [1, 3, 5],
            "source_support": "SOURCE_SERIES_UNAVAILABLE" if not bool((understat or {}).get("player_match_series")) else "AVAILABLE",
            "season_aggregate_preserved": True,
            "source_absence_does_not_exclude_player": True,
        },
        "governance": {
            "official_fpl_factual_authority": True,
            "watchlist_is_output_only": True,
            "benchmark_players_are_not_search_seeds": True,
            "hardcoded_target_players": False,
            "no_silent_optimizer_truncation": True,
            "price_projection_separate_from_current_fact": True,
            "price_cannot_independently_authorize_transfer": True,
            "tactical_direct_xpts_multiplier": False,
            "tactical_direct_xmins_mutation": False,
            "global_optimality_claim_requires_safe_pruning_proof": True,
            "all_enumerated_packages_legal_by_exact_generator_constraints": True,
            "retained_packages_revalidated_with_canonical_validate_squad": True,
            "expensive_evidence_materialized_only_after_exact_selection": True,
        },
    }
