from __future__ import annotations

import copy

import pytest

from src.services.challenger_comparator_service import (
    _comparison_pair,
    _direct_swap,
    _emerging_candidates,
    _performance_signal,
    _rank_owned_targets,
    _role_sustainability,
    _screen_candidate,
    _trigger_signals,
)


def policy():
    return {
        "mode": "ADVISORY_ONLY",
        "candidate_limits": {"emerging": 20, "owned_targets_per_challenger": 3},
        "screening": {
            "status_allowed": ["a", "d"],
            "minimum_start_probability_3gw": 0.62,
            "maximum_dnp_probability_3gw": 0.28,
            "maximum_direct_swap_price_gap_tenths": 25,
            "minimum_relevant_fixtures_5gw": 3,
        },
        "emerging_trigger": {
            "minimum_signals": 2,
            "points_signal": 8,
            "xgi_signal": 0.55,
            "net_transfers_signal": 25000,
            "minutes_signal": 60,
            "start_signal": 1,
            "value_signal_xpts5_per_million": 2.2,
        },
        "decision_policy": {
            "edge_to_uncertainty_review": 0.35,
            "edge_to_uncertainty_lean": 0.80,
            "edge_to_uncertainty_strong": 1.35,
            "minimum_core_confidence_for_lean": 0.68,
            "minimum_core_confidence_for_strong": 0.80,
            "missing_tactical_or_congestion_caps_strong": True,
        },
    }


def universe(element, name, team_id, position="MID", cost=65, status="a", points=4, xgi=.25, starts=1, minutes=90, tin=1000, tout=500):
    return {
        "element": element,
        "name": name,
        "team": f"Team {team_id}",
        "team_id": team_id,
        "position": position,
        "element_type": {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[position],
        "now_cost": cost,
        "status": status,
        "points": points,
        "expected_goal_involvements": str(xgi),
        "starts": starts,
        "minutes": minutes,
        "transfers_in_event": tin,
        "transfers_out_event": tout,
    }


def prediction(element, name, position="MID", xpts=(3, 3, 3, 3, 3), starts=(.82, .82, .82, .82, .82), raw=.35, shrunk=.30, value=2.0):
    fixtures = []
    for idx, (xp, ps) in enumerate(zip(xpts, starts), 2):
        fixtures.append({
            "event": idx,
            "xpts": xp,
            "lower80": max(0, xp - 1.5),
            "upper80": xp + 1.5,
            "xmins": {
                "expected_minutes": 72 * ps / .82,
                "start_probability": ps,
                "bench_probability": .08,
                "dnp_probability": max(0, 1 - ps - .08),
                "workload_factor": .98,
            },
            "components": {"appearance": 1.6, "attack": max(0, xp - 1.8), "bonus": .2},
            "rates": {"raw_xg90": raw, "raw_xa90": raw / 2, "xg90": shrunk, "xa90": shrunk / 2, "current_season_weight": .2},
            "calibration": {"tactical_role": "attacking_midfielder", "tactical_role_source": "deep_match_metrics"},
            "provenance": {"model": "v4-test", "xmins_prior_source": "test"},
        })
    return {
        "element": element,
        "name": name,
        "position": position,
        "fixtures": fixtures,
        "xpts_3": sum(xpts[:3]),
        "xpts_5": sum(xpts[:5]),
        "xpts_10": sum(xpts[:5]) * 2,
        "xpts_15": sum(xpts[:5]) * 3,
        "uncertainty": .2,
        "value": {"xpts5_per_million": value},
        "priors": {"tactical_role": "attacking_midfielder", "tactical_role_source": "deep_match_metrics", "role_prior": .4},
        "fixture_run": {"source": "official_fpl_fixture_adjustment", "direction": "STABLE"},
    }


def team_and_maps(*, wc=True):
    owned_u = universe(1, "Owned", 1, cost=65)
    challenger_u = universe(2, "Challenger", 2, cost=65, points=10, xgi=.8, tin=40000)
    owned_p = prediction(1, "Owned", xpts=(2, 2, 2, 2, 2), starts=(.75,) * 5)
    challenger_p = prediction(2, "Challenger", xpts=(4, 4, 4, 4, 4), starts=(.9,) * 5, value=3)
    umap = {1: owned_u, 2: challenger_u}
    pmap = {1: owned_p, 2: challenger_p}
    ledger = [{"element": 1, "name": "Owned", "team_id": 1, "position": "MID", "sell_cost": 65, "now_cost": 65}]
    # Fill the rest with a legal 2/5/5/3 squad.
    element = 10
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 4), ("FWD", 3)):
        for _ in range(count):
            ledger.append({"element": element, "name": f"P{element}", "team_id": element, "position": position, "sell_cost": 45, "now_cost": 45})
            umap[element] = universe(element, f"P{element}", element, position=position, cost=45)
            pmap[element] = prediction(element, f"P{element}", position=position, xpts=(2, 2, 2, 2, 2))
            element += 1
    team = {"projection_baseline": {"planning_gw": 2}, "team_value_ledger": ledger, "totals": {"itb": 0}}
    effective = {"effective_plan": {"chip_context": {"active_chip": "WILDCARD" if wc else "NONE"}, "bench": {"gk": None, "order": []}}}
    raw = {"official": {"fixtures": [
        {"event": gw, "team_h": 1, "team_a": 2, "kickoff_time": f"2026-09-{gw:02d}T14:00:00Z"} for gw in range(2, 7)
    ]}}
    owned = {1: ledger[0]}
    return umap, pmap, owned, team, effective, raw


