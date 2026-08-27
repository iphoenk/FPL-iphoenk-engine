import pytest

from src.v5.intelligence.defensive_contribution import build_rate_bundle, project_fixture_points


RULES = {
    "authority": "truth-service",
    "defensive_contributions": {
        "1": {"eligible": False, "threshold": None, "points": 0},
        "2": {"eligible": True, "threshold": 10, "points": 2},
        "3": {"eligible": True, "threshold": 12, "points": 2},
        "4": {"eligible": True, "threshold": 12, "points": 2},
    },
}


def test_position_prior_fallback_preserves_prior_expected_points90():
    bundle = build_rate_bundle(
        element_type=2,
        prior_expected_points90=0.55,
        advanced=None,
        rules=RULES,
        shrink_minutes=450,
    )
    assert bundle["eligible"] is True
    assert bundle["source"] == "position_prior_probability_calibrated"
    assert bundle["threshold"] == 10
    assert bundle["expected_points90"] == pytest.approx(0.55, abs=1e-6)
    assert bundle["evidence_minutes"] == 0


def test_player_cbit_evidence_changes_defensive_contribution_probability():
    prior = build_rate_bundle(
        element_type=2,
        prior_expected_points90=0.55,
        advanced=None,
        rules=RULES,
        shrink_minutes=450,
    )
    empirical = build_rate_bundle(
        element_type=2,
        prior_expected_points90=0.55,
        advanced={
            "dc_reconstructed_per90": 18.0,
            "dc_evidence_minutes": 900,
            "dc_sample_quality": "ESTABLISHED",
        },
        rules=RULES,
        shrink_minutes=450,
    )
    assert empirical["source"] == "player_cbit_cbirt_shrunk_to_position_prior"
    assert empirical["evidence_minutes"] == 900
    assert empirical["sample_quality"] == "ESTABLISHED"
    assert empirical["count_rate_per90"] > prior["count_rate_per90"]
    assert empirical["expected_points90"] > prior["expected_points90"]
    assert 0 < empirical["threshold_probability_90"] < 1


def test_midfielder_uses_official_threshold_12():
    bundle = build_rate_bundle(
        element_type=3,
        prior_expected_points90=0.30,
        advanced={"dc_reconstructed_per90": 14.0, "dc_evidence_minutes": 450},
        rules=RULES,
    )
    assert bundle["threshold"] == 12
    assert bundle["points_on_threshold"] == 2


def test_fixture_projection_uses_conditional_minutes_and_appearance_probability():
    bundle = build_rate_bundle(
        element_type=2,
        prior_expected_points90=0.55,
        advanced={"dc_reconstructed_per90": 18.0, "dc_evidence_minutes": 900},
        rules=RULES,
    )
    fixture = project_fixture_points(bundle, expected_minutes=63.0, appearance_probability=0.9)
    assert fixture["conditional_minutes"] == pytest.approx(70.0)
    assert 0 < fixture["threshold_probability_if_appears"] < 1
    assert fixture["points"] == pytest.approx(
        0.9 * 2 * fixture["threshold_probability_if_appears"], abs=1e-9
    )


def test_goalkeeper_is_ineligible():
    bundle = build_rate_bundle(
        element_type=1,
        prior_expected_points90=0.0,
        advanced={"dc_reconstructed_per90": 20.0, "dc_evidence_minutes": 900},
        rules=RULES,
    )
    assert bundle["eligible"] is False
    assert bundle["expected_points90"] == 0
    assert project_fixture_points(bundle, 90, 1.0)["points"] == 0
