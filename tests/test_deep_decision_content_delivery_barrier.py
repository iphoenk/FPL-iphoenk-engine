from __future__ import annotations

from pathlib import Path

from src.engines.v12_deep_delivery import (
    select_personal_evidence,
    validate_deep_decision_content_delivery,
)
from src.engines.v12_package_utility import (
    select_stage3_material_mc_routes,
)
from src.engines.v12_report_orchestration import (
    build_watchlist20,
    render_deep_text,
)


def _section(section_id: str, label: str, content: dict, state: str = "COMPLETE"):
    return {
        "section_id": section_id,
        "label": label,
        "state": state,
        "content": content,
    }


def _action_board(action: str = "WAIT", best_alternative=None):
    return _section(
        "S18",
        "ACTION BOARD",
        {
            "NOW": action,
            "NEXT": "refresh evidence",
            "TRIGGER TO ACT": "canonical threshold",
            "LATEST SAFE DECISION POINT": "next governed checkpoint",
            "COST OF WAITING": {"status": "AVAILABLE", "points": 0.2},
            "ABORT / REVERSAL": "material evidence reversal",
            "BEST ALTERNATIVE": best_alternative or {"route": "R1"},
        },
    )


def _route(
    route_id: str = "R1",
    *,
    transfer_count: int = 1,
    net: float = 1.2,
    verdict: str = "PREPARE",
):
    outs = [
        {
            "element": idx + 1,
            "name": f"P{idx + 1:02d}",
            "sell_value": 50,
            "xmins": 72,
            "p_start": 0.82,
            "tactical_role": "ROLE_OUT",
            "fixture": {"opponent": "T1"},
        }
        for idx in range(transfer_count)
    ]
    ins = [
        {
            "element": 101 + idx,
            "name": f"P{101 + idx:02d}",
            "buy_price": 48 if transfer_count > 1 and idx == 0 else 52,
            "xmins": 84,
            "p_start": 0.94,
            "tactical_role": "ROLE_IN",
            "fixture": {"opponent": "T2"},
        }
        for idx in range(transfer_count)
    ]
    return {
        "route": route_id,
        "route_kind": (
            "DIRECT / 1-TRANSFER"
            if transfer_count == 1
            else "FUNDED / 2-TRANSFER"
        ),
        "moves": {"out": outs, "in": ins},
        "bank_before": 2,
        "affordability": "SUPPORTED",
        "transfer_cost": {
            "hit": 0 if transfer_count == 1 else 4,
            "ft_usage": {"free_transfers": 1},
            "economics_status": "PASS",
            "bank_after": 0,
        },
        "gw1_net": net,
        "two_gw_if_relevant": net + 0.4,
        "three_gw": net + 1.0,
        "five_gw": net + 2.0,
        "raw_gain": net + (0.0 if transfer_count == 1 else 4.0),
        "net_gain": net,
        "p_beats_hold": 0.62 if net > 0 else 0.38,
        "p_delta_meaningful": 0.55 if net > 0 else 0.20,
        "Q10": -2.0,
        "Q25": -0.5,
        "median": net,
        "Q75": 3.0,
        "Q90": 5.0,
        "football_1GW": net + 0.2,
        "football_3GW": net + 1.2,
        "football_5GW": net + 2.2,
        "expected_regret": 0.3,
        "robustness": {"status": "PASS"},
        "sensitivity": {"reversal_risk": "LOW"},
        "price_risk": {"status": "AVAILABLE"},
        "structure_effect": {"formation_changed": False},
        "mini_league_utility": {"rank_gain_utility": 0.1},
        "tactical_fixture_effect": [{"name": ins[0]["name"], "p_start": 0.94}],
        "action_verdict": verdict,
    }


