"""Regression coverage for CLOSE GK captain risk without a position ban."""
from src.engines.v12_captain_frontier import decide_captain_vice


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
