from src.models.projection import project_points


def _player(element_type: int) -> dict:
    return {
        "element_type": element_type,
        "status": "a",
        "chance_of_playing_next_round": 100,
        "minutes": 90,
        "starts": 1,
        "saves": 0,
    }


def test_goal_scoring_2026_27_by_position():
    advanced = {
        "start_probability": 1.0,
        "xg_per90": 1.0,
        "xa_per90": 0.0,
        "clean_sheet_probability": 0.0,
        "bonus_per90": 0.0,
        "defcon_points_per90": 0.0,
        "saves_per90": 0.0,
    }

    expected = {1: 10.0, 2: 6.0, 3: 5.0, 4: 4.0}
    for position, goal_points in expected.items():
        result = project_points(_player(position), advanced)
        assert result["components"]["attack"] == goal_points