def _deep_report(routes, *, extra_sections=()):
    s14 = _section(
        "S14",
        "PACKAGE OPTIMIZER / TRANSFER FRONTIER",
        {
            "package_search_proof": {
                "owned_evaluated": 15,
                "owned_expected": 15,
                "eligible_universe_evaluated": 600,
                "eligible_universe_expected": 600,
                "outgoing_candidate_count": 15,
                "legal_route_count": 3000,
                "hold_included": True,
                "lossy_pruning": False,
                "search_authority": "FULL",
            },
            "package_routes": [
                {
                    "route": "HOLD",
                    "route_kind": "HOLD",
                    "moves": {"out": [], "in": []},
                    "bank_before": 2,
                    "affordability": "SUPPORTED",
                    "transfer_cost": {"bank_after": 2},
                    "gw1_net": 0.0,
                    "two_gw_if_relevant": 0.0,
                    "three_gw": 0.0,
                    "five_gw": 0.0,
                    "raw_gain": 0.0,
                    "net_gain": 0.0,
                    "p_beats_hold": 0.5,
                    "Q10": 0.0,
                    "Q25": 0.0,
                    "median": 0.0,
                    "Q75": 0.0,
                    "Q90": 0.0,
                    "action_verdict": "WAIT",
                },
                *routes,
            ],
            "monte_carlo": {
                "actual_paths": 500_000,
                "canonical_pass": True,
                "convergence_evidence": {"status": "PASS"},
            },
        },
    )
    return {
        "sections": [
            s14,
            *extra_sections,
            _action_board(
                action=(
                    routes[0].get("action_verdict")
                    if routes else "WAIT"
                ),
                best_alternative=(routes[0] if routes else {"route": "HOLD"}),
            ),
        ]
    }


def _rich_all15_rows():
    return [
        {
            "element_id": i,
            "name": f"P{i:02d}",
            "availability": 0.98,
            "p_start": 0.90,
            "xmins": 80,
            "posterior_signal": {"posterior_rates": {"goal": 0.2}},
            "role_detail": {"tactical_role": "ROLE", "set_piece": "NONE", "penalty": "NONE"},
            "fixture_detail": {"opponent": "T2", "home": True},
            "defensive_contribution": {"status": "AVAILABLE"},
            "projection_1gw": 4.0,
            "projection_3gw": 12.0,
            "projection_5gw": 20.0,
            "price_optionality": {"current_price": 50},
            "mini_league_relevance": {"ownership_pct": 50.0},
            "action": "HOLD",
        }
        for i in range(1, 16)
    ]


def test_a_direct_affordable_upgrade_is_visible():
    report = _deep_report([_route()])
    body = render_deep_text(report)
    assert "DIRECT / 1-TRANSFER" in body
    assert "OUT → IN P01 → P101" in body
    assert "BANK BEFORE" in body and "BANK AFTER" in body
    assert validate_deep_decision_content_delivery(report, body) == []


def test_b_unaffordable_target_can_reach_funded_two_transfer_mc_surface():
    hold = {
        "route_id": "HOLD",
        "football_route_utility": {
            "per_gw": [
                {"status": "READY", "expected_fpl_points": 50.0},
                {"status": "READY", "expected_fpl_points": 50.0},
                {"status": "READY", "expected_fpl_points": 50.0},
                {"status": "READY", "expected_fpl_points": 50.0},
                {"status": "READY", "expected_fpl_points": 50.0},
            ]
        },
    }
    direct = {
        **hold,
        "route_id": "DIRECT",
        "transfer_count": 1,
        "football_route_utility": {
            "per_gw": [
                {"status": "READY", "expected_fpl_points": 51.0},
                {"status": "READY", "expected_fpl_points": 51.0},
                {"status": "READY", "expected_fpl_points": 51.0},
                {"status": "READY", "expected_fpl_points": 51.0},
                {"status": "READY", "expected_fpl_points": 51.0},
            ]
        },
        "lineup_impact": {},
        "transfer_economics": {"status": "PASS"},
    }
    funded = {
        **hold,
        "route_id": "FUNDED",
        "transfer_count": 2,
        "football_route_utility": {
            "per_gw": [
                {"status": "READY", "expected_fpl_points": 50.8},
                {"status": "READY", "expected_fpl_points": 51.5},
                {"status": "READY", "expected_fpl_points": 52.0},
                {"status": "READY", "expected_fpl_points": 52.0},
                {"status": "READY", "expected_fpl_points": 52.0},
            ]
        },
        "lineup_impact": {},
        "transfer_economics": {"status": "PARTIAL"},
    }
    selected = select_stage3_material_mc_routes(
        {
            "model_owner": "V12_PACKAGE_UTILITY",
            "search_authority": "FULL",
            "routes": [hold, direct, funded],
        },
        max_routes=3,
    )
    assert selected["route_ids"] == ["HOLD", "DIRECT", "FUNDED"]
    assert selected["transfer_depth_coverage"]["funded_2_transfer"] is True

    report = _deep_report([_route("FUNDED", transfer_count=2)])
    body = render_deep_text(report)
    assert "FUNDED / 2-TRANSFER" in body
    assert "OUT → IN P01, P02 → P101, P102" in body
    assert validate_deep_decision_content_delivery(report, body) == []


