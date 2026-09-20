from __future__ import annotations

import pytest

from src.engines.v12_contextual_dynamics import (
    build_contextual_dynamics,
    build_player_trajectory,
    data_capability_audit,
    enrich_match_rows,
    evaluate_linkup,
    evaluate_multi_player_chain,
    evaluate_opponent_matchup,
    probability_weighted_link_modifier,
)
from src.engines.v12_player_events import project_player_fixture


def row(
    *,
    player: int,
    gw: int,
    match: str,
    opponent: int,
    xg: float,
    xa: float = 0.0,
    goals: int = 0,
    assists: int = 0,
    minutes: int = 90,
    starter: bool = True,
    role: str | None = None,
    manager: str | None = "M1",
    formation: str | None = "4-3-3",
    team: int = 1,
    home: bool = True,
) -> dict:
    return {
        "player_id": player,
        "team_id": team,
        "gw": gw,
        "match_id": match,
        "opponent_team_id": opponent,
        "home": home,
        "minutes_played": minutes,
        "start_min": 0 if starter else 60,
        "actual_role": role,
        "manager_id": manager,
        "formation": formation,
        "xg": xg,
        "xa": xa,
        "total_shots": 4 if xg >= 0.5 else 1,
        "shots_on_target": 2 if xg >= 0.5 else 0,
        "touches_opposition_box": 8 if xg >= 0.5 else 2,
        "chances_created": 2 if xa >= 0.2 else 0,
        "goals": goals,
        "assists": assists,
        "fpl_points": 8 if goals or assists else 2,
    }


def target_and_creator_rows() -> tuple[list[dict], list[dict], list[dict]]:
    target = []
    creator = []
    connections = []
    for gw in range(1, 4):
        match = f"with-{gw}"
        target.append(
            row(
                player=20,
                gw=gw,
                match=match,
                opponent=80 + gw,
                xg=0.65,
                xa=0.15,
                role="FINISHER",
            )
        )
        creator.append(
            row(
                player=21,
                gw=gw,
                match=match,
                opponent=80 + gw,
                xg=0.10,
                xa=0.45,
                role="CREATOR",
            )
        )
        connections.append(
            {
                "from_player_id": 21,
                "to_player_id": 20,
                "match_id": match,
                "chances_created_to": 2,
                "xa_to_xg": 0.5,
                "progressive_passes_to": 3,
            }
        )
    for gw in range(4, 7):
        target.append(
            row(
                player=20,
                gw=gw,
                match=f"without-{gw}",
                opponent=80 + gw,
                xg=0.15,
                xa=0.05,
                role="FINISHER",
            )
        )
    return target, creator, connections


def full_start_minutes() -> dict:
    return {
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "states": [
                {
                    "state": "START",
                    "probability": 1.0,
                    "minutes_mean": 90.0,
                    "minutes_std": 0.0,
                },
                {
                    "state": "CAMEO",
                    "probability": 0.0,
                    "minutes_mean": 20.0,
                    "minutes_std": 0.0,
                },
                {
                    "state": "LATE_CAMEO",
                    "probability": 0.0,
                    "minutes_mean": 8.0,
                    "minutes_std": 0.0,
                },
                {
                    "state": "ZERO_MINUTES",
                    "probability": 0.0,
                    "minutes_mean": 0.0,
                    "minutes_std": 0.0,
                },
            ],
        }
    }


def rates() -> dict:
    return {
        "goal": {"posterior_rate90": 0.60},
        "assist": {"posterior_rate90": 0.20},
        "bonus": {"posterior_rate90": 0.0, "confidence": "LOW"},
        "saves": {"posterior_rate90": 0.0, "confidence": "LOW"},
        "defcon": {
            "eligible": False,
            "posterior_count_rate90": 0.0,
            "threshold": None,
            "points": 0.0,
        },
    }


def fixture() -> dict:
    return {
        "event": 6,
        "fixture": 600,
        "team_h": 1,
        "team_a": 2,
        "team_expected_goals": 1.6,
        "clean_sheet_probability": 0.30,
    }


def test_capability_audit_is_honest_about_unavailable_direct_links():
    audit = data_capability_audit()
    assert audit["match_id"] == "AVAILABLE"
    assert audit["gw"] == "PARTIAL"
    assert audit["chances_created"] == "AVAILABLE"
    assert audit["key_passes"] == "UNAVAILABLE"
    assert audit["direct_player_to_player_passes"] == "UNAVAILABLE"
    assert audit["cutbacks"] == "UNAVAILABLE"


def test_match_identity_enrichment_uses_existing_teammate_presence_only():
    raw = [
        {"player_id": 1, "team_id": 10, "match_id": "m1", "minutes_played": 90},
        {"player_id": 2, "team_id": 20, "match_id": "m1", "minutes_played": 90},
    ]
    out = enrich_match_rows(raw)
    assert out[0]["opponent_team_id"] == 20
    assert out[1]["opponent_team_id"] == 10
    assert "gw" not in out[0]


