from __future__ import annotations

import pytest

from src.engines.v12_contextual_dynamics import (
    build_contextual_dynamics,
    build_player_trajectory,
    construct_directional_chains,
    data_capability_audit,
    enrich_match_rows,
    evaluate_linkup,
    evaluate_multi_player_chain,
    evaluate_opponent_matchup,
    probability_weighted_link_modifier,
)
from src.engines.v12_player_events import project_player_fixture
from src.engines.v12_report_orchestration import build_contextual_player_blocks


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


def strong_edge(
    source: int,
    target: int,
    *,
    modifier: float = 1.15,
    confidence: float = 0.8,
    shared_minutes: float = 360.0,
    target_role: str = "FINISHER",
    source_role: str = "CREATOR",
) -> dict:
    return {
        "source_player_id": source,
        "teammate_player_id": source,
        "target_player_id": target,
        "direction": [source, target],
        "confidence": confidence,
        "dependency_strength": confidence,
        "dependency_direction": (
            "POSITIVE" if modifier > 1.0 else "NEGATIVE"
        ),
        "shared_matches": 4,
        "shared_minutes": shared_minutes,
        "role_complementarity": 1.0,
        "tactical_role_relevance": 1.0,
        "target_role": target_role,
        "teammate_role": source_role,
        "with_player_modifier": modifier,
        "without_player_modifier": max(0.01, 2.0 - modifier),
        "direct_connection_evidence": {
            "status": "AVAILABLE",
            "rows": 4,
            "weighted_connection_count": 4.0,
            "score": 0.8,
        },
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
        strong_edge(30, 31, modifier=1.10),
        strong_edge(31, 32, modifier=1.15),
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


def test_nested_report_blocks_preserve_deep_top_level_contract():
    projection = {
        "contextual_dynamics": {
            "fixture_contexts": [
                {
                    "fixture": 700,
                    "trajectory_classification": "IMPROVING",
                    "latest_match_evidence": {"gw": 5, "xg": 0.7},
                    "matchup": {
                        "historical_meetings": 2,
                        "result_process": {
                            "result_evidence": {"goals": 0},
                            "process_evidence": {"xg": 1.6},
                        },
                        "tactical_similarity": 0.75,
                        "sample_size": 2,
                        "sample_shrinkage": 0.4,
                        "classification": "NEUTRAL",
                    },
                    "linkup_network": {
                        "relationships": [
                            {
                                "teammate_player_id": 701,
                                "confidence": 0.25,
                                "dependency_strength": 0.30,
                            },
                            {
                                "teammate_player_id": 702,
                                "confidence": 0.0,
                                "dependency_strength": 0.80,
                            },
                        ],
                        "multi_player_chains": [
                            {
                                "status": "AVAILABLE",
                                "player_ids": [700, 701, 703],
                                "player_names": ["A", "B", "C"],
                                "direction": [700, 701, 703],
                                "relationship_type": "BOUNDED_MULTI_PLAYER_DEPENDENCY_CHAIN",
                                "edge_count": 2,
                                "chain_intact_probability": 0.5,
                                "weakest_link_confidence": 0.2,
                                "confidence": 0.2,
                                "linked_player_p_start": {
                                    "700": 1.0,
                                    "701": 0.5,
                                },
                                "multiplier": 1.04,
                                "main_dependency_risk": "MIDDLE_NODE_START_RISK",
                                "middle_absence_multiplier": 1.0,
                            }
                        ],
                    },
                }
            ]
        }
    }
    out = build_contextual_player_blocks(projection, fixture=700)
    assert out["state"] == "COMPLETE"
    assert set(out["blocks"]) == {
        "OPPONENT-SPECIFIC MATCHUP",
        "LINK-UP / COMBINATION NETWORK",
    }
    network = out["blocks"]["LINK-UP / COMBINATION NETWORK"]
    assert network["relationship_count"] == 1
    assert network["relationships"][0]["teammate_player_id"] == 701
    assert network["chain_count"] == 1
    assert network["MULTI-PLAYER CHAINS"][0]["player_ids"] == [700, 701, 703]
    assert (
        network["MULTI-PLAYER CHAINS"][0]["middle_absence_multiplier"]
        == pytest.approx(1.0)
    )


def test_canonical_methodology_authority_contains_contextual_governance():
    from pathlib import Path

    canonical = (
        Path(__file__).resolve().parents[1]
        / "control"
        / "fpl_master_v12"
        / "FPL_MASTER_CANONICAL_V12.txt"
    ).read_text(encoding="utf-8")
    required = (
        "GW1-TO-CURRENT TRAJECTORY / OPPONENT MATCHUP / LINK-UP DEPENDENCY",
        "RESULT EVIDENCE != PROCESS EVIDENCE",
        "P(event_B) = P(A starts)*P(event_B|A starts)",
        "SUPPORTIVE, NEUTRAL, ADVERSE or",
        "Haaland-v-Sunderland",
        "Brobbey/Le Fee",
        "20/25/30/25 stays exactly unchanged",
    )
    for token in required:
        assert token in canonical



def _chain_projection(chain: dict) -> dict:
    target_rows = [
        row(
            player=103,
            gw=gw,
            match=f"chain-target-{gw}",
            opponent=70 + gw,
            xg=0.45,
            xa=0.10,
            role="FINISHER",
        )
        for gw in range(1, 5)
    ]
    edges = [
        dict(edge)
        for edge in chain.get("edges") or []
        if isinstance(edge, dict)
    ]
    terminal = edges[-1] if edges else None
    linked = {
        int(player_id): float(probability)
        for player_id, probability in (
            chain.get("linked_player_p_start") or {}
        ).items()
    }
    context = build_contextual_dynamics(
        target_rows,
        player_id=103,
        current_gw=4,
        opponent_team_id=99,
        current_context={"manager_id": "M1", "formation": "4-3-3"},
        linkups=[terminal] if terminal else [],
        chains=[chain] if chain.get("status") == "AVAILABLE" else [],
        teammate_start_probabilities=(
            linked or {101: 1.0, 102: 1.0}
        ),
        opponent_history_rows=[],
        opponent_history_scope="CURRENT-SEASON ONLY",
    )
    projection = project_player_fixture(
        {"id": 103, "element_type": 4, "position": "FWD"},
        full_start_minutes(),
        fixture(),
        home=True,
        rates=rates(),
        league_baseline={"home_goals": 1.6, "away_goals": 1.2},
        contextual_dynamics=context,
    )
    return {"context": context, "projection": projection}


def test_K_strong_three_player_chain_reaches_p13_distribution():
    edges = [
        strong_edge(101, 102, modifier=1.12),
        strong_edge(102, 103, modifier=1.15),
    ]
    chain = evaluate_multi_player_chain(
        edges,
        {101: 1.0, 102: 1.0},
    )
    assert chain["status"] == "AVAILABLE"
    assert chain["multiplier"] > 1.0

    with_chain = _chain_projection(chain)
    neutral = _chain_projection(
        {
            "status": "AVAILABLE",
            "edges": edges,
            "confidence": chain["confidence"],
            "multiplier": 1.0,
        }
    )
    a = with_chain["projection"]
    b = neutral["projection"]
    assert a["event_probabilities"]["p_goal_return"] > b["event_probabilities"]["p_goal_return"]
    assert a["event_probabilities"]["p_attacking_return"] > b["event_probabilities"]["p_attacking_return"]
    assert a["event_probabilities"]["p_total_ga_ge_2"] > b["event_probabilities"]["p_total_ga_ge_2"]
    assert a["point_distribution"]["p_haul_10_plus"] >= b["point_distribution"]["p_haul_10_plus"]
    assert a["point_distribution"]["p_fpl_blank"] < b["point_distribution"]["p_fpl_blank"]
    assert a["mean"] > b["mean"]
    assert a["std"] != b["std"]


def test_L_middle_node_absent_materially_weakens_chain_and_projection():
    edges = [
        strong_edge(101, 102, modifier=1.12),
        strong_edge(102, 103, modifier=1.15),
    ]
    intact = evaluate_multi_player_chain(edges, {101: 1.0, 102: 1.0})
    broken = evaluate_multi_player_chain(edges, {101: 1.0, 102: 0.0})
    assert intact["multiplier"] > broken["multiplier"]
    assert broken["multiplier"] == pytest.approx(1.0)
    assert broken["chain_intact_probability"] == pytest.approx(0.0)

    intact_projection = _chain_projection(intact)["projection"]
    broken_projection = _chain_projection(broken)["projection"]
    assert (
        intact_projection["event_probabilities"]["p_goal_return"]
        > broken_projection["event_probabilities"]["p_goal_return"]
    )
    assert intact_projection["mean"] > broken_projection["mean"]


def test_M_half_start_middle_node_lies_between_intact_and_broken():
    edges = [
        strong_edge(101, 102, modifier=1.12),
        strong_edge(102, 103, modifier=1.15),
    ]
    intact = evaluate_multi_player_chain(edges, {101: 1.0, 102: 1.0})
    half = evaluate_multi_player_chain(edges, {101: 1.0, 102: 0.5})
    broken = evaluate_multi_player_chain(edges, {101: 1.0, 102: 0.0})
    assert broken["multiplier"] < half["multiplier"] < intact["multiplier"]

    p_intact = _chain_projection(intact)["projection"]
    p_half = _chain_projection(half)["projection"]
    p_broken = _chain_projection(broken)["projection"]
    assert (
        p_broken["event_probabilities"]["p_attacking_return"]
        < p_half["event_probabilities"]["p_attacking_return"]
        < p_intact["event_probabilities"]["p_attacking_return"]
    )


def test_N_incompatible_direction_does_not_form_chain():
    edges = [
        strong_edge(101, 102),
        strong_edge(104, 103),
    ]
    out = evaluate_multi_player_chain(edges, {101: 1.0, 104: 1.0})
    assert out["status"] == "REJECTED_INCOMPATIBLE_DIRECTION"
    constructed = construct_directional_chains(
        edges,
        target_player_id=103,
        teammate_start_probabilities={101: 1.0, 104: 1.0},
    )
    assert constructed == []


def test_O_cycle_is_rejected():
    edges = [
        strong_edge(101, 102),
        strong_edge(102, 101),
    ]
    out = evaluate_multi_player_chain(edges, {101: 1.0, 102: 1.0})
    assert out["status"] == "REJECTED_CYCLE"


def test_P_chain_confidence_is_weakest_meaningful_link():
    edges = [
        strong_edge(101, 102, confidence=0.80),
        strong_edge(102, 103, confidence=0.10),
    ]
    out = evaluate_multi_player_chain(edges, {101: 1.0, 102: 1.0})
    assert out["status"] == "AVAILABLE"
    assert out["confidence"] == pytest.approx(0.10)
    assert out["weakest_link_confidence"] == pytest.approx(0.10)


def test_Q_chain_beyond_governed_max_length_is_rejected():
    # Config governs max players in a chain. At the current max=4,
    # a five-player / four-edge candidate must fail closed.
    edges = [
        strong_edge(101, 102),
        strong_edge(102, 103),
        strong_edge(103, 104),
        strong_edge(104, 105),
    ]
    out = evaluate_multi_player_chain(
        edges,
        {101: 1.0, 102: 1.0, 103: 1.0, 104: 1.0},
    )
    assert out["status"] == "REJECTED_MAX_CHAIN_LENGTH"
    assert out["multiplier"] == pytest.approx(1.0)


def test_R_pairwise_only_runtime_remains_numerically_stable():
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
    kwargs = dict(
        match_rows=target,
        player_id=20,
        current_gw=6,
        opponent_team_id=86,
        current_context={"manager_id": "M1", "formation": "4-3-3"},
        linkups=[{**link, "target_role": "FINISHER"}],
        teammate_start_probabilities={21: 0.5},
        opponent_history_rows=[],
        opponent_history_scope="CURRENT-SEASON ONLY",
    )
    legacy_pairwise = build_contextual_dynamics(**kwargs)
    explicit_no_chain = build_contextual_dynamics(**kwargs, chains=[])
    assert legacy_pairwise["event_multipliers"] == explicit_no_chain["event_multipliers"]
    assert legacy_pairwise["linkup_network"]["chain_count"] == 0


def test_S_prior_season_matchup_affects_history_not_current_trajectory():
    current = [
        row(
            player=201,
            gw=gw,
            match=f"s-current-{gw}",
            opponent=60 + gw,
            xg=0.30,
            role="STRIKER",
        )
        for gw in range(1, 6)
    ]
    prior = row(
        player=201,
        gw=38,
        match="s-prior-opponent",
        opponent=99,
        xg=0.80,
        role="STRIKER",
        manager="M1",
        formation="4-3-3",
    )
    prior["season_age"] = 1
    context = build_contextual_dynamics(
        current,
        player_id=201,
        current_gw=5,
        opponent_team_id=99,
        current_context={
            "manager_id": "M1",
            "formation": "4-3-3",
            "player_role": "STRIKER",
        },
        opponent_history_rows=[prior],
        opponent_history_scope="MULTI-SEASON GOVERNED",
    )
    assert context["trajectory"]["sample_size"] == 5
    matchup = context["opponent_specific_matchup"]
    assert matchup["historical_meetings"] == 1
    assert matchup["prior_season_meetings"] == 1
    assert matchup["opponent_history_scope"] == "MULTI-SEASON GOVERNED"


def test_T_old_meeting_system_change_is_heavily_discounted():
    current = [
        row(
            player=202,
            gw=gw,
            match=f"t-current-{gw}",
            opponent=60 + gw,
            xg=0.60,
            role="STRIKER",
        )
        for gw in range(1, 5)
    ]
    prior = row(
        player=202,
        gw=38,
        match="t-prior",
        opponent=99,
        xg=0.05,
        role="STRIKER",
        manager="OLD",
        formation="5-4-1",
    )
    prior["season_age"] = 2
    same = build_contextual_dynamics(
        current,
        player_id=202,
        current_gw=4,
        opponent_team_id=99,
        current_context={
            "manager_id": "OLD",
            "formation": "5-4-1",
            "player_role": "STRIKER",
        },
        opponent_history_rows=[prior],
        opponent_history_scope="MULTI-SEASON GOVERNED",
    )["opponent_specific_matchup"]
    changed = build_contextual_dynamics(
        current,
        player_id=202,
        current_gw=4,
        opponent_team_id=99,
        current_context={
            "manager_id": "NEW",
            "formation": "4-3-3",
            "player_role": "STRIKER",
        },
        opponent_history_rows=[prior],
        opponent_history_scope="MULTI-SEASON GOVERNED",
    )["opponent_specific_matchup"]
    assert changed["tactical_similarity"] < same["tactical_similarity"]
    assert abs(changed["posterior_rate_modifier"] - 1.0) <= abs(
        same["posterior_rate_modifier"] - 1.0
    )


def test_U_zero_goals_strong_prior_xg_is_not_adverse_from_result_alone():
    current = [
        row(
            player=203,
            gw=gw,
            match=f"u-current-{gw}",
            opponent=60 + gw,
            xg=0.70,
            role="STRIKER",
        )
        for gw in range(1, 5)
    ]
    prior = row(
        player=203,
        gw=38,
        match="u-prior",
        opponent=99,
        xg=1.20,
        goals=0,
        role="STRIKER",
        manager="M1",
        formation="4-3-3",
    )
    prior["season_age"] = 1
    matchup = build_contextual_dynamics(
        current,
        player_id=203,
        current_gw=4,
        opponent_team_id=99,
        current_context={
            "manager_id": "M1",
            "formation": "4-3-3",
            "player_role": "STRIKER",
        },
        opponent_history_rows=[prior],
        opponent_history_scope="MULTI-SEASON GOVERNED",
    )["opponent_specific_matchup"]
    assert matchup["result_process"]["result_evidence"]["goals"] == 0
    assert matchup["result_process"]["process_evidence"]["xg"] == pytest.approx(1.2)
    assert matchup["classification"] != "ADVERSE"


def test_V_missing_prior_season_source_is_explicit_and_non_fabricated():
    current = [
        row(
            player=204,
            gw=gw,
            match=f"v-current-{gw}",
            opponent=60 + gw,
            xg=0.40,
            role="STRIKER",
        )
        for gw in range(1, 5)
    ]
    matchup = build_contextual_dynamics(
        current,
        player_id=204,
        current_gw=4,
        opponent_team_id=99,
        current_context={"manager_id": "M1", "formation": "4-3-3"},
        opponent_history_rows=[],
        opponent_history_scope="CURRENT-SEASON ONLY",
    )["opponent_specific_matchup"]
    assert matchup["opponent_history_scope"] == "CURRENT-SEASON ONLY"
    assert (
        matchup["prior_season_matchup_status"]
        == "UNAVAILABLE — NO GOVERNED MATCH-LEVEL FACTUAL SOURCE"
    )
    assert matchup["prior_season_meetings"] == 0



def test_runtime_projection_path_calls_chain_constructor_before_p13():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "models"
        / "historical_projection.py"
    ).read_text(encoding="utf-8")
    assert "construct_directional_chains(" in source
    assert "chains=multi_player_chains" in source
    assert "contextual_dynamics=contextual_by_fixture.get(" in source


