from __future__ import annotations

from src.engines import owned_challenger_comparator as comparator


def _p(element, name, mean):
    return {
        "element": element,
        "name": name,
        "team_id": element,
        "team": f"T{element}",
        "position": "MID",
        "now_cost": 60,
        "xpts_by_gw": [{"gw": 2+i, "mean": mean, "std": 1.0, "fixtures": []} for i in range(5)],
        "xmins": {"start_probability": 0.7, "dnp_probability": 0.1},
    }


def test_one_challenger_can_rank_multiple_logical_owned_targets_but_is_bounded():
    owned = []
    for idx, mean in enumerate((1.5, 2.0, 2.5, 3.0, 3.5), start=1):
        proj = _p(idx, f"Owned {idx}", mean)
        owned.append({"element": idx, "name": proj["name"], "position": "MID", "team_id": idx, "sell_cost": 60, "projection": proj})
    challenger = _p(99, "Generic Challenger", 4.0)
    rows = comparator._target_outs(challenger, owned, set(), 0)
    assert len(rows) == 3
    assert [row["element"] for row in rows] == [1, 2, 3]
