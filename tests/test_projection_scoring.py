from src.models import projection_components


def _projection_cfg() -> dict:
    return {
        "appearance_60_probability_transition": {"start_minutes_low": 55.0, "start_minutes_high": 70.0},
        "attack_multiplier_min": 0.55,
        "attack_multiplier_max": 1.75,
        "uncertainty": {
            "minimum_points_std": 0.0,
            "coefficient_of_variation": 0.0,
            "xmins_std_points_multiplier": 0.0,
            "small_sample_extra_std": 0.0,
        },
    }


def test_goal_scoring_2026_27_by_position_uses_canonical_projection(monkeypatch):
    monkeypatch.setattr(projection_components, "load_projection_config", _projection_cfg)
    monkeypatch.setattr(projection_components, "_team_strength_baseline", lambda: {"home_goals": 1.3, "away_goals": 1.3})
    xmins = {
        "start_probability": 1.0,
        "bench_probability": 0.0,
        "expected_minutes": 90.0,
        "starter_minutes_if_start": 90.0,
        "minutes_std": 0.0,
    }
    matchup = {
        "event": 2,
        "team_h": 1,
        "team_a": 2,
        "home_expected_goals": 1.3,
        "away_expected_goals": 1.3,
        "home_clean_sheet_probability": 0.0,
        "away_clean_sheet_probability": 0.0,
    }
    rates = {
        "xg90": 1.0,
        "xa90": 0.0,
        "bonus90": 0.0,
        "saves90": 0.0,
        "dc90": 0.0,
        "dc_threshold": None,
        "dc_count90": None,
        "dc_points": 0.0,
    }

    expected = {1: 10.0, 2: 6.0, 3: 5.0, 4: 4.0}
    for element_type, goal_points in expected.items():
        result = projection_components._project_fixture(
            {"element_type": element_type},
            xmins,
            matchup,
            True,
            rates,
            False,
        )
        assert result["components"]["attack"] == goal_points