def test_case_A_blanks_with_high_xg_are_not_strongly_adverse():
    rows = [
        row(player=1, gw=1, match="a1", opponent=9, xg=0.8, goals=0),
        row(player=1, gw=2, match="a2", opponent=9, xg=0.8, goals=0),
        row(player=1, gw=3, match="a3", opponent=8, xg=0.7, goals=1),
        row(player=1, gw=4, match="a4", opponent=7, xg=0.7, goals=1),
    ]
    trajectory = build_player_trajectory(rows, player_id=1, current_gw=4)
    matchup = evaluate_opponent_matchup(
        trajectory,
        rows,
        player_id=1,
        opponent_team_id=9,
        current_context={
            "manager_id": "M1",
            "formation": "4-3-3",
            "player_role": None,
        },
    )
    assert matchup["result_process"]["interpretation"] == "OUTPUT_BELOW_PROCESS"
    assert matchup["classification"] != "ADVERSE"


def test_case_B_repeated_underlying_suppression_can_be_adverse():
    rows = [
        row(player=2, gw=1, match="b1", opponent=9, xg=0.02),
        row(player=2, gw=2, match="b2", opponent=9, xg=0.03),
        row(player=2, gw=3, match="b3", opponent=9, xg=0.02),
        row(player=2, gw=4, match="b4", opponent=9, xg=0.03),
        row(player=2, gw=5, match="b5", opponent=8, xg=0.75, goals=1),
        row(player=2, gw=6, match="b6", opponent=7, xg=0.70, goals=1),
        row(player=2, gw=7, match="b7", opponent=6, xg=0.80, goals=1),
    ]
    trajectory = build_player_trajectory(rows, player_id=2, current_gw=7)
    matchup = evaluate_opponent_matchup(
        trajectory,
        rows,
        player_id=2,
        opponent_team_id=9,
        current_context={
            "manager_id": "M1",
            "formation": "4-3-3",
        },
    )
    assert matchup["classification"] == "ADVERSE"
    assert matchup["posterior_rate_modifier"] < 1.0


def test_case_C_manager_system_change_discounts_old_h2h():
    rows = [
        row(player=3, gw=1, match="c1", opponent=9, xg=0.05),
        row(player=3, gw=2, match="c2", opponent=9, xg=0.05),
        row(player=3, gw=3, match="c3", opponent=8, xg=0.8),
        row(player=3, gw=4, match="c4", opponent=7, xg=0.8),
    ]
    trajectory = build_player_trajectory(rows, player_id=3, current_gw=4)
    same = evaluate_opponent_matchup(
        trajectory,
        rows,
        player_id=3,
        opponent_team_id=9,
        current_context={"manager_id": "M1", "formation": "4-3-3"},
    )
    changed = evaluate_opponent_matchup(
        trajectory,
        rows,
        player_id=3,
        opponent_team_id=9,
        current_context={"manager_id": "M2", "formation": "5-3-2"},
    )
    assert changed["tactical_similarity"] < same["tactical_similarity"]
    assert abs(changed["posterior_rate_modifier"] - 1.0) < abs(
        same["posterior_rate_modifier"] - 1.0
    )


def test_case_D_one_match_haul_does_not_reset_trajectory_or_create_action():
    rows = [
        row(player=4, gw=1, match="d1", opponent=10, xg=0.08),
        row(player=4, gw=2, match="d2", opponent=11, xg=0.10),
        row(player=4, gw=3, match="d3", opponent=12, xg=0.08),
        row(player=4, gw=4, match="d4", opponent=13, xg=0.10),
        row(player=4, gw=5, match="d5", opponent=14, xg=1.20, goals=2),
    ]
    trajectory = build_player_trajectory(rows, player_id=4, current_gw=5)
    posterior = trajectory["rates"]["xgi"]["posterior_rate90"]
    latest_rate = 1.20
    assert posterior < latest_rate
    assert "action" not in trajectory


def test_case_E_sustained_role_change_is_detected():
    rows = [
        row(player=5, gw=1, match="e1", opponent=10, xg=0.10, role="WINGER"),
        row(player=5, gw=2, match="e2", opponent=11, xg=0.12, role="WINGER"),
        row(player=5, gw=3, match="e3", opponent=12, xg=0.45, role="STRIKER"),
        row(player=5, gw=4, match="e4", opponent=13, xg=0.55, role="STRIKER"),
        row(player=5, gw=5, match="e5", opponent=14, xg=0.60, role="STRIKER"),
    ]
    trajectory = build_player_trajectory(rows, player_id=5, current_gw=5)
    assert trajectory["trajectory_classification"] == "ROLE_TRANSITION"
    assert trajectory["role_minutes_evolution"]["sustained_role_change"] is True


