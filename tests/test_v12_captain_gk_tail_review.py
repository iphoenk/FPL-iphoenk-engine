"""Regression coverage for CLOSE GK captain risk without a position ban."""
from src.engines.v12_captain_frontier import decide_captain_vice, _mini_league_captain_review, _goalkeeper_tail_review


def _candidate(element, name, position, pmf, *, pstart=.85, pdnp=.05, mean=None):
    mean = sum(p * mass for p, mass in pmf.items()) if mean is None else mean
    return {
        "element_id": element, "player": name, "position": position,
        "expected_points": mean, "p_start": pstart, "p_dnp": pdnp, "xmins": 71.4,
        "point_distribution": {
            "status": "READY_COMPLETE_CONDITIONAL_PMF",
            "probabilities": {str(k): v for k, v in pmf.items()},
            "blank_threshold": 2,
            "p_fpl_blank": sum(v for k, v in pmf.items() if k <= 2),
            "p_haul_10_plus": sum(v for k, v in pmf.items() if k >= 10),
        },
        "league_scope": {"captain_pct": 10.0, "eo_pct": 30.0},
        "competitive_scope": {"captain_pct": 10.0, "eo_pct": 30.0},
    }


def test_close_keeper_lower_tail_is_not_false_locked():
    keeper = _candidate(1, "Tzolakis", "GK", {2: .10, 6: .80, 10: .10},
                        pstart=.83, pdnp=.09)
    bruno = _candidate(2, "Bruno", "MID", {2: .55, 6: .25, 12: .20},
                       pstart=.85, pdnp=.05)
    haaland = _candidate(3, "Haaland", "FWD", {2: .65, 6: .20, 15: .15},
                         pstart=.85, pdnp=.05)
    out = decide_captain_vice(
        [keeper, bruno, haaland], baseline_captain_id=1, baseline_vice_id=2,
        risk_posture="BALANCED", league_complete=True, competitive_complete=True,
    )
    assert out["classification"] == "CLOSE"
    assert out["captain"]["player"] == "Tzolakis"
    assert out["decision_state"] == "PREPARE"
    assert out["review_pair"]["captain"]["player"] == "Bruno"
    assert out["review_pair"]["vice_captain"]["player"] == "Haaland"
    assert out["review_pair"]["relative_points_mc"].startswith("UNAVAILABLE")
    assert "No automatic captain swap" in out["reason"]


def test_clear_keeper_can_still_be_captain():
    keeper = _candidate(1, "Clear GK", "GK", {6: .5, 10: .5},
                        pstart=.99, pdnp=.01)
    forward = _candidate(2, "Forward", "FWD", {2: .2, 6: .5, 10: .3},
                         pstart=.95, pdnp=.05)
    out = decide_captain_vice([keeper, forward],
                              baseline_captain_id=2, baseline_vice_id=1)
    assert out["classification"] == "CLEAR"
    assert out["captain"]["player"] == "Clear GK"
    assert out["decision_state"] == "LOCK"
    assert out["review_pair"] is None


def test_close_keeper_with_superior_tail_is_not_artificially_penalized():
    keeper = _candidate(1, "Keeper", "GK", {2: .35, 6: .4, 15: .25},
                        pstart=.85, pdnp=.05)
    mid = _candidate(2, "Mid", "MID", {2: .4, 6: .5, 10: .1},
                     pstart=.85, pdnp=.05)
    out = decide_captain_vice([keeper, mid],
                              baseline_captain_id=1, baseline_vice_id=2)
    assert out["review_pair"] is None
    assert out["governance"]["position_neutral"] is True