def test_prediction_service_declares_truthful_current_season_history_scope():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "engines"
        / "prediction_service.py"
    ).read_text(encoding="utf-8")
    assert 'opponent_history_scope="CURRENT-SEASON ONLY"' in source
    assert "NO GOVERNED MATCH-LEVEL FACTUAL SOURCE" in source



def _anti_double_context(
    *,
    terminal_modifier: float,
    upstream_modifiers: list[float],
    terminal_without: float | None = None,
    p_starts: dict[int, float] | None = None,
    target_id: int = 303,
) -> dict:
    p_starts = dict(p_starts or {})
    edges = []
    source = 300
    for index, upstream_modifier in enumerate(upstream_modifiers):
        target = source + 1
        edges.append(
            strong_edge(
                source,
                target,
                modifier=upstream_modifier,
                confidence=1.0,
            )
        )
        source = target
    terminal = strong_edge(
        source,
        target_id,
        modifier=terminal_modifier,
        confidence=1.0,
    )
    if terminal_without is not None:
        terminal["without_player_modifier"] = terminal_without
    edges.append(terminal)

    default_probs = {
        int(edge["source_player_id"]): 1.0 for edge in edges
    }
    default_probs.update(p_starts)
    chain = evaluate_multi_player_chain(edges, default_probs)
    assert chain["status"] == "AVAILABLE"

    target_rows = [
        row(
            player=target_id,
            gw=gw,
            match=f"adc-{target_id}-{gw}",
            opponent=80 + gw,
            xg=0.45,
            xa=0.12,
            role="FINISHER",
        )
        for gw in range(1, 5)
    ]
    context = build_contextual_dynamics(
        target_rows,
        player_id=target_id,
        current_gw=4,
        opponent_team_id=99,
        current_context={"manager_id": "M1", "formation": "4-3-3"},
        linkups=[terminal],
        chains=[chain],
        teammate_start_probabilities=default_probs,
        opponent_history_rows=[],
        opponent_history_scope="CURRENT-SEASON ONLY",
    )
    return {
        "edges": edges,
        "terminal": terminal,
        "chain": chain,
        "context": context,
    }