def test_c_hit_economics_can_leave_hold_as_canonical_winner():
    route = _route("R_NEG", transfer_count=2, net=-1.1, verdict="WAIT")
    report = _deep_report([route])
    body = render_deep_text(report)
    assert "NET GAIN -1.1" in body
    assert "NOW" in body and "WAIT" in body
    assert validate_deep_decision_content_delivery(report, body) == []


def test_d_positive_funded_package_preserves_prepare_or_act_decision():
    route = _route("R_POS", transfer_count=2, net=2.5, verdict="PREPARE")
    report = _deep_report([route])
    body = render_deep_text(report)
    assert "PREPARE" in body
    assert "NET GAIN 2.5" in body
    assert validate_deep_decision_content_delivery(report, body) == []


def test_e_high_owned_candidate_is_not_rejected_by_delivery_layer():
    route = _route(verdict="PREPARE")
    route["mini_league_utility"] = {
        "ownership_pct": 82.0,
        "football_ev_precedes_leverage": True,
    }
    report = _deep_report([route])
    body = render_deep_text(report)
    assert "football_ev_precedes_leverage" in body
    assert validate_deep_decision_content_delivery(report, body) == []


def test_f_differential_utility_is_visible_without_forcing_selection():
    route = _route(verdict="WAIT")
    route["mini_league_utility"] = {
        "ownership_pct": 7.0,
        "rank_gain_utility": 0.4,
        "selected_by_football_ev": False,
    }
    report = _deep_report([route])
    body = render_deep_text(report)
    assert "rank_gain_utility" in body
    assert "WAIT" in body
    assert validate_deep_decision_content_delivery(report, body) == []


def test_g_complete_58_manager_mini_league_cannot_be_placeholder():
    mini = _section(
        "S15B",
        "ICON+ MINI-LEAGUE",
        {
            "coverage_state": "FULL",
            "current_league_context": {
                "our_rank": 7,
                "manager_count": 58,
                "our_total_points": 344,
                "leader_points": 361,
                "points_to_leader": 17,
            },
            "exposures": [],
        },
    )
    report = _deep_report([_route()], extra_sections=[mini])
    body = render_deep_text(report)
    failures = validate_deep_decision_content_delivery(report, body)
    assert "MINI_LEAGUE_PLACEHOLDER_ONLY" in failures


def test_h_raw_predictor_exact20_is_semantically_enforced():
    rise = _section(
        "S12",
        "RISE20",
        {"rows": [{"element_id": 200 + i} for i in range(20)]},
    )
    fall = _section(
        "S13",
        "FALL20",
        {"rows": [{"element_id": 300 + i} for i in range(20)]},
    )
    report = _deep_report([_route()], extra_sections=[rise, fall])
    body = render_deep_text(report)
    assert not [
        failure for failure in validate_deep_decision_content_delivery(report, body)
        if "RISE20_VISIBLE_COUNT" in failure or "FALL20_VISIBLE_COUNT" in failure
    ]
    rise["content"]["rows"].pop()
    failures = validate_deep_decision_content_delivery(report, render_deep_text(report))
    assert "RISE20_VISIBLE_COUNT=19/20" in failures