def test_case_F_creator_absence_reduces_finisher_projection():
    target, creator, connections = target_and_creator_rows()
    link = evaluate_linkup(
        target,
        creator,
        target_player_id=20,
        teammate_player_id=21,
        target_role="FINISHER",
        teammate_role="CREATOR",
        connection_rows=connections,
    )
    present = probability_weighted_link_modifier(link, 1.0)
    absent = probability_weighted_link_modifier(link, 0.0)
    assert link["confidence"] > 0.0
    assert present["marginal_modifier"] > absent["marginal_modifier"]

    player = {"id": 20, "element_type": 4, "position": "FWD"}
    base = project_player_fixture(
        player,
        full_start_minutes(),
        fixture(),
        home=True,
        rates=rates(),
        league_baseline={"home_goals": 1.6, "away_goals": 1.2},
    )
    degraded = project_player_fixture(
        player,
        full_start_minutes(),
        fixture(),
        home=True,
        rates=rates(),
        league_baseline={"home_goals": 1.6, "away_goals": 1.2},
        contextual_dynamics={
            "model": "test",
            "model_owner": "V12_CONTEXTUAL_DYNAMICS",
            "event_multipliers": {
                "goal": absent["marginal_modifier"],
                "assist": 1.0,
            },
        },
    )
    assert (
        degraded["event_probabilities"]["p_goal_return"]
        < base["event_probabilities"]["p_goal_return"]
    )


def test_case_G_fifty_percent_start_marginalizes_between_present_and_absent():
    target, creator, connections = target_and_creator_rows()
    link = evaluate_linkup(
        target,
        creator,
        target_player_id=20,
        teammate_player_id=21,
        target_role="FINISHER",
        teammate_role="CREATOR",
        connection_rows=connections,
    )
    present = probability_weighted_link_modifier(link, 1.0)["marginal_modifier"]
    half = probability_weighted_link_modifier(link, 0.5)["marginal_modifier"]
    absent = probability_weighted_link_modifier(link, 0.0)["marginal_modifier"]
    assert absent < half < present


def test_case_H_co_returns_without_process_connection_remain_weak():
    target, creator, _ = target_and_creator_rows()
    link = evaluate_linkup(
        target,
        creator,
        target_player_id=20,
        teammate_player_id=21,
        target_role=None,
        teammate_role=None,
        connection_rows=[],
    )
    assert link["confidence"] == 0.0
    assert link["dependency_direction"] == "WEAK_OR_NONE"


def test_case_I_multi_player_chain_weakens_when_middle_creator_is_absent():
    edges = [
        {
            "teammate_player_id": 30,
            "confidence": 0.8,
            "with_player_modifier": 1.10,
        },
        {
            "teammate_player_id": 31,
            "confidence": 0.8,
            "with_player_modifier": 1.15,
        },
    ]
    intact = evaluate_multi_player_chain(edges, {30: 1.0, 31: 1.0})
    broken = evaluate_multi_player_chain(edges, {30: 1.0, 31: 0.0})
    assert intact["multiplier"] > broken["multiplier"]
    assert broken["multiplier"] == pytest.approx(1.0)


def test_case_J_high_sample_old_link_is_discounted_after_role_change():
    target = [
        row(
            player=40,
            gw=gw,
            match=f"j{gw}",
            opponent=50 + gw,
            xg=0.65,
            role="STRIKER",
        )
        for gw in range(1, 7)
    ]
    creator = [
        row(
            player=41,
            gw=gw,
            match=f"j{gw}",
            opponent=50 + gw,
            xg=0.10,
            xa=0.45,
            role="CREATOR",
        )
        for gw in range(1, 7)
    ]
    connections = [
        {
            "from_player_id": 41,
            "to_player_id": 40,
            "match_id": f"j{gw}",
            "chances_created_to": 2,
            "xa_to_xg": 0.4,
        }
        for gw in range(1, 7)
    ]
    stable = evaluate_linkup(
        target,
        creator,
        target_player_id=40,
        teammate_player_id=41,
        target_role="STRIKER",
        teammate_role="CREATOR",
        connection_rows=connections,
    )
    changed = evaluate_linkup(
        target,
        creator,
        target_player_id=40,
        teammate_player_id=41,
        target_role="WINGER",
        teammate_role="CREATOR",
        connection_rows=connections,
    )
    assert stable["confidence"] > changed["confidence"]
    assert changed["tactical_role_relevance"] < stable["tactical_role_relevance"]


