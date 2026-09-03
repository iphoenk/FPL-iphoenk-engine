from __future__ import annotations

import json
from pathlib import Path

from src.engines import decision_intelligence
from src.engines.decision_intelligence import (
    _package_frontier,
    _step_legal_transfer_sequence,
    build_package_optimizer,
)

ROOT = Path(__file__).resolve().parents[1]


def _player(element: int, position: str, team_id: int, mean: float, cost: int = 50) -> dict:
    rows = [{"gw": gw, "mean": mean, "std": 1.0} for gw in range(3, 18)]
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": team_id,
        "now_cost": cost,
        "status": "a",
        "xpts_by_gw": rows,
        "horizons": {
            "3": {"mean": mean * 3, "std": 1.0},
            "5": {"mean": mean * 5, "std": 1.0},
            "10": {"mean": mean * 10, "std": 1.0},
            "15": {"mean": mean * 15, "std": 1.0},
        },
    }


def _owned_squad() -> list[dict]:
    rows = []
    element = 1
    team_id = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(count):
            rows.append(_player(element, position, team_id, 3.0, 50))
            element += 1
            team_id += 1
    return rows


def _team(owned: list[dict]) -> dict:
    return {
        "team_value_ledger": [
            {"element": row["element"], "sell_cost": row["now_cost"]}
            for row in owned
        ],
        "totals": {"itb": 0},
    }


def test_config_forbids_hidden_top_n_candidate_authority():
    cfg = json.loads((ROOT / "config/intelligence/package_optimizer.json").read_text())
    assert cfg["candidate_origin"] == "COMPLETE_ELIGIBLE_OFFICIAL_FPL_UNIVERSE"
    assert cfg["watchlist_is_optimizer_input"] is False
    assert "max_candidates_per_position" not in cfg
    assert "max_single_moves_per_out" not in cfg
    assert "max_deterministic_packages" not in cfg
    assert cfg["governance"]["fixed_top_n_candidate_authority_forbidden"] is True
    assert cfg["governance"]["lossy_pruning_must_downgrade_search_authority"] is True


def test_rank_beyond_old_top7_can_win_package_optimization(monkeypatch):
    owned = _owned_squad()
    candidates = []
    # Seven high candidate-score rows are deliberately unaffordable. The eighth
    # candidate must still enter exact single-move evaluation and can win.
    for index in range(7):
        candidates.append(_player(100 + index, "MID", 16 + index, 8.0 - index * 0.1, 100))
    candidates.append(_player(107, "MID", 23, 7.0, 50))
    candidates.append(_player(108, "MID", 24, 2.0, 50))
    projections = {"planning_gw": 3, "players": owned + candidates}
    cfg = json.loads((ROOT / "config/intelligence/package_optimizer.json").read_text())
    cfg["max_changes"] = 1
    cfg["candidate_pool_preview_per_position"] = 7
    cfg["monte_carlo_top_n"] = 100
    monkeypatch.setattr(decision_intelligence, "load_optimizer_config", lambda: cfg)

    result = build_package_optimizer(projections, _team(owned))

    preview_ids = {row["element"] for row in result["candidate_pool"]["MID"]}
    package_in_ids = {
        row["element"]
        for package in result["packages"]
        for row in package.get("ins") or []
    }
    assert 107 not in preview_ids
    assert 107 in package_in_ids
    assert result["search_diagnostics"]["eligible_by_position"]["MID"] == 9
    assert result["search_diagnostics"]["fixed_top_n_candidate_truncation_applied"] is False
    assert result["search_diagnostics"]["watchlist_used_as_optimizer_input"] is False
    assert result["search_diagnostics"]["search_authority"] == "FULL"


def test_each_transfer_step_recomputes_cash_and_legal_squad():
    owned = _owned_squad()
    mids = [row for row in owned if row["position"] == "MID"]
    outs = [dict(mids[0], sell_cost=50), dict(mids[1], sell_cost=50)]
    ins = [_player(201, "MID", 16, 5.0, 55), _player(202, "MID", 17, 5.0, 45)]

    valid, audit = _step_legal_transfer_sequence(owned, outs, ins, itb=0)

    assert valid is True
    assert audit["resulting_itb"] == 0
    assert len(audit["steps"]) == 2
    assert all(step["legal_squad_after_step"] is True for step in audit["steps"])
    assert audit["steps"][0]["itb_after"] >= 0
    assert audit["steps"][1]["itb_after"] >= 0


def test_frontier_is_representation_not_second_scoring_authority():
    hold = {
        "id": "HOLD",
        "changes": 0,
        "affordability": {"resulting_itb": 0},
        "score": {
            "robust_score": 100.0,
            "objective_std": 10.0,
            "horizons": {h: {"mean": 100.0} for h in ("3", "5", "10", "15")},
        },
    }
    better = {
        "id": "BETTER",
        "changes": 1,
        "affordability": {"resulting_itb": 0},
        "score": {
            "robust_score": 120.0,
            "objective_std": 8.0,
            "horizons": {h: {"mean": 120.0} for h in ("3", "5", "10", "15")},
        },
    }
    dominated = {
        "id": "DOMINATED",
        "changes": 2,
        "affordability": {"resulting_itb": 0},
        "score": {
            "robust_score": 110.0,
            "objective_std": 9.0,
            "horizons": {h: {"mean": 110.0} for h in ("3", "5", "10", "15")},
        },
    }

    frontier = _package_frontier([hold, better, dominated], hold, 20)
    ids = {row["id"] for row in frontier["packages"]}
    assert "BETTER" in ids
    assert "DOMINATED" not in ids
    assert frontier["never_second_scoring_authority"] is True
    assert frontier["authority"] == "REPRESENTATION_ONLY"
