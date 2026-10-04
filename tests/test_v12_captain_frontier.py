from __future__ import annotations

import pytest

from src.engines.v12_captain_frontier import decide_captain_vice


def _candidate(
    element,
    name,
    *,
    expected,
    pmf,
    position="MID",
    p_start=0.95,
    xmins=85.0,
    p_dnp=None,
    league_c=20.0,
    league_eo=80.0,
    competitive_c=20.0,
    competitive_eo=80.0,
):
    return {
        "element_id": element,
        "player": name,
        "position": position,
        "expected_points": expected,
        "p_start": p_start,
        "xmins": xmins,
        "p_dnp": (1.0 - p_start) if p_dnp is None else p_dnp,
        "point_distribution": {
            "status": "READY_COMPLETE_CONDITIONAL_PMF",
            "probabilities": {str(k): v for k, v in pmf.items()},
        },
        "league_scope": {
            "captain_pct": league_c,
            "eo_pct": league_eo,
        },
        "competitive_scope": {
            "captain_pct": competitive_c,
            "eo_pct": competitive_eo,
        },
    }


def test_tzolakis_regression_highest_mean_alone_is_not_clear_captain():
    rows = [
        _candidate(
            1, "Tzolakis", expected=4.811, position="GK",
            pmf={2: 0.60, 6: 0.30, 10: 0.10},
            p_start=0.8299, xmins=71.4,
            league_c=1.0, league_eo=12.0,
            competitive_c=0.0, competitive_eo=10.0,
        ),
        _candidate(
            2, "Bruno", expected=4.681,
            pmf={2: 0.45, 5: 0.25, 10: 0.15, 15: 0.15},
            p_start=0.8299, xmins=71.4,
            league_c=18.0, league_eo=80.0,
            competitive_c=22.0, competitive_eo=88.0,
        ),
        _candidate(
            3, "De Cuyper", expected=4.540, position="DEF",
            pmf={2: 0.50, 6: 0.25, 10: 0.15, 15: 0.10},
            p_start=0.8299, xmins=68.8,
            league_c=2.0, league_eo=35.0,
            competitive_c=1.0, competitive_eo=32.0,
        ),
        _candidate(
            4, "Haaland", expected=4.485, position="FWD",
            pmf={2: 0.40, 5: 0.25, 10: 0.15, 15: 0.20},
            p_start=0.8299, xmins=71.4,
            league_c=55.0, league_eo=141.4,
            competitive_c=65.0, competitive_eo=150.0,
        ),
    ]
    out = decide_captain_vice(
        rows,
        baseline_captain_id=1,
        baseline_vice_id=2,
        risk_posture="BALANCED",
        league_complete=True,
        competitive_complete=True,
    )
    assert out["classification"] == "CLOSE"
    assert out["governance"]["highest_mean_alone_is_not_authority"] is True
    assert len(out["frontier"]) >= 2
    assert out["captain"]["element_id"] == 1
    tz = next(row for row in out["profiles"] if row["element_id"] == 1)
    assert tz["expected_points"] == pytest.approx(4.811)
    assert tz["p_haul"] == pytest.approx(tz["p_ge_10"])
    assert all(
        pair["method"] == "EXACT_DISCRETE_PMF_DIFFERENCE"
        for pair in out["pairwise"]
        if pair["status"] == "AVAILABLE"
    )


def test_gk_can_captain_when_mean_and_distribution_clearly_dominate():
    rows = [
        _candidate(
            1, "Dominant GK", expected=8.0, position="GK",
            pmf={6: 0.50, 10: 0.50}, p_start=0.99, xmins=89.0,
        ),
        _candidate(
            2, "Attacker", expected=6.0, position="FWD",
            pmf={2: 0.20, 6: 0.50, 10: 0.30}, p_start=0.95, xmins=84.0,
        ),
    ]
    out = decide_captain_vice(
        rows,
        baseline_captain_id=2,
        baseline_vice_id=1,
        risk_posture="ATTACK",
        league_complete=True,
        competitive_complete=True,
    )
    assert out["classification"] == "CLEAR"
    assert out["captain"]["player"] == "Dominant GK"
    assert out["governance"]["position_neutral"] is True
    assert out["mini_league_override_applied"] is False


def test_attacker_with_stronger_upper_tail_enters_close_frontier_despite_lower_mean():
    rows = [
        _candidate(
            1, "Keeper", expected=5.1, position="GK",
            pmf={2: 0.20, 6: 0.70, 10: 0.10},
        ),
        _candidate(
            2, "Forward", expected=5.0, position="FWD",
            pmf={2: 0.30, 4: 0.30, 10: 0.10, 15: 0.30},
        ),
    ]
    out = decide_captain_vice(
        rows,
        baseline_captain_id=1,
        baseline_vice_id=2,
    )
    assert out["classification"] == "CLOSE"
    assert {row["player"] for row in out["frontier"]} == {"Keeper", "Forward"}
    forward = next(row for row in out["frontier"] if row["player"] == "Forward")
    keeper = next(row for row in out["frontier"] if row["player"] == "Keeper")
    assert forward["q90"] > keeper["q90"]
    assert forward["expected_points"] < keeper["expected_points"]


