from __future__ import annotations

import json

from src.engines.v4_wc_optimizer import POSITION_COUNTS, build_candidates, reconcile_owned_costs
from src.utils import CONFIG, DATA, read_json


PRODUCTION_FRONTIER_PER_POSITION = 7
AUDIT_DEPTH_PER_POSITION = 20
UNCERTAINTY_WEIGHT = 0.12


def _selection_score(player) -> float:
    return player.objective - UNCERTAINTY_WEIGHT * player.uncertainty


def frontier_exclusion_audit_from_candidates(
    candidates,
    locked: dict,
    *,
    production_frontier_per_position: int = PRODUCTION_FRONTIER_PER_POSITION,
    audit_depth_per_position: int = AUDIT_DEPTH_PER_POSITION,
) -> dict:
    """Expose retained/pruned candidates using production frontier ranking only.

    Audit-only helper. It MUST NOT influence candidate generation, package ranking,
    beam width, legality, decision authority, or production recommendations.
    """
    if production_frontier_per_position < 1:
        raise ValueError("production_frontier_per_position must be >= 1")
    if audit_depth_per_position < production_frontier_per_position:
        raise ValueError("audit depth must cover the production frontier")

    candidates, affordability = reconcile_owned_costs(candidates, locked)
    owned_ids = {int(row["element"]) for row in locked.get("players", [])}

    by_position: dict[str, list[dict]] = {}
    boundary: dict[str, dict] = {}
    for position in POSITION_COUNTS:
        rows = [player for player in candidates if player.position == position and player.element not in owned_ids]
        rows.sort(
            key=lambda player: (_selection_score(player), player.x5, -player.cost),
            reverse=True,
        )

        emitted = []
        for rank, player in enumerate(rows[:audit_depth_per_position], start=1):
            emitted.append({
                "rank": rank,
                "frontier_state": "IN_FRONTIER" if rank <= production_frontier_per_position else "PRUNED",
                "element": player.element,
                "name": player.name,
                "team": player.team,
                "team_id": player.team_id,
                "position": player.position,
                "cost": player.cost,
                "xpts_3": round(player.x3, 2),
                "xpts_5": round(player.x5, 2),
                "xpts_10": round(player.x10, 2),
                "xpts_15": round(player.x15, 2),
                "uncertainty": round(player.uncertainty, 3),
                "objective": round(player.objective, 4),
                "selection_score": round(_selection_score(player), 4),
            })
        by_position[position] = emitted

        retained = rows[production_frontier_per_position - 1] if len(rows) >= production_frontier_per_position else None
        first_pruned = rows[production_frontier_per_position] if len(rows) > production_frontier_per_position else None
        boundary[position] = {
            "retained_rank": production_frontier_per_position if retained else None,
            "retained_element": retained.element if retained else None,
            "retained_selection_score": round(_selection_score(retained), 4) if retained else None,
            "first_pruned_rank": production_frontier_per_position + 1 if first_pruned else None,
            "first_pruned_element": first_pruned.element if first_pruned else None,
            "first_pruned_selection_score": round(_selection_score(first_pruned), 4) if first_pruned else None,
            "selection_score_gap": round(_selection_score(retained) - _selection_score(first_pruned), 4)
            if retained and first_pruned else None,
        }

    return {
        "schema_version": 1,
        "engine": "v4-frontier-exclusion-audit",
        "audit_only": True,
        "decision_authority": "NONE",
        "affects_search": False,
        "production_frontier_unchanged": True,
        "ranking_semantics": "objective_minus_0.12_uncertainty_then_xpts5_then_lower_cost",
        "production_frontier_per_position": production_frontier_per_position,
        "audit_depth_per_position": audit_depth_per_position,
        "screened_players": len(candidates),
        "owned_players": len(owned_ids),
        "affordability": affordability,
        "boundary": boundary,
        "by_position": by_position,
    }


def audit_current_runtime() -> dict:
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    locked = read_json(CONFIG / "locked_squad.json", {})
    candidates = build_candidates(predictions, universe)
    return frontier_exclusion_audit_from_candidates(candidates, locked)


def run() -> dict:
    out = audit_current_runtime()
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