def test_W_positive_terminal_overlap_is_not_multiplied_twice():
    # Pairwise B->C = 1.10; upstream residual chosen so raw joint = 1.16.
    upstream = 1.16 / 1.10
    out = _anti_double_context(
        terminal_modifier=1.10,
        upstream_modifiers=[upstream],
    )
    context = out["context"]
    chain = context["linkup_network"]["multi_player_chains"][0]
    assert context["event_multipliers"]["linkup_goal"] == pytest.approx(1.10)
    assert chain["raw_chain_multiplier"] == pytest.approx(1.16, abs=1e-6)
    assert chain["overlapping_pairwise_multiplier"] == pytest.approx(1.10)
    assert chain["incremental_chain_multiplier"] == pytest.approx(
        upstream, abs=1e-6
    )
    assert chain["anti_double_count_applied"] is True
    assert context["event_multipliers"]["final_dependency_goal"] == pytest.approx(
        1.16, abs=1e-6
    )
    assert context["event_multipliers"]["final_dependency_goal"] != pytest.approx(
        1.10 * 1.16, abs=1e-6
    )


def test_X_negative_terminal_overlap_is_not_multiplied_twice():
    upstream = 0.86 / 0.92
    out = _anti_double_context(
        terminal_modifier=0.92,
        upstream_modifiers=[upstream],
    )
    context = out["context"]
    chain = context["linkup_network"]["multi_player_chains"][0]
    assert context["event_multipliers"]["linkup_goal"] == pytest.approx(0.92)
    assert chain["raw_chain_multiplier"] == pytest.approx(0.86, abs=1e-6)
    assert chain["incremental_chain_multiplier"] == pytest.approx(
        upstream, abs=1e-6
    )
    assert context["event_multipliers"]["final_dependency_goal"] == pytest.approx(
        0.86, abs=1e-6
    )
    assert context["event_multipliers"]["final_dependency_goal"] != pytest.approx(
        0.92 * 0.86, abs=1e-6
    )


