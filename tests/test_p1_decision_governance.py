from __future__ import annotations

from src.engines.p1_decision_governance import (
    bench_battles,
    choose_close_call_lineup,
    decision_scores,
    lineup_risk_adjustment,
    uncertainty_fields,
    vice_rank,
)


POLICY = {
    "selection": {
        "risk_aversion_std": 0.12,
        "dnp_penalty_points": 2.0,
        "close_call_rerank_gap": 0.75,
        "same_team_defensive_cluster_penalty": 0.08,
        "defensive_route_concentration_penalty": 0.06,
        "bench_utility_weight": 0.03,
        "maximum_close_call_adjustment": 0.30,
    },
    "uncertainty": {"z_value": 1.2815515655},
    "captaincy": {
        "risk_aversion_std": 0.10,
        "dnp_penalty_points": 4.0,
        "vice_attack_ceiling_weight": 0.08,
        "vice_focality_weight": 0.12,
        "vice_penalty_role_bonus": 0.08,
        "vice_set_piece_role_bonus": 0.04,
        "vice_defender_small_edge_guard": 0.30,
        "maximum_vice_context_adjustment": 0.35,
    },
    "bench": {
        "risk_aversion_std": 0.10,
        "dnp_penalty_points": 1.5,
        "start_probability_weight": 0.20,
        "ceiling_weight": 0.05,
        "maximum_context_adjustment": 0.25,
        "close_battle_threshold": 0.35,
    },
}


def test_uncertainty_fields_preserve_point_estimate_and_expose_80_interval():
    fields = uncertainty_fields(
        {"mean": 5.0, "std": 2.0},
        {"dnp_probability": 0.1, "bench_probability": 0.2, "availability": 0.95},
        POLICY,
    )
    assert fields["lower80"] < 5.0 < fields["upper80"]
    assert fields["interval_width"] == round(fields["upper80"] - fields["lower80"], 3)
    assert fields["dnp_probability"] == 0.1
    assert fields["bench_probability"] == 0.2
    assert fields["availability"] == 0.95


def test_vice_score_uses_attacking_context_without_mutating_raw_xpts():
    proj = {"penalty_role": "PRIMARY", "set_piece_role": "CORNERS"}
    gw = {"mean": 5.0, "std": 1.0, "fixtures": [{"components": {"attack": 2.5, "appearance": 1.8}}]}
    xmins = {"dnp_probability": 0.05, "start_probability": 0.9}
    scores = decision_scores(proj, gw, xmins, POLICY)
    assert scores["score_decomposition"]["raw_xpts"] == 5.0
    assert scores["vice_score"] > scores["captain_score"]
    assert scores["score_decomposition"]["vice_context_adjustment"] <= 0.35


def test_defender_cannot_win_vice_only_on_tiny_score_edge_over_higher_ceiling_attacker():
    defender = {"element": 1, "position": "DEF", "vice_score": 5.20, "captain_score": 5.20, "attack_ceiling_proxy": 0.3}
    attacker = {"element": 2, "position": "MID", "vice_score": 5.05, "captain_score": 5.00, "attack_ceiling_proxy": 2.0}
    rows = vice_rank([defender, attacker], captain_element=999, policy=POLICY)
    assert rows[0]["element"] == 2


def test_lineup_risk_adjustment_penalizes_same_team_defensive_cluster_without_attacker_bonus():
    starters = [
        {"position": "GK", "team_id": 10, "defensive_route_proxy": 3.0, "xpts_mean": 5.0},
        {"position": "DEF", "team_id": 10, "defensive_route_proxy": 2.5, "xpts_mean": 5.0},
        {"position": "MID", "team_id": 20, "defensive_route_proxy": 0.0, "xpts_mean": 5.0},
    ]
    bench = [{"position": "MID", "bench_score": 3.0}]
    risk = lineup_risk_adjustment(starters, bench, POLICY)
    assert risk["same_team_defensive_cluster_extras"] == 1
    assert risk["defensive_cluster_penalty"] > 0
    assert risk["governance"]["no_attacking_formation_bonus"] is True
    assert abs(risk["adjustment"]) <= 0.30


def test_close_lineup_can_be_reranked_by_bounded_decision_risk_but_distant_one_cannot_jump():
    candidates = [
        {"formation": "5-3-2", "base_score": 50.0, "decision_score": 49.8, "xpts_mean": 52.0},
        {"formation": "3-4-3", "base_score": 49.8, "decision_score": 49.9, "xpts_mean": 51.8},
        {"formation": "4-4-2", "base_score": 48.0, "decision_score": 50.0, "xpts_mean": 50.0},
    ]
    ranked = choose_close_call_lineup(candidates, POLICY)
    assert ranked[0]["formation"] == "3-4-3"
    assert ranked[-1]["formation"] == "4-4-2"


def test_bench_close_battle_is_surfaced():
    rows = [
        {"element": 1, "name": "A", "bench_score": 3.20, "xpts_mean": 3.2},
        {"element": 2, "name": "B", "bench_score": 3.00, "xpts_mean": 3.0},
        {"element": 3, "name": "C", "bench_score": 2.00, "xpts_mean": 2.0},
    ]
    battles = bench_battles(rows, POLICY)
    assert len(battles) == 1
    assert battles[0]["higher"]["element"] == 1
    assert battles[0]["lower"]["element"] == 2
    assert battles[0]["status"] == "CLOSE"