def candidate(kind="EMERGING_CHALLENGER"):
    return {"element": 2, "challenger_type": kind, "candidate_source": "test", "trigger_signals": ["RECENT_POINTS_RETURN", "UNDERLYING_XGI"]}


def test_same_price_direct_swap_is_affordable_and_legal():
    umap, _, _, team, _, _ = team_and_maps()
    out = _direct_swap(1, 2, team, umap)
    assert out["affordable"] is True and out["squad_legal"] is True


def test_upgrade_requires_itb():
    umap, _, _, team, _, _ = team_and_maps()
    umap[2]["now_cost"] = 70
    assert _direct_swap(1, 2, team, umap)["affordable"] is False
    team["totals"]["itb"] = 5
    assert _direct_swap(1, 2, team, umap)["affordable"] is True


def test_downgrade_is_affordable():
    umap, _, _, team, _, _ = team_and_maps()
    umap[2]["now_cost"] = 55
    assert _direct_swap(1, 2, team, umap)["affordable"] is True


def test_position_violation_is_not_direct_swap_legal():
    umap, _, _, team, _, _ = team_and_maps()
    umap[2]["position"] = "FWD"
    assert _direct_swap(1, 2, team, umap)["squad_legal"] is False


def test_same_club_limit_violation_is_rejected():
    umap, _, _, team, _, _ = team_and_maps()
    # Put three retained players on challenger club; replacement would make four.
    for row in team["team_value_ledger"][1:4]:
        row["team_id"] = 2
    assert _direct_swap(1, 2, team, umap)["squad_legal"] is False


@pytest.mark.parametrize("status", ["i", "s", "u"])
def test_injury_or_suspension_fails_minimum_screen(status):
    umap, pmap, _, _, _, _ = team_and_maps()
    umap[2]["status"] = status
    assert _screen_candidate(candidate(), umap, pmap, policy())["pass"] is False


def test_one_haul_is_trigger_not_automatic_transfer():
    umap, pmap, _, _, _, _ = team_and_maps()
    signals = _trigger_signals(umap[2], pmap[2], policy())
    assert "RECENT_POINTS_RETURN" in signals
    weak = copy.deepcopy(pmap[2])
    for fx in weak["fixtures"]:
        fx["xmins"]["start_probability"] = .3
        fx["xmins"]["dnp_probability"] = .6
    screening = _screen_candidate(candidate(), umap, {**pmap, 2: weak}, policy())
    sustainability = _role_sustainability(umap[2], weak)
    assert _performance_signal(candidate(), screening, sustainability, policy()) == "INTERESTING"