def test_Y_neutral_higher_order_effect_leaves_pairwise_unchanged():
    out = _anti_double_context(
        terminal_modifier=1.10,
        upstream_modifiers=[1.0],
    )
    context = out["context"]
    chain = context["linkup_network"]["multi_player_chains"][0]
    assert chain["incremental_chain_multiplier"] == pytest.approx(1.0)
    assert chain["effective_chain_multiplier"] == pytest.approx(1.0)
    assert context["event_multipliers"]["final_dependency_goal"] == pytest.approx(
        1.10
    )


def test_Z_real_higher_order_positive_effect_survives_residualization():
    upstream = 1.18 / 1.08
    out = _anti_double_context(
        terminal_modifier=1.08,
        upstream_modifiers=[upstream],
    )
    context = out["context"]
    chain = context["linkup_network"]["multi_player_chains"][0]
    assert chain["incremental_chain_multiplier"] > 1.0
    assert context["event_multipliers"]["final_dependency_goal"] == pytest.approx(
        1.18, abs=1e-6
    )


def test_AA_middle_node_absent_neutralizes_chain_not_pairwise_absence_state():
    upstream = 1.16 / 1.10
    out = _anti_double_context(
        terminal_modifier=1.10,
        terminal_without=0.90,
        upstream_modifiers=[upstream],
        p_starts={301: 0.0},
    )
    context = out["context"]
    chain = context["linkup_network"]["multi_player_chains"][0]
    assert chain["chain_intact_probability"] == pytest.approx(0.0)
    assert chain["incremental_chain_multiplier"] == pytest.approx(1.0)
    # Pairwise B->C separately owns the B-absent state.
    assert context["event_multipliers"]["linkup_goal"] == pytest.approx(0.90)
    assert context["event_multipliers"]["final_dependency_goal"] == pytest.approx(
        0.90
    )


