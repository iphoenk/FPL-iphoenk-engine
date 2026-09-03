from __future__ import annotations

from src.engines.package_optimizer_exhaustive_finalize import build_exhaustive, safe_per_gw_dominates


def _player(element: int, position: str, team_id: int, means: list[float], cost: int = 50, std: float = 1.0) -> dict:
    rows = [
        {"gw": 3 + index, "mean": float(mean), "std": float(std)}
        for index, mean in enumerate(means)
    ]
    cumulative = []
    running = 0.0
    variance = 0.0
    horizon_rows = {}
    for index, mean in enumerate(means, start=1):
        running += mean
        variance += std * std
        cumulative.append(running)
        if index in (3, 5, 10, 15):
            horizon_rows[str(index)] = {"mean": running, "std": variance ** 0.5}
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": team_id,
        "now_cost": cost,
        "status": "a",
        "xpts_by_gw": rows,
        "horizons": horizon_rows,
    }


def _owned() -> list[dict]:
    rows = []
    element = 1
    team_id = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(count):
            rows.append(_player(element, position, team_id, [3.0] * 15, 50, 1.0))
            element += 1
            team_id = team_id % 20 + 1
    return rows


def _team(owned: list[dict]) -> dict:
    return {
        "team_value_ledger": [{"element": row["element"], "sell_cost": row["now_cost"]} for row in owned],
        "totals": {"itb": 0},
    }


def test_safe_dominance_requires_every_gw_not_only_cumulative_horizons():
    # Same total across the first 3 GWs, but left loses one individual GW.
    left = _player(100, "MID", 16, [5.0, 1.0, 6.0] + [4.0] * 12, 50, 1.0)
    right = _player(101, "MID", 16, [4.0, 4.0, 4.0] + [4.0] * 12, 50, 1.0)
    assert safe_per_gw_dominates(left, right, 3, 15) is False


def test_safe_dominance_is_same_team_position_price_and_per_gw():
    stronger = _player(100, "MID", 16, [5.0] * 15, 49, 0.8)
    weaker = _player(101, "MID", 16, [4.0] * 15, 50, 1.0)
    other_team = _player(102, "MID", 17, [4.0] * 15, 50, 1.0)
    assert safe_per_gw_dominates(stronger, weaker, 3, 15) is True
    assert safe_per_gw_dominates(stronger, other_team, 3, 15) is False


def test_exhaustive_small_universe_has_full_authority_and_no_budget():
    owned = _owned()
    candidates = [
        _player(100, "MID", 16, [5.0] * 15, 50),
        _player(101, "MID", 17, [4.5] * 15, 50),
        _player(102, "DEF", 18, [4.5] * 15, 50),
        _player(103, "FWD", 19, [4.5] * 15, 50),
    ]
    projections = {"planning_gw": 3, "players": owned + candidates}
    result = build_exhaustive(projections, _team(owned), top_keep=100)
    diag = result["search_diagnostics"]
    assert result["status"] == "READY"
    assert diag["search_authority"] == "FULL"
    assert diag["lossy_pruning"] is False
    assert diag["single_budget_applied"] is False
    assert diag["pair_budget_applied"] is False
    assert diag["exact_package_limit_applied"] is False
    assert diag["single_exact_scored"] == diag["legal_single_stubs"]
    assert diag["pair_candidates_exact_scored"] == diag["pair_step_legal"]
    assert result["package_count"] == 1 + diag["single_exact_scored"] + diag["pair_candidates_exact_scored"]