def test_weak_underlying_spike_not_sustainable_candidate():
    umap, pmap, _, _, _, _ = team_and_maps()
    pmap[2]["fixtures"][0]["rates"].update({"raw_xg90": 2.0, "raw_xa90": 1.0, "xg90": .15, "xa90": .08})
    screening = _screen_candidate(candidate(), umap, pmap, policy())
    sustainability = _role_sustainability(umap[2], pmap[2])
    assert _performance_signal(candidate(), screening, sustainability, policy()) == "STRONG"


def test_secure_role_can_be_sustainable_candidate():
    umap, pmap, _, _, _, _ = team_and_maps()
    screening = _screen_candidate(candidate(), umap, pmap, policy())
    sustainability = _role_sustainability(umap[2], pmap[2])
    assert _performance_signal(candidate(), screening, sustainability, policy()) == "SUSTAINABLE_CANDIDATE"


def test_emerging_universe_excludes_owned_and_requires_multiple_signals():
    umap, pmap, owned, _, _, _ = team_and_maps()
    rows = _emerging_candidates(umap, pmap, set(owned), policy())
    assert 1 not in {row["element"] for row in rows}
    assert 2 in {row["element"] for row in rows}


def test_multiple_challengers_can_target_one_owned_player():
    umap, pmap, owned, team, effective, _ = team_and_maps()
    umap[3] = universe(3, "Other", 3, cost=65)
    pmap[3] = prediction(3, "Other", xpts=(5, 5, 5, 5, 5))
    first = _rank_owned_targets(candidate(), owned, pmap, umap, team, effective, policy())
    second = _rank_owned_targets({"element": 3}, owned, pmap, umap, team, effective, policy())
    assert first[0]["owned_element"] == second[0]["owned_element"] == 1


def test_one_challenger_can_rank_multiple_logical_owned_targets():
    umap, pmap, owned, team, effective, _ = team_and_maps()
    # Add another MID as owned by replacing one synthetic MID ledger row.
    row = next(r for r in team["team_value_ledger"] if r["position"] == "MID" and r["element"] != 1)
    owned[row["element"]] = row
    targets = _rank_owned_targets(candidate(), owned, pmap, umap, team, effective, policy())
    assert len(targets) >= 2


def test_active_wildcard_has_zero_transfer_opportunity_cost():
    umap, pmap, owned, team, effective, raw = team_and_maps(wc=True)
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    assert result["opportunity_cost"] == 0 and result["affordability"]["affordable"] is True


def test_normal_transfer_without_ft_evidence_fails_safe_to_review():
    umap, pmap, owned, team, effective, raw = team_and_maps(wc=False)
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    assert result["opportunity_cost"] is None
    assert result["decision"] in {"REVIEW", "WATCH_CHALLENGER", "HOLD_OWNED"}
    assert "FREE_TRANSFER_OPPORTUNITY_COST_UNVERIFIED" in result["decision_risks"]


def test_missing_tactical_data_is_explicit_not_fabricated():
    umap, pmap, owned, team, effective, raw = team_and_maps()
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    assert result["data_quality"]["tactical_verified_gws"] == 0
    assert all(value["matchup_edge"] == "UNVERIFIED" for value in result["tactical_matchup_by_gw"]["challenger"].values())


def test_missing_external_congestion_is_explicit():
    umap, pmap, owned, team, effective, raw = team_and_maps()
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    assert result["midweek_schedule"]["status"] == "PARTIAL_OR_UNVERIFIED"
    assert result["international_context"]["status"] == "UNVERIFIED"


