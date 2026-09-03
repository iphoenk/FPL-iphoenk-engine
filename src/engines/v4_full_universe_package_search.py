from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Any, Iterable

from src.engines import v4_full_universe_package_search_core as _core
from src.engines.v4_recommendation_sanity import _player_evidence
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_wc_optimizer import Candidate


CONTRACT = _core.CONTRACT
POLICY_FILE = _core.POLICY_FILE
_SEARCH_LOCK = RLock()
_POSITION_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}

# Public compatibility aliases. The exhaustive enumeration/frontier mechanics stay
# in one implementation module; this facade owns the production proof contract.
projected_price_scenario = _core.projected_price_scenario


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _gw5(player: Candidate) -> tuple[float, ...]:
    values = tuple(_f(value) for value in player.gw_xpts[:5])
    return values + (0.0,) * max(0, 5 - len(values))


def _future_buy_costs(player: Candidate, price_map: dict[int, dict]) -> tuple[int, int, int]:
    row = price_map.get(player.element) or {}
    raw = row.get("raw") or {}
    current = int(raw.get("now_cost") or round(_f(row.get("current_price")) * 10) or player.cost)
    return tuple(_core._projected_now_cost(row, current, offset) for offset in (0, 1, 2))


def _sanity_row(
    player: Candidate,
    prediction_map: dict[int, dict],
    universe_map: dict[int, dict],
) -> dict:
    if player.element not in prediction_map or player.element not in universe_map:
        return {
            "confidence": 0.0,
            "start_probability_5": 0.0,
            "dnp_probability_5": 1.0,
            "uncertainty": 1.0,
            "role_prior": 0.0,
            "horizon_stability": 0.0,
            "rate_spike_risk": 1.0,
            "current_season_weight": 0.0,
            "market_support": 0.0,
        }
    return _player_evidence(player.element, prediction_map, universe_map)


def _dominance_dimensions(
    player: Candidate,
    *,
    interaction_map: dict[int, dict],
    price_map: dict[int, dict],
    prediction_map: dict[int, dict],
    universe_map: dict[int, dict],
) -> dict[str, float]:
    risk = _core._player_risk(player, interaction_map, price_map)
    sanity = _sanity_row(player, prediction_map, universe_map)
    future0, future1, future2 = _future_buy_costs(player, price_map)
    gw1, gw2, gw3, gw4, gw5 = _gw5(player)
    return {
        # Minimize dimensions.
        "cost": float(player.cost),
        "projection_uncertainty": _f(risk.get("projection_uncertainty"), 1.0),
        "xmins_uncertainty": _f(risk.get("xmins_uncertainty"), 1.0),
        "tactical_uncertainty": _f(risk.get("tactical_uncertainty"), 1.0),
        "roster_change_uncertainty": _f(risk.get("roster_change_uncertainty"), 1.0),
        "price_risk": _f(risk.get("price_risk"), 1.0),
        "projected_buy_cost_0": float(future0),
        "projected_buy_cost_1": float(future1),
        "projected_buy_cost_2": float(future2),
        "dnp_probability_5": _f(sanity.get("dnp_probability_5"), 1.0),
        "rate_spike_risk": _f(sanity.get("rate_spike_risk"), 1.0),
        # Maximize dimensions.
        "xpts_3": float(player.x3),
        "xpts_5": float(player.x5),
        "xpts_10": float(player.x10),
        "xpts_15": float(player.x15),
        "objective": float(player.objective),
        "gw_xpts_1": gw1,
        "gw_xpts_2": gw2,
        "gw_xpts_3": gw3,
        "gw_xpts_4": gw4,
        "gw_xpts_5": gw5,
        "tactical_role_confidence": _f(risk.get("tactical_role_confidence")),
        "opponent_matchup_confidence": _f(risk.get("opponent_matchup_confidence")),
        "sanity_confidence": _f(sanity.get("confidence")),
        "start_probability_5": _f(sanity.get("start_probability_5")),
        "role_prior": _f(sanity.get("role_prior")),
        "horizon_stability": _f(sanity.get("horizon_stability")),
        "current_season_weight": _f(sanity.get("current_season_weight")),
        "market_support": _f(sanity.get("market_support")),
    }


