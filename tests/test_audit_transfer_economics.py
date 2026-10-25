"""E03: transfer economics keep unknown values unknown and keep economics out of the football score."""
from __future__ import annotations

import pytest

from src.engines.canonical_decision_methodology import build_transfer_economics


def _econ(**over):
    base = dict(ft_used=1, hit_points=0, buy_back_cost=0.0, sell_value_loss=0.0, price_movement_effect=0.0,
                affordability_after=None, itb_after=None, concentration_risk=None, correlation_risk=None,
                exit_route=None, reacquisition_plan=None)
    base.update(over)
    return build_transfer_economics(**base)


def test_unavailable_ft_shadow_is_unknown_not_numeric_zero():
    out = _econ()
    assert out["ft_shadow"]["status"] == "UNAVAILABLE" and out["ft_shadow"]["ft_shadow_value"] is None
    assert out["ft_shadow_semantics"] == "UNAVAILABLE"
    assert out["future_ft_shadow_value"] is None  # was 0.0: an unknown FT value must not look like a measured zero


def test_dynamic_shadow_value_is_kept_including_a_genuine_zero():
    out = _econ(ft_shadow={"status": "PASS", "fixed_universal_ft_value": False, "ft_shadow_value": 0.0})
    assert out["future_ft_shadow_value"] == 0.0 and out["ft_shadow_semantics"] == "DYNAMIC_CANONICAL"
    out = _econ(ft_shadow={"status": "PASS", "fixed_universal_ft_value": False, "ft_shadow_value": 0.35})
    assert out["future_ft_shadow_value"] == 0.35


def test_legacy_fixed_shadow_is_labelled_not_canonical():
    out = _econ(future_ft_shadow_value=0.2)
    assert out["ft_shadow_semantics"] == "LEGACY_HEURISTIC_NOT_CANONICAL" and out["future_ft_shadow_value"] == 0.2


def test_economics_are_not_part_of_the_football_score():
    assert _econ(hit_points=4)["included_in_football_score"] is False


def test_hit_and_opportunity_value_are_separate_fields():
    out = _econ(hit_points=4, ft_shadow={"status": "PASS", "fixed_universal_ft_value": False, "ft_shadow_value": 1.5})
    assert out["hit_points"] == 4 and out["future_ft_shadow_value"] == 1.5
    assert out["hit_points"] != out["future_ft_shadow_value"]


def test_non_finite_money_inputs_are_rejected_rather_than_coerced():
    for bad in (float("nan"), float("inf"), None, "x"):
        with pytest.raises(Exception):
            _econ(buy_back_cost=bad)


def test_invalid_exit_security_is_rejected():
    with pytest.raises(Exception):
        _econ(exit_security="MAYBE")
    assert _econ(exit_security="punt exit secure")["exit_security"] == "PUNT EXIT SECURE"