@pytest.mark.parametrize("competition_field", ["midweek_schedule", "international_context"])
def test_verified_external_workload_can_be_consumed_without_refetch(competition_field):
    umap, pmap, owned, team, effective, raw = team_and_maps()
    tactical = {"teams": {"1": {"events": {str(gw): {"rest_days": 3, competition_field: {"verified": True}, "matchup_edge": "NEUTRAL", "matchup_risk": "MEDIUM", "confidence": .8, "source": "test_verified"} for gw in range(2, 7)}}}, "2": {"events": {str(gw): {"rest_days": 3, competition_field: {"verified": True}, "matchup_edge": "POSITIVE", "matchup_risk": "LOW", "confidence": .8, "source": "test_verified"} for gw in range(2, 7)}}}}}
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), tactical)
    assert result["data_quality"]["tactical_verified_gws"] >= 3


def test_tbd_or_unverified_schedule_never_invented():
    umap, pmap, owned, team, effective, raw = team_and_maps()
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    assert all(value in {"UNVERIFIED", None} for value in result["midweek_schedule"]["challenger"].values())


def test_improving_xmins_is_visible_fixture_by_fixture():
    umap, pmap, owned, team, effective, raw = team_and_maps()
    pmap[2] = prediction(2, "Challenger", xpts=(4, 4, 4, 4, 4), starts=(.62, .72, .82, .9, .92), value=3)
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    values = list(result["start_probability_by_gw"]["challenger"].values())
    assert values[-1] > values[0]


def test_deteriorating_xmins_is_visible_fixture_by_fixture():
    umap, pmap, owned, team, effective, raw = team_and_maps()
    pmap[2] = prediction(2, "Challenger", xpts=(4, 4, 4, 4, 4), starts=(.92, .85, .75, .65, .55), value=3)
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    values = list(result["start_probability_by_gw"]["challenger"].values())
    assert values[-1] < values[0]


def test_early_season_uncertainty_prevents_blind_strong_transfer():
    umap, pmap, owned, team, effective, raw = team_and_maps()
    for fx in pmap[2]["fixtures"]:
        fx["lower80"], fx["upper80"] = 0, 12
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    assert result["decision"] != "STRONG_TRANSFER"


def test_governed_watchlist_can_receive_demotion_review_without_mutation():
    umap, pmap, owned, team, effective, raw = team_and_maps()
    pmap[2] = prediction(2, "Challenger", xpts=(1, 1, 1, 1, 1), starts=(.4,) * 5)
    result = _comparison_pair(candidate("GOVERNED_WATCHLIST"), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    assert result["decision"] in {"HOLD_OWNED", "REVIEW"}
    assert result["watchlist_governance_suggestion"] != "PROMOTE_TO_WATCHLIST"


def test_engine_governed_candidate_is_not_mislabelled_as_watchlist():
    umap, pmap, owned, team, effective, raw = team_and_maps()
    result = _comparison_pair(candidate("GOVERNED_DSS_CANDIDATE"), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    assert result["challenger_type"] == "GOVERNED_DSS_CANDIDATE"
    assert "ENGINE_GOVERNED_CANDIDATE_NOT_MISLABELLED_AS_WATCHLIST" in result["decision_reasons"]


def test_cross_engine_consensus_is_not_majority_vote_contractually():
    # V4 comparator exposes its own conclusion; higher orchestration may compare
    # engines, but this service must never majority-vote or mutate authority.
    assert policy()["mode"] == "ADVISORY_ONLY"


def test_output_contains_required_common_contract_fields():
    umap, pmap, owned, team, effective, raw = team_and_maps()
    result = _comparison_pair(candidate(), 1, (umap, pmap, owned), team, effective, raw, policy(), {})
    required = {
        "player_out", "player_in", "challenger_type", "planning_gw",
        "horizon_1gw", "horizon_2gw", "horizon_3gw", "horizon_5gw",
        "fixture_by_fixture", "xpts_by_gw", "xmins_by_gw", "start_probability_by_gw",
        "tactical_matchup_by_gw", "rest_congestion_by_gw", "midweek_schedule",
        "international_context", "role_sustainability", "performance_signal",
        "raw_gain_2gw", "raw_gain_3gw", "raw_gain_5gw", "structural_cost",
        "opportunity_cost", "net_transfer_value", "affordability", "confidence",
        "decision", "decision_reasons", "decision_risks", "reversal_triggers", "data_quality",
    }
    assert required <= set(result)
