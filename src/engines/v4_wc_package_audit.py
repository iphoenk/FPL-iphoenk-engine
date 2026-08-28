from __future__ import annotations

"""Shared package-audit primitives and compatibility delegates.

Authoritative package search is owned by ``v4_wc_package_audit_fast``.  This
module keeps only reusable formatting/metric/frontier primitives plus thin legacy
entry points, so there is exactly one package-search algorithm in V4.
"""

from src.engines.v4_optimizer_primitives import gw_value as _gw_value
from src.engines.v4_wc_optimizer import (
    POSITION_COUNTS,
    best_xi,
    build_candidates,
    _best_xi_score_grouped,
    _group_by_position,
)


def payload(player):
    return {
        "element": player.element,
        "name": player.name,
        "position": player.position,
        "team": player.team,
        "team_id": player.team_id,
        "cost": player.cost,
        "xpts_3": round(player.x3, 2),
        "xpts_5": round(player.x5, 2),
        "xpts_10": round(player.x10, 2),
        "xpts_15": round(player.x15, 2),
        "uncertainty": round(player.uncertainty, 3),
        "objective": round(player.objective, 4),
    }


def package_class(delta_xi, delta_utility, replacements):
    xi_required = {1: 1.5, 2: 2.5, 3: 3.5, 4: 4.5}[replacements]
    utility_required = {1: 1.8, 2: 3.0, 3: 4.2, 4: 5.4}[replacements]
    if delta_xi >= xi_required and delta_utility >= utility_required:
        return "MATERIAL_UPGRADE"
    if delta_xi >= xi_required * 0.55 and delta_utility >= utility_required * 0.55:
        return "OPTIONAL_IMPROVEMENT"
    return "KEEP_BASELINE"


def _package_class(delta_x5, delta_obj, replacements):
    return package_class(delta_x5, delta_obj, replacements)


def _fast_metrics(players, include_detail=False):
    """Canonical package metric primitive shared by the exact-fast audit."""
    rows = list(players)
    grouped = _group_by_position(rows)
    xi5 = 0.0
    utility5 = 0.0
    detail = []
    for index in range(5):
        score = _best_xi_score_grouped(grouped, index)
        total = sum(_gw_value(player, index) for player in rows)
        xi5 += score
        utility5 += score + 0.12 * (total - score)
        if include_detail:
            _score, ids = best_xi(rows, index)
            detail.append({"gw_offset": index + 1, "xpts": round(score, 2), "elements": ids})
    out = {
        "cost": sum(player.cost for player in rows),
        "objective": round(sum(player.objective for player in rows), 4),
        "squad_xpts_3": round(sum(player.x3 for player in rows), 2),
        "squad_xpts_5": round(sum(player.x5 for player in rows), 2),
        "squad_xpts_10": round(sum(player.x10 for player in rows), 2),
        "squad_xpts_15": round(sum(player.x15 for player in rows), 2),
        "best_xi_xpts_5": round(xi5, 2),
        "bench_adjusted_utility_5": round(utility5, 2),
    }
    if include_detail:
        out["best_xi_by_gw"] = detail
    return out


def frontier(candidates, owned_ids, n=7):
    """Shared deterministic candidate-frontier primitive, not a search owner."""
    out = []
    for position in POSITION_COUNTS:
        rows = [
            player
            for player in candidates
            if player.position == position and player.element not in owned_ids
        ]
        rows.sort(
            key=lambda player: (
                player.objective - 0.12 * player.uncertainty,
                player.x5,
                -player.cost,
            ),
            reverse=True,
        )
        out += rows[:n]
    return out


def audit_packages(
    predictions,
    universe,
    locked,
    max_replacements=4,
    budget=None,
    per_position_frontier=7,
    top_per_size=8,
    beam_size=28,
):
    return audit_packages_from_candidates(
        build_candidates(predictions, universe),
        locked,
        max_replacements=max_replacements,
        budget=budget,
        per_position_frontier=per_position_frontier,
        top_per_size=top_per_size,
        beam_size=beam_size,
    )


def audit_packages_from_candidates(
    candidates,
    locked,
    max_replacements=4,
    budget=None,
    per_position_frontier=7,
    top_per_size=8,
    beam_size=28,
):
    """Compatibility entry point delegated to the single exact-fast search owner."""
    from src.engines.v4_wc_package_audit_fast import audit_packages_from_candidates_fast

    return audit_packages_from_candidates_fast(
        candidates,
        locked,
        max_replacements=max_replacements,
        budget=budget,
        per_position_frontier=per_position_frontier,
        top_per_size=top_per_size,
        beam_size=beam_size,
    )