def test_high_eo_materially_inferior_candidate_cannot_be_promoted():
    rows = [
        _candidate(
            1, "Football Winner", expected=7.5,
            pmf={6: 0.50, 10: 0.50}, p_start=0.99, xmins=89,
            competitive_c=20, competitive_eo=80,
        ),
        _candidate(
            2, "High EO Inferior", expected=4.0,
            pmf={2: 0.60, 6: 0.40}, p_start=0.90, xmins=75,
            competitive_c=80, competitive_eo=170,
        ),
    ]
    out = decide_captain_vice(
        rows,
        baseline_captain_id=1,
        baseline_vice_id=2,
        risk_posture="PROTECT",
        league_complete=True,
        competitive_complete=True,
    )
    assert out["classification"] == "CLEAR"
    assert out["captain"]["player"] == "Football Winner"
    assert out["mini_league_override_applied"] is False


def test_low_eo_materially_inferior_differential_cannot_be_promoted():
    rows = [
        _candidate(
            1, "Football Winner", expected=7.5,
            pmf={6: 0.50, 10: 0.50}, p_start=0.99, xmins=89,
            competitive_c=60, competitive_eo=145,
        ),
        _candidate(
            2, "Low EO Inferior", expected=4.0,
            pmf={2: 0.60, 6: 0.40}, p_start=0.90, xmins=75,
            competitive_c=1, competitive_eo=8,
        ),
    ]
    out = decide_captain_vice(
        rows,
        baseline_captain_id=1,
        baseline_vice_id=2,
        risk_posture="ATTACK",
        league_complete=True,
        competitive_complete=True,
    )
    assert out["classification"] == "CLEAR"
    assert out["captain"]["player"] == "Football Winner"


def test_close_frontier_can_be_resolved_by_protect_or_attack_posture():
    rows = [
        _candidate(
            1, "Protection", expected=6.0,
            pmf={2: 0.25, 6: 0.50, 10: 0.25},
            competitive_c=70, competitive_eo=150,
            league_c=60, league_eo=140,
        ),
        _candidate(
            2, "Leverage", expected=5.9,
            pmf={2: 0.35, 5: 0.25, 10: 0.10, 15: 0.30},
            competitive_c=5, competitive_eo=25,
            league_c=8, league_eo=30,
        ),
    ]
    protect = decide_captain_vice(
        rows,
        baseline_captain_id=2,
        baseline_vice_id=1,
        risk_posture="PROTECT",
        league_complete=True,
        competitive_complete=True,
    )
    attack = decide_captain_vice(
        rows,
        baseline_captain_id=1,
        baseline_vice_id=2,
        risk_posture="ATTACK",
        league_complete=True,
        competitive_complete=True,
    )
    assert protect["classification"] == "CLOSE"
    assert attack["classification"] == "CLOSE"
    assert protect["captain"]["player"] == "Protection"
    assert attack["captain"]["player"] == "Leverage"
    assert protect["competitive_context"]["relative_points_not_invented_from_eo"] is True


def test_vice_prioritizes_robust_fallback_not_captain_rank_two():
    rows = [
        _candidate(
            1, "Clear Captain", expected=8.0,
            pmf={6: 0.40, 10: 0.60}, p_start=0.99, xmins=89,
        ),
        _candidate(
            2, "Risky High Mean", expected=6.5,
            pmf={2: 0.30, 6: 0.40, 10: 0.30},
            p_start=0.80, p_dnp=0.20, xmins=68,
        ),
        _candidate(
            3, "Safe Fallback", expected=5.5,
            pmf={2: 0.20, 6: 0.60, 10: 0.20},
            p_start=0.98, p_dnp=0.02, xmins=87,
        ),
    ]
    out = decide_captain_vice(
        rows,
        baseline_captain_id=1,
        baseline_vice_id=2,
    )
    assert out["captain"]["player"] == "Clear Captain"
    assert out["vice_captain"]["player"] == "Safe Fallback"
    assert "LOW_DNP_HIGH_START" in out["vice_reason"]


def test_missing_mini_league_context_preserves_football_leader_and_fabricates_nothing():
    rows = [
        _candidate(
            1, "Baseline", expected=6.0,
            pmf={2: 0.25, 6: 0.50, 10: 0.25},
            competitive_c=70, competitive_eo=150,
        ),
        _candidate(
            2, "Alternative", expected=5.9,
            pmf={2: 0.35, 5: 0.25, 10: 0.10, 15: 0.30},
            competitive_c=5, competitive_eo=25,
        ),
    ]
    out = decide_captain_vice(
        rows,
        baseline_captain_id=1,
        baseline_vice_id=2,
        risk_posture="ATTACK",
        league_complete=False,
        competitive_complete=False,
    )
    assert out["classification"] == "CLOSE"
    assert out["captain"]["player"] == "Baseline"
    assert out["mini_league_override_applied"] is False
    assert out["competitive_context"]["tie_break_status"] == (
        "UNAVAILABLE_INCOMPLETE_MINI_LEAGUE_EVIDENCE"
    )
    for row in out["competitive_context"]["competitive_consequence"]:
        assert row["expected_relative_points_delta_vs_league"] is None
        assert row["probability_gain_relative_points"] is None
