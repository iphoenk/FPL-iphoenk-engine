import pytest

from src.models.projection_components import robust_attack_rate

CFG = {
    "absolute_upper_rate90": 1.5,
    "tiers": [
        {"max_minutes": 90, "shrink_minutes": 900, "upper_prior_multiplier": 2.5},
        {"max_minutes": 270, "shrink_minutes": 675, "upper_prior_multiplier": 3.5},
        {"max_minutes": 450, "shrink_minutes": 525, "upper_prior_multiplier": 4.5},
        {"max_minutes": None, "shrink_minutes": 450, "upper_prior_multiplier": 6.0},
    ],
}


def player(minutes, cumulative):
    return {"minutes": minutes, "expected_goals": cumulative, "expected_assists": cumulative}


def test_no_current_minutes_returns_prior_exactly():
    rate, source, diag = robust_attack_rate(player(0, 0), "expected_goals", 0.38, CFG)
    assert rate == pytest.approx(0.38)
    assert source == "position_or_historical_prior"
    assert diag["raw_observed90"] is None


def test_one_match_extreme_rate_is_bounded_and_strongly_shrunk():
    rate, source, diag = robust_attack_rate(player(90, 4.0), "expected_goals", 0.38, CFG)
    assert diag["winsorized"] is True
    assert diag["shrink_minutes"] == 900
    assert rate < 0.55
    assert "winsorized" in source


def test_breakout_cap_relaxes_as_evidence_accumulates():
    early, _, early_diag = robust_attack_rate(player(90, 2.0), "expected_goals", 0.38, CFG)
    established, _, established_diag = robust_attack_rate(player(900, 20.0), "expected_goals", 0.38, CFG)
    assert early_diag["cap_multiplier"] == 2.5
    assert established_diag["cap_multiplier"] == 6.0
    assert established > early


def test_normal_observation_is_not_winsorized_but_still_shrunk():
    rate, source, diag = robust_attack_rate(player(270, 1.5), "expected_goals", 0.38, CFG)
    raw = 1.5 * 90 / 270
    assert diag["winsorized"] is False
    assert 0.38 < rate < raw
    assert source == "robust_observed_shrunk_to_prior"


def test_zero_observation_remains_valid_and_does_not_create_fake_attack():
    rate, _, diag = robust_attack_rate(player(270, 0.0), "expected_assists", 0.20, CFG)
    assert diag["raw_observed90"] == 0.0
    assert 0.0 < rate < 0.20
