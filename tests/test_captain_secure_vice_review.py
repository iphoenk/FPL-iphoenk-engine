"""CLOSE goalkeeper-tail review must not promote GK vice on a security tie.

Only advisory vice priority changes. P1.7 selected C/VC, LOCK, and Monte Carlo
are untouched.
"""
from src.engines.v12_captain_frontier import _select_vice


def _rows():
    return [
        {
            "element_id": 572, "player": "Tzolakis", "position": "GK",
            "p_dnp": .09, "p_start": .8299, "xmins": 71.4,
            "expected_points": 4.811, "p_ge_10": .1128, "q90": 10,
        },
        {
            "element_id": 426, "player": "Bruno", "position": "MID",
            "p_dnp": .09, "p_start": .8299, "xmins": 71.4,
            "expected_points": 4.681, "p_ge_10": .1401, "q90": 11,
        },
        {
            "element_id": 411, "player": "Haaland", "position": "FWD",
            "p_dnp": .09, "p_start": .8299, "xmins": 71.4,
            "expected_points": 4.485, "p_ge_10": .1407, "q90": 11,
        },
        {
            "element_id": 115, "player": "De Cuyper", "position": "DEF",
            "p_dnp": .09, "p_start": .8299, "xmins": 68.8,
            "expected_points": 4.54, "p_ge_10": .143, "q90": 12,
        },
    ]


def test_review_gk_security_tied_attacking_vice_haaland():
    vice, _ = _select_vice(
        _rows(), captain_id=426, baseline_vice_id=426,
        prefer_attacking_when_security_tied=True,
    )
    assert vice["element_id"] == 411


def test_current_baseline_vice_remains_keeper_without_review_flag():
    vice, _ = _select_vice(_rows(), captain_id=426, baseline_vice_id=426)
    assert vice["element_id"] == 572


def test_less_secure_attacker_must_not_displace_keeper():
    rows = _rows()
    rows[2]["p_dnp"] = 0.10
    vice, _ = _select_vice(
        rows, captain_id=426, baseline_vice_id=426,
        prefer_attacking_when_security_tied=True,
    )
    assert vice["element_id"] == 572