def test_review_preserves_three_scopes_rank_and_historical_baseline():
    current = {
        "league_scope": {"captain_pct": 1.0, "eo_pct": 12.0},
        "rivals_scope": {"captain_pct": 0.0, "eo_pct": 11.0},
        "competitive_scope": {"captain_pct": 0.0, "eo_pct": 11.1},
    }
    challenger = {
        "league_scope": {"captain_pct": 18.0, "eo_pct": 80.0},
        "rivals_scope": {"captain_pct": 20.0, "eo_pct": 85.0},
        "competitive_scope": {"captain_pct": 22.2, "eo_pct": 88.9},
    }
    denominators = {
        "LEAGUE": {"expected": 58, "collected": 58},
        "RIVALS": {"expected": 57, "collected": 57},
        "COMPETITIVE": {"expected": 9, "collected": 9},
    }
    result = _mini_league_captain_review(
        current, challenger, risk_posture="ATTACK",
        risk_context={"current_rank": 7, "league_size": 58, "leader_gap": 17},
        risk_context_complete=True, league_complete=True,
        rivals_complete=True, competitive_complete=True,
        scope_denominators=denominators,
        behavioural_baseline="HISTORICAL_SUBMITTED_PICKS_NOT_TARGET_GW_FORECAST",
    )
    assert result["status"] == "OBSERVED_BASELINE_COMPLETE"
    assert result["strategy_posture"] == "ATTACK"
    assert result["scope_comparison"]["COMPETITIVE"]["denominator"]["expected"] == 9
    assert result["scope_comparison"]["COMPETITIVE"]["review_minus_current_captain_pct_points"] == 22.2
    assert result["scope_comparison"]["LEAGUE"]["review_eo_pct"] == 80.0
    assert result["scope_comparison"]["RIVALS"]["review_captain_pct"] == 20.0
    assert result["risk_posture_evidence"]["leader_gap"] == 17
    assert result["target_gw_captain_ownership_forecast"] == "UNAVAILABLE"
    assert result["scope_comparison"]["COMPETITIVE"]["relative_points_expected_delta"] is None


def test_review_missing_competitive_coverage_is_fail_soft_not_false_confident():
    current = {"league_scope": {"captain_pct": 1, "eo_pct": 12}}
    challenger = {"league_scope": {"captain_pct": 18, "eo_pct": 80}}
    result = _mini_league_captain_review(
        current, challenger, risk_posture="PROTECT",
        risk_context={}, risk_context_complete=False,
        league_complete=True, rivals_complete=False, competitive_complete=False,
        scope_denominators={"LEAGUE": {"expected": 58, "collected": 58}},
        behavioural_baseline="HISTORICAL_SUBMITTED_PICKS_NOT_TARGET_GW_FORECAST",
    )
    assert result["status"] == "INCOMPLETE_FAIL_SOFT"
    assert result["mini_league_effect_on_review"].startswith("UNAVAILABLE")
    assert result["scope_comparison"]["COMPETITIVE"]["review_eo_pct"] is None
    assert result["joint_relative_points_mc"].startswith("UNAVAILABLE")


def test_complete_mini_league_posture_selects_only_among_football_viable_review_options():
    keeper = {
        "position": "GK", "p_ge_10": .10, "q90": 10,
        "p_start": .82, "p_dnp": .12,
    }
    candidates = [keeper]
    for name, share, expected in (("Protected", 70.0, 4.7), ("Differential", 5.0, 4.8)):
        candidates.append({
            "player": name, "position": "MID", "football_evidence_complete": True,
            "p_ge_10": .20, "q90": 12, "p_start": .90, "p_dnp": .05,
            "expected_points": expected,
            "league_scope": {"captain_pct": share, "eo_pct": share + 20},
            "rivals_scope": {"captain_pct": share, "eo_pct": share + 20},
            "competitive_scope": {"captain_pct": share, "eo_pct": share + 20},
        })
    flags = dict(risk_context_complete=True, league_complete=True,
                 rivals_complete=True, competitive_complete=True)
    protect = _goalkeeper_tail_review(
        candidates, keeper, "CLOSE", risk_posture="PROTECT", **flags)
    attack = _goalkeeper_tail_review(
        candidates, keeper, "CLOSE", risk_posture="ATTACK", **flags)
    assert protect["player"] == "Protected"
    assert attack["player"] == "Differential"
    # Incomplete evidence: exposure cannot select, football mean leads.
    fallback = _goalkeeper_tail_review(
        candidates, keeper, "CLOSE", risk_posture="PROTECT",
        **{**flags, "competitive_complete": False})
    assert fallback["player"] == "Differential"