def test_AB_half_start_is_between_intact_and_broken_without_double_penalty():
    upstream = 1.16 / 1.10
    intact = _anti_double_context(
        terminal_modifier=1.10,
        terminal_without=0.90,
        upstream_modifiers=[upstream],
        p_starts={301: 1.0},
    )["context"]
    half = _anti_double_context(
        terminal_modifier=1.10,
        terminal_without=0.90,
        upstream_modifiers=[upstream],
        p_starts={301: 0.5},
    )["context"]
    broken = _anti_double_context(
        terminal_modifier=1.10,
        terminal_without=0.90,
        upstream_modifiers=[upstream],
        p_starts={301: 0.0},
    )["context"]
    broken_final = broken["event_multipliers"]["final_dependency_goal"]
    half_final = half["event_multipliers"]["final_dependency_goal"]
    intact_final = intact["event_multipliers"]["final_dependency_goal"]
    assert broken_final < half_final < intact_final
    assert (
        half["linkup_network"]["multi_player_chains"][0][
            "incremental_chain_multiplier"
        ]
        > 1.0
    )


def test_AC_two_chains_sharing_terminal_edge_apply_pairwise_once():
    terminal = strong_edge(
        402,
        404,
        modifier=1.10,
        confidence=1.0,
    )
    edge_a = strong_edge(
        401,
        402,
        modifier=1.05,
        confidence=1.0,
    )
    edge_c = strong_edge(
        403,
        402,
        modifier=1.04,
        confidence=1.0,
    )
    probs = {401: 1.0, 402: 1.0, 403: 1.0}
    chain_a = evaluate_multi_player_chain([edge_a, terminal], probs)
    chain_c = evaluate_multi_player_chain([edge_c, terminal], probs)
    target_rows = [
        row(
            player=404,
            gw=gw,
            match=f"ac-{gw}",
            opponent=60 + gw,
            xg=0.50,
            role="FINISHER",
        )
        for gw in range(1, 5)
    ]
    context = build_contextual_dynamics(
        target_rows,
        player_id=404,
        current_gw=4,
        opponent_team_id=99,
        current_context={"manager_id": "M1", "formation": "4-3-3"},
        linkups=[terminal],
        chains=[chain_a, chain_c],
        teammate_start_probabilities=probs,
        opponent_history_rows=[],
        opponent_history_scope="CURRENT-SEASON ONLY",
    )
    assert context["event_multipliers"]["linkup_goal"] == pytest.approx(1.10)
    assert context["event_multipliers"]["chain_goal"] == pytest.approx(
        1.05 * 1.04, abs=1e-6
    )
    assert context["event_multipliers"]["final_dependency_goal"] == pytest.approx(
        1.10 * 1.05 * 1.04, abs=1e-6
    )
    assert context["event_multipliers"]["overlap_removed"][
        "terminal_pairwise_edge_ids"
    ] == ["402->404"]


