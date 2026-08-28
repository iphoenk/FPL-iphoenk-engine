from src.engines.v4_runner import player_priors
from src.models.v4_prediction_inputs import build_historical_index
from src.sources.vaastav import historical_seasons


def _player():
    return {
        "id": 1, "code": 999, "element_type": 3, "now_cost": 70,
        "selected_by_percent": "5.0", "creativity": "20", "threat": "30",
        "first_name": "Test", "second_name": "Player",
    }


def _payload(season, minutes, xg90, xa90):
    return {
        "status": "LIVE", "season": season,
        "rows": [{
            "code": "999", "first_name": "Test", "second_name": "Player",
            "minutes": str(minutes), "starts": "20",
            "expected_goals_per_90": str(xg90), "expected_assists_per_90": str(xa90),
        }],
    }


def test_historical_seasons_exclude_immediate_previous_season():
    seasons = historical_seasons(depth=2)
    assert seasons == ["2024-25", "2023-24"]


def test_multi_season_index_requires_and_preserves_multiple_older_seasons():
    out = build_historical_index([_player()], [
        _payload("2024-25", 1800, 0.4, 0.2),
        _payload("2023-24", 1500, 0.2, 0.1),
    ])
    row = out[1]
    assert row["season_count"] == 2
    assert row["seasons_used"] == ["2024-25", "2023-24"]
    assert 0.2 < row["xg_per90"] < 0.4
    assert row["aggregation"] == "recency_and_minutes_weighted_older_seasons"


def test_historical_prior_only_supplements_thin_last_season():
    history = {
        "minutes": 3300, "xg_per90": 0.35, "xa_per90": 0.18,
        "seasons_used": ["2024-25", "2023-24"], "source": "vaastav:2024-25+vaastav:2023-24",
    }
    thin = player_priors(_player(), {"minutes": 180, "xg_per90": 0.5, "xa_per90": 0.2, "source": "vaastav:2025-26"}, history)
    assert thin["historical_prior_consumed"] is True
    assert thin["historical_weight"] > 0
    assert thin["last_season_weight"] > 0

    strong = player_priors(_player(), {"minutes": 1800, "xg_per90": 0.5, "xa_per90": 0.2, "source": "vaastav:2025-26"}, history)
    assert strong["historical_prior_consumed"] is False
    assert strong["historical_weight"] == 0


def test_historical_prior_is_used_when_last_season_missing():
    history = {
        "minutes": 3300, "xg_per90": 0.35, "xa_per90": 0.18,
        "seasons_used": ["2024-25", "2023-24"], "source": "vaastav:2024-25+vaastav:2023-24",
    }
    priors = player_priors(_player(), None, history)
    assert priors["last_season_weight"] == 0
    assert priors["historical_prior_consumed"] is True
    assert priors["historical_weight"] > 0