def test_no_context_preserves_existing_p13_numerics_exactly():
    player = {"id": 60, "element_type": 4, "position": "FWD"}
    kwargs = {
        "player": player,
        "minutes_projection": full_start_minutes(),
        "matchup": fixture(),
        "home": True,
        "rates": rates(),
        "league_baseline": {"home_goals": 1.6, "away_goals": 1.2},
    }
    legacy = project_player_fixture(**kwargs)
    neutral = project_player_fixture(
        **kwargs,
        contextual_dynamics={
            "model": "test",
            "model_owner": "V12_CONTEXTUAL_DYNAMICS",
            "event_multipliers": {"goal": 1.0, "assist": 1.0},
        },
    )
    assert legacy["mean"] == neutral["mean"]
    assert legacy["std"] == neutral["std"]
    assert legacy["event_probabilities"] == neutral["event_probabilities"]
    assert legacy["point_distribution"] == neutral["point_distribution"]


def test_haaland_sunderland_acceptance_is_process_not_scoreline_rule():
    # Named acceptance fixture only: no player-specific parameter exists.
    haaland = 411
    sunderland = 18
    rows = [
        row(
            player=haaland,
            gw=1,
            match="haaland-sun-1",
            opponent=sunderland,
            xg=0.85,
            goals=0,
            role="STRIKER",
        ),
        row(
            player=haaland,
            gw=2,
            match="haaland-sun-2",
            opponent=sunderland,
            xg=0.75,
            goals=0,
            role="STRIKER",
        ),
        row(
            player=haaland,
            gw=3,
            match="haaland-other-1",
            opponent=3,
            xg=0.80,
            goals=1,
            role="STRIKER",
        ),
        row(
            player=haaland,
            gw=4,
            match="haaland-other-2",
            opponent=4,
            xg=0.78,
            goals=1,
            role="STRIKER",
        ),
    ]
    trajectory = build_player_trajectory(rows, player_id=haaland, current_gw=4)
    matchup = evaluate_opponent_matchup(
        trajectory,
        rows,
        player_id=haaland,
        opponent_team_id=sunderland,
        current_context={
            "manager_id": "M1",
            "formation": "4-3-3",
            "player_role": "STRIKER",
        },
    )
    assert matchup["result_process"]["result_evidence"]["goals"] == 0
    assert matchup["result_process"]["process_evidence"]["xg"] == pytest.approx(1.60)
    assert matchup["classification"] != "ADVERSE"


def test_brobbey_le_fee_acceptance_one_match_cannot_create_strong_dependency():
    brobbey = 700
    le_fee = 701
    shared = [
        row(
            player=brobbey,
            gw=5,
            match="sun-current",
            opponent=2,
            xg=0.70,
            goals=1,
            role="FINISHER",
            team=18,
        )
    ]
    creator = [
        row(
            player=le_fee,
            gw=5,
            match="sun-current",
            opponent=2,
            xg=0.05,
            xa=0.35,
            assists=1,
            role="CREATOR",
            team=18,
        )
    ]
    connection = [
        {
            "from_player_id": le_fee,
            "to_player_id": brobbey,
            "match_id": "sun-current",
            "chances_created_to": 1,
            "xa_to_xg": 0.35,
        }
    ]
    link = evaluate_linkup(
        shared,
        creator,
        target_player_id=brobbey,
        teammate_player_id=le_fee,
        target_role="FINISHER",
        teammate_role="CREATOR",
        connection_rows=connection,
    )
    assert link["sample_size"] == 1
    assert link["confidence"] < 0.35
    half = probability_weighted_link_modifier(link, 0.5)
    assert (
        min(
            link["with_player_modifier"],
            link["without_player_modifier"],
        )
        <= half["marginal_modifier"]
        <= max(
            link["with_player_modifier"],
            link["without_player_modifier"],
        )
    )


def test_contextual_bundle_exposes_trajectory_matchup_linkup_and_bounded_rates():
    target, creator, connections = target_and_creator_rows()
    rows = target + creator
    link = evaluate_linkup(
        target,
        creator,
        target_player_id=20,
        teammate_player_id=21,
        target_role="FINISHER",
        teammate_role="CREATOR",
        connection_rows=connections,
    )
    context = build_contextual_dynamics(
        rows,
        player_id=20,
        current_gw=6,
        opponent_team_id=86,
        current_context={"manager_id": "M1", "formation": "4-3-3"},
        linkups=[{**link, "target_role": "FINISHER"}],
        teammate_start_probabilities={21: 0.5},
    )
    assert context["trajectory"]["sample_size"] == 6
    assert "classification" in context["opponent_specific_matchup"]
    assert context["linkup_network"]["relationship_count"] == 1
    assert 0.72 <= context["event_multipliers"]["goal"] <= 1.35
    assert 0.72 <= context["event_multipliers"]["assist"] <= 1.35
    assert context["governance"]["methodology_weights_20_25_30_25_unchanged"] is True
