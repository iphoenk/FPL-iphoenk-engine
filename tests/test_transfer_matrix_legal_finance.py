"""A GW6 transfer what-if matrix must never masquerade as executed P1.7/P1.4."""

import json
from pathlib import Path

from src.engines.v12_transfer_matrix import INPUT_PATH, build_matrix


def _result():
    return build_matrix(json.loads(Path(INPUT_PATH).read_text(encoding="utf-8")))


def test_complete_240_route_grid_and_no_fabricated_mc():
    result = _result()
    assert result["coverage"] == {
        "distinct_squads": 30,
        "formation_rows": 240,
        "conditionally_fundable_squads": 15,
        "conditionally_fundable_formation_rows": 120,
        "invalid_or_unfunded_formation_rows": 120,
    }
    assert len({r["formation"] for r in result["formation_matrix"]}) == 8
    assert sum(r["mc_500k_status"] == "BASELINE_PACKAGE_ONLY"
               for r in result["formation_matrix"]) == 8
    assert sum(r["mc_500k_status"] == "NOT_EXECUTED"
               for r in result["formation_matrix"]) == 232
    assert all(
        r["captain_adjusted_xpts"] is None
        for r in result["formation_matrix"]
        if r["mc_500k_status"] == "NOT_EXECUTED"
    )
    assert result["base_mc_is_not_what_if_mc"] is True


def test_saka_without_arsenal_exit_fails_exact_club_rule():
    cases = _result()["scenarios"]
    for case in cases:
        if case["tavernier_element"] == 12 and case["konsa_element"] == 31:
            assert case["arsenal_count"] == 4
            assert case["status"] == "ILLEGAL_MAX_3_CLUB"
        if case["tavernier_element"] == 12 and case["konsa_element"] != 31:
            assert case["arsenal_count"] == 3
            assert case["club_legal"] is True


def test_saka_plus_mbeumo_konsa_exit_is_indicatively_funded():
    cases = _result()["scenarios"]
    target = [
        c for c in cases if c["tavernier_element"] == 12
        and c["bruno_element"] == 427 and c["konsa_element"] != 31
    ]
    assert len(target) == 9
    assert all(c["status"] == "STRUCTURAL_PASS_FINANCE_UNVERIFIED" for c in target)
    assert all(c["transfers"] in (3, 4) for c in target)
    assert all(c["official_bank_verified"] is False for c in target)
    assert all(c["free_transfers_verified"] is False for c in target)
    assert all(c["hit_points"] is None for c in target)


def test_saka_without_mbeumo_is_still_unfunded_after_budget_exit():
    cases = _result()["scenarios"]
    target = [
        c for c in cases if c["tavernier_element"] == 12
        and c["bruno_element"] == 426 and c["konsa_element"] != 31
    ]
    assert len(target) == 9
    assert all(c["status"] == "INDICATIVE_UNFUNDED" for c in target)