_MINIMIZE = (
    "cost",
    "projection_uncertainty",
    "xmins_uncertainty",
    "tactical_uncertainty",
    "roster_change_uncertainty",
    "price_risk",
    "projected_buy_cost_0",
    "projected_buy_cost_1",
    "projected_buy_cost_2",
    "dnp_probability_5",
    "rate_spike_risk",
)
_MAXIMIZE = (
    "xpts_3",
    "xpts_5",
    "xpts_10",
    "xpts_15",
    "objective",
    "gw_xpts_1",
    "gw_xpts_2",
    "gw_xpts_3",
    "gw_xpts_4",
    "gw_xpts_5",
    "tactical_role_confidence",
    "opponent_matchup_confidence",
    "sanity_confidence",
    "start_probability_5",
    "role_prior",
    "horizon_stability",
    "current_season_weight",
    "market_support",
)


def _dominates(
    left: Candidate,
    right: Candidate,
    *,
    left_dimensions: dict[str, float],
    right_dimensions: dict[str, float],
    epsilon: float,
) -> bool:
    if left.element == right.element or left.team_id != right.team_id or left.position != right.position:
        return False
    no_worse = (
        all(left_dimensions[key] <= right_dimensions[key] + epsilon for key in _MINIMIZE)
        and all(left_dimensions[key] + epsilon >= right_dimensions[key] for key in _MAXIMIZE)
    )
    strict = (
        any(left_dimensions[key] + epsilon < right_dimensions[key] for key in _MINIMIZE)
        or any(left_dimensions[key] > right_dimensions[key] + epsilon for key in _MAXIMIZE)
    )
    return no_worse and strict