def test_AD_pairwise_only_numerics_are_exactly_unchanged():
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
    common = dict(
        match_rows=target,
        player_id=20,
        current_gw=6,
        opponent_team_id=86,
        current_context={"manager_id": "M1", "formation": "4-3-3"},
        linkups=[{**link, "target_role": "FINISHER"}],
        teammate_start_probabilities={21: 0.5},
        opponent_history_rows=[],
        opponent_history_scope="CURRENT-SEASON ONLY",
    )
    before_semantics = build_contextual_dynamics(**common)
    explicit_no_chain = build_contextual_dynamics(**common, chains=[])
    assert before_semantics["event_multipliers"] == explicit_no_chain[
        "event_multipliers"
    ]
    assert before_semantics["linkup_network"]["chain_count"] == 0


def test_AE_neutral_terminal_pairwise_still_allows_chain_interaction():
    out = _anti_double_context(
        terminal_modifier=1.0,
        terminal_without=1.0,
        upstream_modifiers=[1.12],
    )
    context = out["context"]
    chain = context["linkup_network"]["multi_player_chains"][0]
    assert context["event_multipliers"]["linkup_goal"] == pytest.approx(1.0)
    assert chain["incremental_chain_multiplier"] == pytest.approx(1.12)
    assert context["event_multipliers"]["final_dependency_goal"] == pytest.approx(
        1.12
    )


