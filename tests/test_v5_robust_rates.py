import pytest

from src.v5.intelligence.robust_rates import robust_attack_rate, validate_config


CFG = {
    "model": "adaptive_shrinkage_winsor_v1",
    "absolute_upper_rate90": 1.5,
    "tiers": [
        {"max_minutes": 90, "shrink_minutes": 900, "upper_prior_multiplier": 2.5},
        {"max_minutes": 270, "shrink_minutes": 675, "upper_prior_multiplier": 3.5},
        {"max_minutes": 450, "shrink_minutes": 525, "upper_prior_multiplier": 4.5},
        {"max_minutes": None, "shrink_minutes": 450, "upper_prior_multiplier": 6.0},
    ],
}


def test_zero_minutes_preserves_prior_without_fabricating_observation():
    value, source, diagnostics = robust_attack_rate(
        {"minutes": 0, "expected_goals": 4.0}, "expected_goals", 0.4, CFG
    )
    assert value == pytest.approx(0.4)
    assert source == "position_or_historical_prior"
    assert diagnostics["raw_observed90"] is None
    assert diagnostics["winsorized"] is False


def test_extreme_early_observation_is_winsorized_and_heavily_shrunk():
    value, source, diagnostics = robust_attack_rate(
        {"minutes": 90, "expected_goals": 4.0}, "expected_goals", 0.4, CFG
    )
    assert diagnostics["raw_observed90"] == pytest.approx(4.0)
    assert diagnostics["upper_rate90"] == pytest.approx(1.5)
    assert diagnostics["bounded_observed90"] == pytest.approx(1.5)
    assert diagnostics["shrink_minutes"] == pytest.approx(900.0)
    assert diagnostics["winsorized"] is True
    assert source == "robust_observed_shrunk_to_prior_winsorized"
    assert value == pytest.approx(0.5)


def test_breakout_cap_relaxes_as_evidence_minutes_accumulate():
    early, _, early_diag = robust_attack_rate(
        {"minutes": 90, "expected_goals": 3.0}, "expected_goals", 0.4, CFG
    )
    established, _, established_diag = robust_attack_rate(
        {"minutes": 600, "expected_goals": 20.0}, "expected_goals", 0.4, CFG
    )
    assert early_diag["cap_multiplier"] == pytest.approx(2.5)
    assert established_diag["cap_multiplier"] == pytest.approx(6.0)
    assert early_diag["shrink_minutes"] == pytest.approx(900.0)
    assert established_diag["shrink_minutes"] == pytest.approx(450.0)
    assert established_diag["upper_rate90"] > early_diag["upper_rate90"]
    assert established > early


def test_invalid_or_unbounded_tier_contract_fails_closed():
    with pytest.raises(RuntimeError):
        validate_config({"model": "adaptive_shrinkage_winsor_v1", "tiers": []})
    with pytest.raises(RuntimeError):
        validate_config(
            {
                "model": "adaptive_shrinkage_winsor_v1",
                "tiers": [{"max_minutes": 90, "shrink_minutes": 900, "upper_prior_multiplier": 2.5}],
            }
        )