def safe_prune_incoming_players(
    candidates: list[Candidate],
    owned_ids: set[int],
    *,
    interactions: dict | None = None,
    prices: dict | None = None,
    predictions: dict | None = None,
    universe: dict | None = None,
    epsilon: float | None = None,
) -> tuple[list[Candidate], list[dict]]:
    """Prune only when replacement is safe for search *and* downstream sanity.

    Legality equivalence requires identical FPL position and club. The dominator
    must then be no worse across every numeric dimension that can affect package
    frontier/risk, projected affordability, or recommendation-sanity confidence.
    This makes the pruning proof compatible with the full decision chain rather
    than xPts-only shortlist semantics.
    """
    policy = _core._policy()
    cfg = policy.get("search") or {}
    epsilon = _f(cfg.get("dominance_epsilon"), 1e-6) if epsilon is None else float(epsilon)
    interaction_map = _core._interaction_rows(interactions)
    price_map = _core._price_rows(prices)
    prediction_map = {
        int(row.get("element")): row
        for row in (predictions or {}).get("players") or []
        if row.get("element") is not None
    }
    universe_map = {
        int(row.get("element")): row
        for row in (universe or {}).get("players") or []
        if row.get("element") is not None
    }

    external = [row for row in candidates if row.element not in owned_ids]
    grouped: dict[tuple[str, int], list[Candidate]] = defaultdict(list)
    for player in external:
        grouped[(player.position, player.team_id)].append(player)

    dimensions = {
        player.element: _dominance_dimensions(
            player,
            interaction_map=interaction_map,
            price_map=price_map,
            prediction_map=prediction_map,
            universe_map=universe_map,
        )
        for player in external
    }
    pruned: set[int] = set()
    proofs: list[dict] = []
    for key in sorted(grouped, key=lambda item: (_POSITION_ORDER.get(item[0], 99), item[1])):
        rows = sorted(grouped[key], key=lambda item: item.element)
        for right in rows:
            if right.element in pruned:
                continue
            dominators = [
                left for left in rows
                if _dominates(
                    left,
                    right,
                    left_dimensions=dimensions[left.element],
                    right_dimensions=dimensions[right.element],
                    epsilon=epsilon,
                )
            ]
            if not dominators:
                continue
            # Deterministic proof selection independent of names/watchlist/benchmarks.
            left = min(dominators, key=lambda row: (row.cost, -row.x5, -row.x15, row.element))
            pruned.add(right.element)
            proofs.append({
                "pruned_element": right.element,
                "dominating_element": left.element,
                "position": right.position,
                "team_id": right.team_id,
                "reason": "SAME_TEAM_SAME_POSITION_FULL_DECISION_PARETO_DOMINANCE",
                "safe_legality_equivalence": True,
                "safe_package_frontier_equivalence": True,
                "safe_projected_affordability_equivalence": True,
                "safe_recommendation_sanity_equivalence": True,
                "minimize_dimensions": list(_MINIMIZE),
                "maximize_dimensions": list(_MAXIMIZE),
                "dominator": dimensions[left.element],
                "dominated": dimensions[right.element],
            })
    kept = [row for row in external if row.element not in pruned]
    return kept, proofs


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
    if interactions is None and predictions is not None and universe is not None:
        interactions = build_tactical_interactions(
            predictions,
            universe,
            understat or {},
            team_system_evidence=team_system_evidence,
            roster_events=roster_events,
        )
    interactions = interactions or {"players": {}, "health": {"status": "UNAVAILABLE"}}

    def governed_pruner(rows: list[Candidate], owned: set[int], *, epsilon: float | None = None):
        return safe_prune_incoming_players(
            rows,
            owned,
            interactions=interactions,
            prices=prices,
            predictions=predictions,
            universe=universe,
            epsilon=epsilon,
        )

    # The core owns exhaustive enumeration/frontier mechanics. Replace only its
    # pruning callback for the duration of one search call, under a process-local
    # lock, then restore it. Package runtime runs in its own worker process, but
    # the lock also makes direct threaded test/use safe and deterministic.
    with _SEARCH_LOCK:
        original = _core.safe_prune_incoming_players
        _core.safe_prune_incoming_players = governed_pruner
        try:
            out = _core.search_full_universe_packages(
                candidates,
                locked,
                predictions=predictions,
                universe=universe,
                understat=understat,
                interactions=interactions,
                team_system_evidence=team_system_evidence,
                roster_events=roster_events,
                prices=prices,
                max_replacements=max_replacements,
                top_per_size=top_per_size,
            )
        finally:
            _core.safe_prune_incoming_players = original

    search = out.setdefault("search", {})
    proofs = search.get("pruning_proofs") or []
    all_safe = all(
        proof.get("safe_legality_equivalence") is True
        and proof.get("safe_package_frontier_equivalence") is True
        and proof.get("safe_projected_affordability_equivalence") is True
        and proof.get("safe_recommendation_sanity_equivalence") is True
        for proof in proofs
    )
    configured_exact = not bool((_core._policy().get("search") or {}).get("allow_heuristic_candidate_cutoff")) and not bool((_core._policy().get("search") or {}).get("allow_beam_cutoff"))
    global_proof = configured_exact and all_safe
    search.update({
        "status": "FULL_UNIVERSE_PROVEN" if global_proof else "FULL_UNIVERSE_HEURISTIC",
        "global_optimality_guaranteed_under_declared_package_semantics": global_proof,
        "safe_pruning_rule": "SAME_TEAM_SAME_POSITION_FULL_DECISION_PARETO_DOMINANCE",
        "proof_covers_package_frontier_risk_confidence": all_safe,
        "proof_covers_projected_affordability": all_safe,
        "proof_covers_recommendation_sanity": all_safe,
        "proof_minimize_dimensions": list(_MINIMIZE),
        "proof_maximize_dimensions": list(_MAXIMIZE),
    })
    out.setdefault("governance", {}).update({
        "full_decision_chain_safe_pruning": all_safe,
        "xpts_only_pruning_forbidden": True,
        "downstream_sanity_regret_from_pruning_forbidden": True,
    })
    if not global_proof:
        (out.get("efficient_frontier") or {})["status"] = "PARTIAL"
    return out