def test_i_watchlist_requires_exact_five_per_position_when_supportable():
    universe = []
    element = 100
    for position in ("GK", "DEF", "MID", "FWD"):
        for rank in range(5):
            universe.append(
                {
                    "element_id": element,
                    "name": f"P{element}",
                    "position": position,
                    "eligible": True,
                    "canonical_evaluation_complete": True,
                    "canonical_rank": rank + 1,
                    "football_score": 100 - rank,
                }
            )
            element += 1
    got = build_watchlist20(
        evaluated_universe=universe,
        owned_element_ids=[],
        universe_authority="FULL",
    )
    assert got["state"] == "COMPLETE"
    assert got["available_count"] == 20
    assert got["position_counts"] == {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}


def test_j_current15_supportable_requires_exactly_15_rich_individual_analyses():
    s16 = _section(
        "S16",
        "ALL15 TACTICAL / PROBABILITY REVIEW",
        {"rows": _rich_all15_rows()},
    )
    report = _deep_report([_route()], extra_sections=[s16])
    body = render_deep_text(report)
    failures = validate_deep_decision_content_delivery(report, body)
    assert not [failure for failure in failures if failure.startswith("ALL15_")]
    assert "posterior" in body.lower()


def test_k_detailed_gw1_now_evidence_requires_match_by_match_visible_rows():
    s16b = _section(
        "S16B",
        "POST-MATCH REVIEW GW1 → NOW",
        {
            "recency_weighting": "EXPONENTIAL_HALF_LIFE_GW",
            "bayesian_update": "POSTERIOR_RECENT_RATE_WITH_SHRINKAGE",
            "our15": [
                {
                    "element_id": 1,
                    "player": "P01",
                    "bayesian_state": {"goal_rate": 0.2},
                    "trajectory": {
                        "trajectory_classification": "STABLE",
                        "role_minutes_evolution": {},
                        "matches": [
                            {
                                "gw": 1,
                                "opponent_team_id": 2,
                                "home": True,
                                "starter": True,
                                "minutes": 90,
                                "fpl_points": 6,
                                "goals": 1,
                                "assists": 0,
                                "xg": 0.4,
                                "npxg": 0.4,
                                "xa": 0.1,
                                "xgi": 0.5,
                                "shots": 3,
                                "shots_on_target": 2,
                                "box_touches": 5,
                                "key_passes": 1,
                                "chances_created": 1,
                                "big_chances": 1,
                                "team_formation": "4-3-3",
                                "opponent_formation": "4-4-2",
                            }
                        ],
                    },
                }
            ],
        },
    )
    report = _deep_report([_route()], extra_sections=[s16b])
    body = render_deep_text(report)
    assert "- GW1" in body
    assert "npxG 0.4" in body
    assert validate_deep_decision_content_delivery(report, body) == []


def test_l_canonical_mc_500k_must_reach_visible_probability_and_tails():
    report = _deep_report([_route()])
    body = render_deep_text(report)
    assert "MC PATHS: 500000" in body
    assert "P>HOLD" in body
    assert "Q10" in body and "Q90" in body
    assert validate_deep_decision_content_delivery(report, body) == []


def test_m_p1_7_lineup_and_captain_outputs_are_visibly_required():
    s06 = _section(
        "S06",
        "FORMATION / XI / BENCH",
        {
            "formation": "3-5-2",
            "starting_xi": [{"element": i, "name": f"P{i:02d}"} for i in range(1, 12)],
            "bench": {"gk": {"element": 12, "name": "P12"}, "order": [13, 14, 15]},
            "lineup_score": {"xpts_mean": 55.0},
        },
    )
    s08 = _section(
        "S08",
        "CAPTAIN / VICE CAPTAIN",
        {
            "captain": {"element_id": 1, "player": "P01"},
            "vice_captain": {"element_id": 2, "player": "P02"},
            "authority": "distributional evidence",
        },
    )
    report = _deep_report([_route()], extra_sections=[s06, s08])
    body = render_deep_text(report)
    assert "FORMATION:" in body and "XI:" in body and "BENCH:" in body
    assert "CAPTAIN AUTHORITY:" in body
    assert validate_deep_decision_content_delivery(report, body) == []


