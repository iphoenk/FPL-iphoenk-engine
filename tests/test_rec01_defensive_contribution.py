import pytest

from src.models.projection_components import (
    _poisson_tail_at_least,
    defensive_contribution_rate_bundle,
)


def _player(element_type: int) -> dict:
    return {"id": 1, "element_type": element_type, "position": {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[element_type]}


def _feature(rate: float | None, minutes: float, quality: str = "ESTABLISHED") -> dict:
    return {
        "advanced_current": {
            "minutes": minutes,
            "dc_reconstructed_per90": rate,
            "sample_quality": quality,
        }
    }


def test_gk_is_ineligible_for_defensive_contribution_points():
    out = defensive_contribution_rate_bundle(_player(1), _feature(20.0, 900), 0.0, 450.0)
    assert out["dc90"] == 0.0
    assert out["dc_threshold"] is None
    assert out["dc_source"] == "ineligible_position"


@pytest.mark.parametrize(
    "element_type,prior_points90,threshold",
    [(2, 0.55, 10), (3, 0.30, 12), (4, 0.16, 12)],
)
def test_no_advanced_evidence_preserves_existing_position_prior_at_90_minutes(element_type, prior_points90, threshold):
    out = defensive_contribution_rate_bundle(_player(element_type), _feature(None, 0), prior_points90, 450.0)
    probability = _poisson_tail_at_least(threshold, out["dc_count90"])
    assert 2.0 * probability == pytest.approx(prior_points90, abs=1e-6)
    assert out["dc90"] == pytest.approx(prior_points90, abs=1e-6)
    assert out["dc_source"] == "position_prior_probability_calibrated"


def test_player_specific_cbit_evidence_moves_defender_above_or_below_prior():
    high = defensive_contribution_rate_bundle(_player(2), _feature(15.0, 900), 0.55, 450.0)
    low = defensive_contribution_rate_bundle(_player(2), _feature(4.0, 900), 0.55, 450.0)
    assert high["dc90"] > 0.55
    assert low["dc90"] < 0.55
    assert high["dc_source"] == "player_cbit_cbirt_shrunk_to_position_prior"
    assert high["dc_evidence_minutes"] == 900


def test_midfielder_uses_cbirt_threshold_12_and_is_shrunk_for_small_samples():
    established = defensive_contribution_rate_bundle(_player(3), _feature(16.0, 900), 0.30, 450.0)
    tiny = defensive_contribution_rate_bundle(_player(3), _feature(16.0, 45, "SINGLE_APPEARANCE"), 0.30, 450.0)
    assert established["dc_threshold"] == 12
    assert established["dc90"] > tiny["dc90"] > 0.30
    assert tiny["dc_sample_quality"] == "SINGLE_APPEARANCE"