def test_AF_residual_chain_still_propagates_through_p13_distribution():
    upstream = 1.18 / 1.08
    with_chain_context = _anti_double_context(
        terminal_modifier=1.08,
        upstream_modifiers=[upstream],
    )["context"]
    pairwise_only_context = _anti_double_context(
        terminal_modifier=1.08,
        upstream_modifiers=[1.0],
    )["context"]

    kwargs = dict(
        player={"id": 303, "element_type": 4, "position": "FWD"},
        minutes_projection=full_start_minutes(),
        matchup=fixture(),
        home=True,
        rates=rates(),
        league_baseline={"home_goals": 1.6, "away_goals": 1.2},
    )
    with_chain = project_player_fixture(
        **kwargs, contextual_dynamics=with_chain_context
    )
    pairwise_only = project_player_fixture(
        **kwargs, contextual_dynamics=pairwise_only_context
    )
    assert (
        with_chain["event_probabilities"]["p_goal_return"]
        > pairwise_only["event_probabilities"]["p_goal_return"]
    )
    assert (
        with_chain["event_probabilities"]["p_assist_return"]
        > pairwise_only["event_probabilities"]["p_assist_return"]
    )
    assert (
        with_chain["event_probabilities"]["p_attacking_return"]
        > pairwise_only["event_probabilities"]["p_attacking_return"]
    )
    assert (
        with_chain["event_probabilities"]["p_total_ga_ge_2"]
        > pairwise_only["event_probabilities"]["p_total_ga_ge_2"]
    )
    assert (
        with_chain["point_distribution"]["p_haul_10_plus"]
        >= pairwise_only["point_distribution"]["p_haul_10_plus"]
    )
    assert (
        with_chain["point_distribution"]["p_fpl_blank"]
        < pairwise_only["point_distribution"]["p_fpl_blank"]
    )
    assert with_chain["mean"] > pairwise_only["mean"]
    assert with_chain["std"] != pairwise_only["std"]