def test_n_stale_auth_expired_marker_cannot_override_valid_authenticated_evidence():
    valid_rows = [{"element_id": i} for i in range(1, 16)]
    stale_rows = [{"element_id": i} for i in range(21, 36)]
    resolved = select_personal_evidence(
        [
            {
                "source": "valid-auth",
                "source_class": "AUTHENTICATED_CURRENT_TEAM",
                "payload": {"players": valid_rows, "auth_state": "AUTH_AVAILABLE", "gw": 6},
                "observed_at": "2026-09-23T08:00:00+07:00",
                "gw": 6,
                "auth_state": "AUTH_AVAILABLE",
            },
            {
                "source": "newer-but-expired",
                "source_class": "AUTHENTICATED_CURRENT_TEAM",
                "payload": {"players": stale_rows, "auth_state": "AUTH_EXPIRED", "gw": 6},
                "observed_at": "2026-09-23T08:30:00+07:00",
                "gw": 6,
                "auth_state": "AUTH_EXPIRED",
            },
        ],
        planning_gw=6,
    )
    assert resolved["source"] == "valid-auth"
    assert [row["element_id"] for row in resolved["rows"]] == list(range(1, 16))
    assert resolved["finance_allowed"] is True


def test_o_contemplated_transfer_never_mutates_current15():
    current = [{"element_id": i} for i in range(1, 16)]
    contemplated = [{"element_id": i} for i in range(1, 15)] + [{"element_id": 99}]
    resolved = select_personal_evidence(
        [
            {
                "source": "current",
                "source_class": "AUTHENTICATED_CURRENT_TEAM",
                "payload": {"players": current, "auth_state": "AUTH_AVAILABLE", "gw": 6},
                "observed_at": "2026-09-23T08:00:00+07:00",
                "gw": 6,
                "auth_state": "AUTH_AVAILABLE",
            },
            {
                "source": "contemplated-route",
                "source_class": "CONTEMPLATED_TRANSFER",
                "payload": {"players": contemplated, "gw": 6},
                "observed_at": "2026-09-23T08:40:00+07:00",
                "gw": 6,
            },
        ],
        planning_gw=6,
    )
    ids = [row["element_id"] for row in resolved["rows"]]
    assert ids == list(range(1, 16))
    assert 99 not in ids


def test_p_current_gw_authenticated_squad_beats_previous_gw_submitted_picks():
    previous = [{"element_id": i} for i in range(1, 16)]
    current = [{"element_id": i} for i in range(31, 46)]
    resolved = select_personal_evidence(
        [
            {
                "source": "gw5-public",
                "source_class": "OFFICIAL_SUBMITTED_PICKS",
                "payload": {"picks": previous, "gw": 5},
                "observed_at": "2026-09-23T08:30:00+07:00",
                "gw": 5,
            },
            {
                "source": "gw6-auth",
                "source_class": "AUTHENTICATED_CURRENT_TEAM",
                "payload": {"players": current, "auth_state": "AUTH_AVAILABLE", "gw": 6},
                "observed_at": "2026-09-23T08:10:00+07:00",
                "gw": 6,
                "auth_state": "AUTH_AVAILABLE",
            },
        ],
        planning_gw=6,
    )
    assert resolved["source"] == "gw6-auth"
    assert [row["element_id"] for row in resolved["rows"]] == list(range(31, 46))


def test_q_report_plane_and_permanent_contract_do_not_pin_production_players():
    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "src/engines/v12_deep_delivery.py",
        root / "src/engines/v12_integrated_report_runner.py",
        root / "src/engines/v12_report_orchestration.py",
        root / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt",
        root / "README.md",
    )
    production_names = ("Haaland", "Calafiori", "Sangaré", "Groß")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "CURRENT15 = [" not in text
        assert "owned_element_ids = [" not in text
        for name in production_names:
            assert name not in text


def test_r_legacy_short_narrative_cannot_human_facing_pass():
    report = _deep_report([_route()])
    failures = validate_deep_decision_content_delivery(
        report,
        "WAIT. Hold for now.",
    )
    assert failures
    assert "FRONTIER_IDENTITIES_NOT_VISIBLE" in failures
    assert "MC_DISTRIBUTION_NOT_VISIBLE" in failures
