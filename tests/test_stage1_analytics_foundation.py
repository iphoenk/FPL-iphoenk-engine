from __future__ import annotations

from src.models.v12_stage1_analytics import (
    build_canonical_universe,
    build_hierarchical_priors,
    distribution_selection_matrix,
    opponent_adjust_match_rows,
    regime_change_evidence,
    walk_forward_validate,
)


def _rows():
    rows = []
    for gw in range(1, 6):
        rows.extend(
            [
                {
                    "player_id": 1, "element": 1, "team_id": 1,
                    "position": "MID", "gw": gw, "match_id": 100 + gw,
                    "opponent_team_id": 2, "home": gw % 2 == 1,
                    "minutes": 90, "starter": True,
                    "xg": 0.15 * gw, "xa": 0.10,
                    "xgi": 0.15 * gw + 0.10,
                    "goals": int(gw == 5), "assists": 0,
                    "saves": 0, "bonus": 0, "defensive": 5,
                },
                {
                    "player_id": 2, "element": 2, "team_id": 2,
                    "position": "FWD", "gw": gw, "match_id": 200 + gw,
                    "opponent_team_id": 1, "home": gw % 2 == 0,
                    "minutes": 75 if gw < 4 else 90, "starter": True,
                    "xg": 0.25, "xa": 0.05 * gw,
                    "xgi": 0.25 + 0.05 * gw,
                    "goals": 0, "assists": int(gw == 4),
                    "saves": 0, "bonus": 0, "defensive": 3,
                },
            ]
        )
    return rows


def _strength():
    return {
        "teams": [
            {
                "team_id": 1, "attack_home_index": 1.2,
                "attack_away_index": 1.1, "defence_home_index": 1.15,
                "defence_away_index": 1.05,
            },
            {
                "team_id": 2, "attack_home_index": 0.9,
                "attack_away_index": 0.95, "defence_home_index": 0.8,
                "defence_away_index": 0.85,
            },
        ]
    }


def test_opponent_adjustment_and_hierarchy_are_deterministic():
    adjusted = opponent_adjust_match_rows(_rows(), _strength())
    assert all(row["opponent_strength_weight"] > 0 for row in adjusted)
    priors = build_hierarchical_priors(adjusted)
    assert priors["players"]["1"]["variables"]["xg90"]["prior_rate90"] >= 0
    assert priors["different_prior_strengths_by_variable"] is True
    assert priors["final_player_posterior_owner"] == "V12_PLAYER_EVENTS"


def test_distribution_selection_never_uses_erlang_generically():
    matrix = distribution_selection_matrix(_rows())["matrix"]
    assert matrix
    assert all(row.get("erlang_selected") is not True for row in matrix)
    assert any(row.get("target") == "goals" for row in matrix)


def test_walk_forward_is_expanding_window_without_future_leakage():
    result = walk_forward_validate(
        opponent_adjust_match_rows(_rows(), _strength())
    )
    assert result["future_leakage"] is False
    assert result["folds"] >= 1
    assert result["status"] == "PASS"
    assert result["starter_brier"]


def test_regime_change_publishes_role_stability_probability():
    result = regime_change_evidence(_rows()[:5])
    assert 0.0 <= result["p_role_stable"] <= 1.0
    assert result["history_hard_reset"] is False


def test_canonical_universe_uses_exact_macro_weights_and_owner_outputs_only():
    players = []
    for position in ("GK", "DEF", "MID", "FWD"):
        for index in range(6):
            element = len(players) + 1
            players.append(
                {
                    "element": element,
                    "name": f"P{element}",
                    "position": position,
                    "team_id": 1,
                    "now_cost": 50,
                    "status": "a",
                    "posterior_rates": {
                        "goal": {
                            "prior": 0.1 + index / 100,
                            "posterior_rate90": 0.12 + index / 100,
                        },
                        "assist": {
                            "prior": 0.08,
                            "posterior_rate90": 0.09,
                        },
                        "saves": {
                            "prior": 3.0,
                            "posterior_rate90": 3.1,
                        },
                        "defcon": {
                            "prior_expected_points90": 0.3,
                            "expected_points90": 0.4,
                        },
                    },
                    "tactical_role_component": {
                        "canonical_tactical_role_score": 50 + index
                    },
                    "horizons": {
                        "1": {"mean": 4 + index / 10},
                        "3": {"mean": 12 + index / 10},
                        "5": {"mean": 20 + index / 10},
                    },
                }
            )
    out = build_canonical_universe({"players": players})
    assert out["status"] == "COMPLETE"
    assert out["weights"] == {
        "PROVEN_HISTORICAL": 0.20,
        "TACTICAL_ROLE": 0.25,
        "CURRENT_UNDERLYING": 0.30,
        "FIXTURE_SECURITY": 0.25,
    }
    assert all(
        row["canonical_evaluation_complete"] for row in out["players"]
    )
    assert out["new_xpts_model_created"] is False
    assert out["new_xmins_model_created"] is False
