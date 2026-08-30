import json
from pathlib import Path

import pytest

from src.v5.decision.lineup_optimizer import _lineup_risk_adjustment, player_score
from src.v5.intelligence import projection as projection_module


ROOT = Path(__file__).resolve().parents[1]


def _projected_player(element: int, position: str, team_id: int, mean: float = 5.0, std: float = 2.0, dnp: float = 0.1):
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": team_id,
        "now_cost": 50,
        "xmins": {"start_probability": 0.8, "dnp_probability": dnp},
        "xpts_by_gw": [
            {
                "gw": 2,
                "mean": mean,
                "std": std,
                "fixtures": [
                    {
                        "components": {
                            "clean_sheet": 0.0,
                            "saves": 0.0,
                            "defensive_contribution": 0.0,
                        }
                    }
                ],
            }
        ],
    }


def test_final_xi_player_score_matches_current_production_risk_contract():
    cfg = json.loads((ROOT / "config/v5_decision_registry.json").read_text())
    policy = cfg["lineup"]["player_score"]
    assert policy == {
        "mean_weight": 1.0,
        "risk_std_penalty": 0.12,
        "start_probability_weight": 0.0,
        "dnp_probability_penalty": 2.0,
    }
    player = _projected_player(1, "MID", 1)
    assert player_score(player, 2, "player_score") == pytest.approx(5.0 - 0.12 * 2.0 - 2.0 * 0.1)


def test_lineup_risk_adjustment_is_bounded_decision_only():
    cfg = json.loads((ROOT / "config/v5_decision_registry.json").read_text())["lineup"]
    risk = cfg["lineup_risk"]
    assert risk == {
        "enabled": True,
        "close_call_rerank_gap": 0.75,
        "same_team_defensive_cluster_penalty": 0.08,
        "defensive_route_concentration_penalty": 0.06,
        "bench_utility_weight": 0.03,
        "maximum_close_call_adjustment": 0.30,
    }
    starters = [
        _projected_player(1, "GK", 1),
        _projected_player(2, "DEF", 1),
        _projected_player(3, "DEF", 2),
        _projected_player(4, "DEF", 3),
        *[_projected_player(10 + i, "MID", 4 + i) for i in range(4)],
        *[_projected_player(20 + i, "FWD", 8 + i) for i in range(3)],
    ]
    bench = [
        _projected_player(30, "GK", 11, mean=3.0),
        _projected_player(31, "DEF", 12, mean=3.0),
        _projected_player(32, "MID", 13, mean=3.0),
        _projected_player(33, "FWD", 14, mean=3.0),
    ]
    out = _lineup_risk_adjustment(starters, bench, 2, cfg)
    assert out["same_team_defensive_cluster_extras"] == 1
    assert out["defensive_cluster_penalty"] == pytest.approx(0.08)
    assert abs(out["adjustment"]) <= 0.30
    assert out["governance"]["raw_xpts_unchanged"] is True
    assert out["governance"]["bounded_decision_adjustment_only"] is True


def _minimal_prediction(monkeypatch, *, set_piece_share: float, penalty_share: float):
    captured = []

    def fake_strength(bootstrap, fixtures):
        return {
            "teams": [{"team_id": 1, "matches_played": 1}],
            "matchups": [
                {
                    "event": 2,
                    "kickoff_time": "2026-09-01T19:00:00Z",
                    "team_h": 1,
                    "team_a": 2,
                    "home_expected_goals": 1.5,
                    "away_expected_goals": 1.0,
                    "home_clean_sheet_probability": 0.35,
                    "away_clean_sheet_probability": 0.20,
                }
            ],
            "baseline": {"home_goals": 1.5, "away_goals": 1.2},
        }

    def fake_roles(bootstrap, team_matches):
        return {
            "model": "test-role",
            "players": {
                1: {
                    "role_start_probability": 0.99,
                    "rotation_risk": 0.45,
                    "competition_pressure": 0.45,
                    "set_piece_share": set_piece_share,
                    "penalty_share": penalty_share,
                    "source": "test",
                }
            },
            "capabilities": [],
            "non_claims": [],
            "projection_adjustment": {"set_piece_assist_uplift": 9.0, "penalty_goal_uplift": 9.0},
        }

    def fake_xmins(player, context):
        captured.append(dict(context))
        return {
            "start_probability": 0.8,
            "bench_probability": 0.1,
            "dnp_probability": 0.1,
            "expected_minutes": 70.0,
            "starter_minutes_if_start": 75.0,
            "minutes_std": 10.0,
            "small_sample_guard": True,
            "confidence": "MEDIUM",
        }

    monkeypatch.setattr(projection_module, "build_team_strength", fake_strength)
    monkeypatch.setattr(projection_module, "build_role_intelligence", fake_roles)
    monkeypatch.setattr(projection_module, "estimate_xmins", fake_xmins)

    bootstrap = {
        "teams": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        "elements": [
            {
                "id": 1,
                "web_name": "Player",
                "team": 1,
                "element_type": 3,
                "now_cost": 70,
                "status": "a",
                "selected_by_percent": "1.0",
                "starts": 1,
                "minutes": 90,
                "expected_goals": 0.5,
                "expected_assists": 0.3,
                "bonus": 0,
                "saves": 0,
            }
        ],
    }
    rules = {
        "ruleset_id": "test",
        "goal_points": {1: 10, 2: 6, 3: 5, 4: 4},
        "clean_sheet_points": {1: 4, 2: 4, 3: 1, 4: 0},
        "assist_points": 3,
    }
    out = projection_module.build_predictions(bootstrap, [{}], rules, 2, horizon=3, historical_prior={"players": {}})
    return out, captured


def test_role_start_signal_is_observable_but_not_double_counted_into_xmins(monkeypatch):
    out, captured = _minimal_prediction(monkeypatch, set_piece_share=1.0, penalty_share=1.0)
    assert len(captured) == 1
    assert "role_start_probability" not in captured[0]
    assert "rotation_risk" not in captured[0]
    player = out["players"][0]
    assert player["role"]["role_start_probability"] == pytest.approx(0.99)
    assert out["role_projection_governance"]["role_start_probability_not_double_counted_in_xmins"] is True


def test_set_piece_and_penalty_role_do_not_directly_mutate_quantitative_xpts(monkeypatch):
    neutral, _ = _minimal_prediction(monkeypatch, set_piece_share=0.0, penalty_share=0.0)
    enriched, _ = _minimal_prediction(monkeypatch, set_piece_share=1.0, penalty_share=1.0)
    assert enriched["players"][0]["xpts_by_gw"][0]["mean"] == pytest.approx(
        neutral["players"][0]["xpts_by_gw"][0]["mean"]
    )
    assert enriched["role_projection_governance"]["set_piece_and_penalty_role_do_not_directly_mutate_xpts"] is True
