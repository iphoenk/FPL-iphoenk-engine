"""E02 characterization: legal lineup enumeration and captain/vice pair semantics (no rule or weight changes)."""
from __future__ import annotations

import itertools

import pytest

from src.engines.v12_lineup_optimizer import (
    LineupOptimizerError,
    enumerate_legal_xi,
    evaluate_captain_vice_pairs,
)

SQUAD = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def _players(positions=SQUAD):
    return [{"element": i + 1, "position": pos} for i, pos in enumerate(positions)]


def _independent_legal_count(positions) -> int:
    """Brute force from the published FPL rule only: 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD, 11 players."""
    count = 0
    for combo in itertools.combinations(range(15), 11):
        chosen = [positions[i] for i in combo]
        gk, d, m, f = (chosen.count(p) for p in ("GK", "DEF", "MID", "FWD"))
        if gk == 1 and 3 <= d <= 5 and 2 <= m <= 5 and 1 <= f <= 3:
            count += 1
    return count


def test_enumeration_matches_independent_brute_force():
    masks = enumerate_legal_xi(_players())
    assert len(masks) == _independent_legal_count(SQUAD)
    assert len(set(masks)) == len(masks)


def test_goalkeeper_is_separate_every_xi_has_exactly_one_and_bench_has_the_other():
    for mask in enumerate_legal_xi(_players()):
        assert [SQUAD[i] for i in mask].count("GK") == 1
        bench = [i for i in range(15) if i not in mask]
        assert len(bench) == 4 and sum(SQUAD[i] == "GK" for i in bench) == 1


def test_every_enumerated_xi_has_a_legal_formation_and_eleven_players():
    for mask in enumerate_legal_xi(_players()):
        chosen = [SQUAD[i] for i in mask]
        assert len(mask) == 11
        assert 3 <= chosen.count("DEF") <= 5 and 2 <= chosen.count("MID") <= 5 and 1 <= chosen.count("FWD") <= 3


def test_squad_that_is_not_exactly_fifteen_is_rejected_not_padded():
    with pytest.raises(LineupOptimizerError):
        enumerate_legal_xi(_players()[:14])
    with pytest.raises(LineupOptimizerError):
        enumerate_legal_xi([{"element": 1, "position": "XX"}] * 15)


def _starter(element, mean, p_dnp=0.1, p_app=0.9):
    return {"element": element, "name": f"P{element}", "xpts_mean": mean, "expected_shortfall": 1.0,
            "expected_excess_ge_8": 0.5, "p_dnp": p_dnp, "p_appearance": p_app}


def test_same_context_gives_the_same_captain_vice_ranking():
    starters = [_starter(1, 7.0), _starter(2, 6.0), _starter(3, 5.0), _starter(4, 5.0)]
    a = evaluate_captain_vice_pairs(starters)
    b = evaluate_captain_vice_pairs(list(starters))
    assert [(r["captain_element"], r["vice_element"]) for r in a] == [(r["captain_element"], r["vice_element"]) for r in b]
    assert len(a) == 4 * 3  # ordered pairs, never captain == vice
    assert all(r["captain_element"] != r["vice_element"] for r in a)


def test_non_owned_player_can_never_be_captain_or_vice():
    starters = [_starter(1, 7.0), _starter(2, 6.0)]
    pairs = evaluate_captain_vice_pairs(starters)
    assert {r["captain_element"] for r in pairs} | {r["vice_element"] for r in pairs} == {1, 2}


def test_vice_takeover_value_is_weighted_by_the_captain_dnp_probability():
    pair = next(r for r in evaluate_captain_vice_pairs([_starter(1, 7.0, p_dnp=0.2), _starter(2, 6.0, p_dnp=0.1, p_app=0.8)])
                if r["captain_element"] == 1)
    assert pair["expected_vice_takeover_value"] == pytest.approx(0.2 * 6.0)
    assert pair["vice_takeover_probability"] == pytest.approx(0.2 * 0.8)
    assert pair["joint_dnp_failure_probability"] == pytest.approx(0.2 * 0.1)
    assert pair["covariance_status"] == "COVARIANCE_NOT_MODELLED_YET"


def test_captain_with_zero_dnp_probability_gives_the_vice_no_value():
    pair = next(r for r in evaluate_captain_vice_pairs([_starter(1, 7.0, p_dnp=0.0), _starter(2, 6.0)]) if r["captain_element"] == 1)
    assert pair["expected_vice_takeover_value"] == 0 and pair["vice_takeover_probability"] == 0
