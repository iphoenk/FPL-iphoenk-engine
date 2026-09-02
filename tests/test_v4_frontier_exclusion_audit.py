from __future__ import annotations

from types import SimpleNamespace

from src.engines.v4_frontier_exclusion_audit import frontier_exclusion_audit_from_candidates
from src.engines.v4_wc_package_audit import frontier


def _p(element, position, objective, uncertainty, x5, cost, team_id=1):
    return SimpleNamespace(
        element=element,
        name=f"P{element}",
        position=position,
        team=f"T{team_id}",
        team_id=team_id,
        cost=cost,
        x3=x5 * 0.6,
        x5=x5,
        x10=x5 * 2,
        x15=x5 * 3,
        uncertainty=uncertainty,
        objective=objective,
    )


def _locked():
    return {"players": [], "itb_tenths": 1000}


def test_audit_top7_exactly_matches_production_frontier(monkeypatch):
    monkeypatch.setattr(
        "src.engines.v4_frontier_exclusion_audit.reconcile_owned_costs",
        lambda candidates, locked: (candidates, {"available_budget_tenths": 1000}),
    )
    candidates = []
    element = 1
    for pos in ("GK", "DEF", "MID", "FWD"):
        for index in range(12):
            candidates.append(_p(element, pos, 10 - index * 0.25, index * 0.01, 20 - index, 45 + index, (index % 5) + 1))
            element += 1

    audit = frontier_exclusion_audit_from_candidates(candidates, _locked())
    expected = frontier(candidates, set(), 7)
    expected_by_pos = {
        pos: [p.element for p in expected if p.position == pos]
        for pos in ("GK", "DEF", "MID", "FWD")
    }

    assert audit["audit_only"] is True
    assert audit["decision_authority"] == "NONE"
    assert audit["affects_search"] is False
    assert audit["production_frontier_unchanged"] is True
    for pos, rows in audit["by_position"].items():
        assert [row["element"] for row in rows[:7]] == expected_by_pos[pos]
        assert all(row["frontier_state"] == "IN_FRONTIER" for row in rows[:7])
        assert all(row["frontier_state"] == "PRUNED" for row in rows[7:])


def test_audit_preserves_exact_frontier_tie_break_order(monkeypatch):
    monkeypatch.setattr(
        "src.engines.v4_frontier_exclusion_audit.reconcile_owned_costs",
        lambda candidates, locked: (candidates, {"available_budget_tenths": 1000}),
    )
    candidates = [
        _p(1, "MID", 5.0, 0.2, 20.0, 70),
        _p(2, "MID", 5.0, 0.2, 20.0, 65),
        _p(3, "MID", 5.0, 0.2, 19.0, 60),
    ]
    audit = frontier_exclusion_audit_from_candidates(
        candidates,
        _locked(),
        production_frontier_per_position=2,
        audit_depth_per_position=3,
    )
    assert [row["element"] for row in audit["by_position"]["MID"]] == [2, 1, 3]


def test_boundary_reports_rank7_rank8_gap_without_changing_width(monkeypatch):
    monkeypatch.setattr(
        "src.engines.v4_frontier_exclusion_audit.reconcile_owned_costs",
        lambda candidates, locked: (candidates, {"available_budget_tenths": 1000}),
    )
    candidates = [_p(i, "FWD", 10 - i * 0.1, 0.1, 20 - i * 0.1, 50) for i in range(1, 11)]
    audit = frontier_exclusion_audit_from_candidates(candidates, _locked())
    row = audit["boundary"]["FWD"]
    assert row["retained_rank"] == 7
    assert row["first_pruned_rank"] == 8
    assert audit["production_frontier_per_position"] == 7
