from __future__ import annotations

from datetime import datetime, timezone
import inspect
import json
from pathlib import Path

from src.engines.v12_deep_delivery import (
    select_personal_evidence,
    validate_deep_decision_content_delivery,
)
from src.engines.v12_final_delivery_barrier import validate_final_delivery_barrier
from src.engines.v12_integrated_report_runner import (
    _fingerprint,
    _lineup_content,
    _personal_evidence_resolution,
    _route_execution_economics_state,
    _three_gw_staging,
    run_deep,
)
from src.engines.v12_package_utility import (
    select_stage3_material_mc_routes,
)
from src.engines.v12_report_orchestration import (
    _price_source_freshness,
    build_calendar_workload_context,
    build_watchlist20,
    render_deep_text,
)


def test_stage_fingerprint_canonicalizes_aware_datetime():
    observed = datetime(2026, 9, 23, 4, 36, 9, tzinfo=timezone.utc)
    assert _fingerprint({"timestamp": observed}) == _fingerprint(
        {"timestamp": observed.isoformat()}
    )


def _section(section_id: str, label: str, content: dict, state: str = "COMPLETE"):
    payload = dict(content)
    if state == "COMPLETE" and section_id in {
        "S01", "S02", "S04", "S06", "S07", "S08", "S10", "S11",
        "S12", "S13", "S14", "S15", "S15B", "S16", "S16B", "S18", "S19"
    }:
        payload.setdefault("authoritative_binding", {
            "status": "BOUND",
            "producer": "SYNTHETIC_TEST_PRODUCER",
            "payload_fingerprint": "synthetic-test-fingerprint",
        })
    return {
        "section_id": section_id,
        "label": label,
        "state": state,
        "content": payload,
    }


def _action_board(action: str = "WAIT", best_alternative=None):
    axes = []
    for axis, now in (
        ("TRANSFER", action),
        ("XI", "LOCK"),
        ("CAPTAIN", "LOCK"),
        ("PRICE", "MONITOR"),
        ("AUTH/FINANCE", "AVAILABLE"),
        ("INJURY/TEAM NEWS", "CLEAR"),
    ):
        axes.append(
            {
                "axis": axis,
                "NOW": now,
                "NEXT": "refresh evidence",
                "TRIGGER TO ACT": "canonical threshold",
                "LATEST SAFE DECISION POINT": "next governed checkpoint",
                "COST OF WAITING": {"status": "AVAILABLE", "points": 0.2},
                "ABORT / REVERSAL": "material evidence reversal",
            }
        )
    alternative = best_alternative or {"route": "R1", "executable": True}
    return _section(
        "S18",
        "ACTION BOARD",
        {
            "action_board": {
                "axes": axes,
                "best_alternative": alternative,
                "best_alternative_executable": alternative.get("executable"),
            },
            "NOW": {row["axis"]: row["NOW"] for row in axes},
            "NEXT": {row["axis"]: row["NEXT"] for row in axes},
            "TRIGGER TO ACT": {row["axis"]: row["TRIGGER TO ACT"] for row in axes},
            "LATEST SAFE DECISION POINT": {
                row["axis"]: row["LATEST SAFE DECISION POINT"] for row in axes
            },
            "COST OF WAITING": {row["axis"]: row["COST OF WAITING"] for row in axes},
            "ABORT / REVERSAL": {row["axis"]: row["ABORT / REVERSAL"] for row in axes},
            "BEST ALTERNATIVE": alternative,
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
        "execution_economics_status": "AVAILABLE",
        "executable": True,
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
            "execution_economics_status": "AVAILABLE",
            "execution_economics_authority": {
                "bank": 2,
                "bank_status": "AVAILABLE",
                "sell_value_status": "AVAILABLE",
                "free_transfers": 1,
                "free_transfers_status": "AVAILABLE",
                "source": "SYNTHETIC_AUTH_CURRENT",
                "observed_at": "2026-09-25T10:00:00+00:00",
            },
            "package_routes": [
                {
                    "route": "HOLD",
                    "route_kind": "HOLD",
                    "moves": {"out": [], "in": []},
                    "bank_before": 2,
                    "affordability": "SUPPORTED",
                    "execution_economics_status": "NOT_APPLICABLE",
                    "executable": True,
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


def _rich_s02_rows():
    rows = []
    for i in range(1, 16):
        rows.append(
            {
                "element_id": i,
                "player": f"P{i:02d}",
                "position": "MID",
                "club": "Club",
                "current_price": 75,
                "selling_price": 74,
                "opponent": "Opponent",
                "home_away": "H",
                "availability": 0.98,
                "p_start": 0.90,
                "xmins": 80,
                "projection_1gw": 4.0,
                "projection_3gw": 12.0,
                "projection_5gw": 20.0,
                "tactical_role_label": "ROLE",
                "tactical_score": 0.7,
                "injury_rotation_warning": "NONE_MATERIAL",
                "price_relevance": "NONE_MATERIAL",
                "ownership_source": "OFFICIAL_FPL_PUBLIC_SELECTED_BY_PERCENT",
            }
        )
    return rows


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


def test_h0_real_schema_rank20_uses_native_order_without_internal_rank():
    rise_rows = [
        {
            "element_id": 100 + index,
            "projected_percent": 100.0 - index,
            "direction": "RISE",
            "estimate_source": "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
        }
        for index in range(20)
    ]
    fall_rows = [
        {
            "element_id": 200 + index,
            "projected_percent": -100.0 + index,
            "direction": "FALL",
            "estimate_source": "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
        }
        for index in range(20)
    ]
    rise = _section(
        "S12",
        "RISE20",
        {
            "rows": rise_rows,
            "artifact_adapter": "V6_DATA_PLAYERS_OFFSET0",
            "sort_contract": "projected_percent DESC, id ASC",
        },
    )
    fall = _section(
        "S13",
        "FALL20",
        {
            "rows": fall_rows,
            "artifact_adapter": "V6_DATA_PLAYERS_OFFSET0",
            "sort_contract": "projected_percent ASC, id ASC",
        },
    )
    assert all("rank" not in row for row in rise_rows + fall_rows)
    failures = validate_deep_decision_content_delivery(
        {"sections": [rise, fall]},
        "",
    )
    assert not [
        failure
        for failure in failures
        if failure.startswith("GOVERNED_RANK20_")
    ]


def test_h1_real_schema_rank20_rejects_order_drift():
    rows = [
        {
            "element_id": 100 + index,
            "projected_percent": 100.0 - index,
            "direction": "RISE",
            "estimate_source": "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
        }
        for index in range(20)
    ]
    rows[0], rows[1] = rows[1], rows[0]
    rise = _section(
        "S12",
        "RISE20",
        {
            "rows": rows,
            "artifact_adapter": "V6_DATA_PLAYERS_OFFSET0",
            "sort_contract": "projected_percent DESC, id ASC",
        },
    )
    failures = validate_deep_decision_content_delivery(
        {"sections": [rise]},
        "",
    )
    assert "GOVERNED_RANK20_ORDER_MISMATCH=S12:1" in failures


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
    s02 = _section(
        "S02",
        "OUR15",
        {
            "rows": _rich_s02_rows(),
            "current15_authority": {
                "source_class": "AUTH_CURRENT",
                "source": "synthetic",
                "observed_at": "2026-09-26T00:00:00+00:00",
                "applicable_gw": 6,
                "auth_state": "AUTH_AVAILABLE",
                "finance_availability": "AVAILABLE",
                "stale": False,
            },
        },
    )
    s06 = _section(
        "S06",
        "FORMATION / XI / BENCH",
        {
            "formation": "3-5-2",
            "starting_xi": [{"element": i, "name": f"P{i:02d}"} for i in range(1, 12)],
            "bench": {"gk": {"element": 12, "name": "P12"}, "order": [13, 14, 15]},
            "lineup_score": {"xpts_mean": 55.0},
            "xi_base_xpts": 55.0,
            "captain_adjusted_xpts": 55.0,
            "lineup_route_utility": 55.0,
            "score_semantics": {
                "authority": "P1_7_LINEUP",
                "relationship": "DISTINCT_BY_DESIGN",
                "raw_xpts_mutated": False,
            },
        },
    )
    scope = {
        "denominator": 6,
        "captain_count": 3,
        "captain_pct": 50.0,
        "effective_multiplier_sum": 8.0,
        "eo_pct": 133.3,
    }
    s08 = _section(
        "S08",
        "CAPTAIN / VICE CAPTAIN",
        {
            "decision_state": "LOCK",
            "captain": {"element_id": 1, "player": "P01"},
            "vice_captain": {"element_id": 2, "player": "P02"},
            "captain_frontier": [
                {
                    "element_id": 1,
                    "player": "P01",
                    "football_rank": 1,
                    "football_score": 90.0,
                    "expected_points": 7.0,
                    "league_scope": scope,
                    "rivals_scope": scope,
                    "direct_scope": scope,
                    "exposure_leverage_class": "BALANCED",
                },
                {
                    "element_id": 2,
                    "player": "P02",
                    "football_rank": 2,
                    "football_score": 86.0,
                    "expected_points": 6.5,
                    "league_scope": scope,
                    "rivals_scope": scope,
                    "direct_scope": scope,
                    "exposure_leverage_class": "PROTECTION",
                },
            ],
            "captain_safe_pool": [1],
            "candidate_universe_proof": {
                "captain_in_current15": True,
                "vice_in_current15": True,
                "captain_in_final_xi": True,
                "vice_in_final_xi": True,
                "captain_vice_distinct": True,
                "frontier_subset_of_final_xi": True,
            },
            "football_baseline_first": True,
            "mini_league_overlay_second": True,
            "reconciliation_reason": "football baseline retained",
            "authority": "P1.7 baseline + P1.8 exposure overlay",
        },
    )
    report = _deep_report([_route()], extra_sections=[s02, s06, s08])
    body = render_deep_text(report)
    assert "FORMATION:" in body and "XI:" in body and "BENCH:" in body
    assert "CAPTAIN AUTHORITY:" in body
    assert "OWNED FINAL-XI CAPTAIN FRONTIER" in body
    assert "EXPOSURE / LEVERAGE CLASS" in body
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


def test_p1_explicit_current15_state_outranks_stale_previous_gw_runtime(tmp_path: Path):
    confirmed = {
        "goalkeepers": [{"element_id": i} for i in range(1, 3)],
        "defenders": [{"element_id": i} for i in range(3, 8)],
        "midfielders": [{"element_id": i} for i in range(8, 13)],
        "forwards": [{"element_id": i} for i in range(13, 16)],
        "explicit_user_confirmation": True,
        "explicit_user_confirmed_at": "2026-09-26T09:00:00+00:00",
        "applicable_planning_gw": 6,
        "bank": None,
        "chips": None,
    }
    state = {"confirmed_current_squad_state": confirmed}
    planning_gw = int(confirmed["applicable_planning_gw"])

    confirmed_rows = []
    for group in ("goalkeepers", "defenders", "midfielders", "forwards"):
        confirmed_rows.extend(dict(row) for row in confirmed.get(group) or [])
    confirmed_ids = [int(row["element_id"]) for row in confirmed_rows]

    assert confirmed["explicit_user_confirmation"] is True
    assert confirmed["explicit_user_confirmed_at"]
    assert len(confirmed_ids) == 15
    assert len(set(confirmed_ids)) == 15

    personal = tmp_path / "data/v6/personal"
    personal.mkdir(parents=True)
    stale_ids = list(range(9001, 9016))
    (personal / "current_team.json").write_text(
        json.dumps(
            {
                "players": [{"element_id": value} for value in stale_ids],
                "generated_at": "2026-09-24T09:00:00+00:00",
                "gw": planning_gw - 1,
                "auth_state": "AUTH_EXPIRED",
            }
        ),
        encoding="utf-8",
    )
    (personal / "submitted_picks.json").write_text(
        json.dumps(
            {
                "picks": [{"element_id": value} for value in stale_ids],
                "generated_at": "2026-09-24T09:01:00+00:00",
                "gw": planning_gw - 1,
                "status": "AVAILABLE",
            }
        ),
        encoding="utf-8",
    )

    resolved = _personal_evidence_resolution(
        tmp_path,
        state,
        planning_gw=planning_gw,
    )

    assert resolved["resolution_status"] == "CURRENT_VALID"
    assert resolved["stale"] is False
    assert resolved["source_class"] == "USER_CONFIRMED"
    assert resolved["source"] == "FPL_MASTER_STATE_V12:EXPLICIT_USER_CONFIRMED"
    assert resolved["user_current"] is True
    assert [int(row["element_id"]) for row in resolved["rows"]] == confirmed_ids
    assert resolved["payload"].get("bank") is None
    assert resolved["payload"].get("chips") is None
    assert all(
        row.get("purchase_price") is None and row.get("selling_price") is None
        for row in resolved["rows"]
    )

def test_q_report_plane_and_new_permanent_contract_do_not_pin_production_players():
    root = Path(__file__).resolve().parents[1]
    source_paths = (
        root / "src/engines/v12_deep_delivery.py",
        root / "src/engines/v12_integrated_report_runner.py",
        root / "src/engines/v12_report_orchestration.py",
    )
    production_names = ("Haaland", "Calafiori", "Sangaré", "Groß")
    for path in source_paths:
        text = path.read_text(encoding="utf-8")
        assert "CURRENT15 = [" not in text
        assert "owned_element_ids = [" not in text
        for name in production_names:
            assert name not in text

    canonical = (
        root / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
    ).read_text(encoding="utf-8")
    canonical_block = canonical.split(
        "DEEP DECISION-CONTENT DELIVERY BARRIER:", 1
    )[1].split("HUMAN_FACING acceptance is fail-closed:", 1)[0]
    readme = (root / "README.md").read_text(encoding="utf-8")
    readme_block = readme.split(
        "## DEEP decision-content delivery barrier", 1
    )[1].split("## PRICE human-facing delivery barrier", 1)[0]
    for block in (canonical_block, readme_block):
        assert "CURRENT15 = [" not in block
        for name in production_names:
            assert name not in block


def test_r_legacy_short_narrative_cannot_human_facing_pass():
    report = _deep_report([_route()])
    failures = validate_deep_decision_content_delivery(
        report,
        "WAIT. Hold for now.",
    )
    assert failures
    assert "FRONTIER_IDENTITIES_NOT_VISIBLE" in failures
    assert "MC_DISTRIBUTION_NOT_VISIBLE" in failures

def test_integrated_deep_does_not_bruteforce_global_two_transfer_p17():
    source = inspect.getsource(run_deep)
    assert "max_transfers=1" in source
    assert "compose_material_two_transfer_packages" in source
    assert "P1_2A_FUNDED_PACKAGE_SEARCH" in source
    assert "P1_2B_FUNDED_PACKAGE_UTILITY" in source
    assert "FULL_DIRECT_MATERIAL_FUNDED" in source
    assert "max_transfers=2" not in source

def _stage_a_fixture(name: str) -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")
    )


def test_stage_a_required_ci_real_36126675342_fails_known_false_pass_classes():
    payload = _stage_a_fixture("v12_semantic_regression_36126675342.json")
    failures = set(
        validate_deep_decision_content_delivery(payload["report"], "")
    )
    expected = {
        "S17_AUTH_AUTHORITY_MISSING",
        "S17_PRIVATE_AUTH_STATE_MISSING",
        "S14B_FT_AUTHORITY_MISSING",
        "S14B_FT_STATUS_MISSING",
        "S14B_FT_CLAIM_WITHOUT_AUTHORITY",
        "S14_EXECUTION_ECONOMICS_AUTHORITY_MISSING",
        "S14_EXECUTION_ECONOMICS_STATUS_MISSING",
        "S14_ROUTE_EXECUTION_STATE_MISSING=1:426->52",
        "S06_SCORE_SEMANTICS_AUTHORITY_MISSING",
        "S06_SCORE_VALUES_MISSING",
        "S10_PRICE_FRESHNESS_AUTHORITY_MISSING=1",
        "S12_PRICE_FRESHNESS_AUTHORITY_MISSING=1",
        "S13_PRICE_FRESHNESS_AUTHORITY_MISSING=1",
    }
    assert expected.issubset(failures)
    assert payload["bound_authority"]["v6_private_auth_state"] == "AUTH_EXPIRED"
    s17 = next(
        row for row in payload["report"]["sections"]
        if row["section_id"] == "S17"
    )
    assert s17["content"]["source_health"]["authenticated_personal_scope"] == "HEALTHY"
    assert not any("TERMINAL_DATE_STATE_MISSING" in row for row in failures)


def test_stage_f_final_barrier_rejects_real_36126675342_false_pass():
    payload = _stage_a_fixture("v12_semantic_regression_36126675342.json")
    result = validate_final_delivery_barrier(
        report_mode="DEEP",
        report=payload["report"],
        body="",
    )
    assert result["status"] == "FAIL"
    assert result["can_emit"] is False
    assert "S17_AUTH_AUTHORITY_MISSING" in result["failures"]
    assert (
        result["governance"]["human_facing_pass_requires_final_barrier_pass"]
        is True
    )


def test_stage_a_required_ci_comparison_36108029034_is_not_semantic_pass():
    payload = _stage_a_fixture("v12_semantic_comparison_36108029034.json")
    failures = set(
        validate_deep_decision_content_delivery(payload["report"], "")
    )
    assert payload["bound_authority"]["v6_private_auth_state"] == "AUTH_EXPIRED"
    assert "S17_AUTH_AUTHORITY_MISSING" in failures
    assert "S17_PRIVATE_AUTH_STATE_MISSING" in failures
    assert "S14B_FT_CLAIM_WITHOUT_AUTHORITY" in failures
    assert "S14_EXECUTION_ECONOMICS_STATUS_MISSING" in failures
    assert "S06_SCORE_SEMANTICS_AUTHORITY_MISSING" in failures
    assert "S10_PRICE_FRESHNESS_AUTHORITY_MISSING=1" in failures
    assert not any("TERMINAL_DATE_STATE_MISSING" in row for row in failures)


def test_stage_a_required_ci_price_freshness_is_human_visible():
    s10 = _section(
        "S10",
        "ACTIONABLE PRICE RADAR",
        {
            "rows": [
                {
                    "element_id": 572,
                    "name": "P572",
                    "current_price": 4.7,
                    "authenticated_sell_value": "UNAVAILABLE",
                    "predictor_direction": "RISE",
                    "predictor_progress": "0.0",
                    "predictor_projected_percent": 0.1,
                    "next_official_price_cycle_wib": "2026-09-26T06:00:00+07:00",
                    "cycles_to_expected_change": "UNAVAILABLE",
                    "date_state": "NO_CROSSING_WITHIN_GOVERNED_HORIZON",
                    "eta_context": "Belum terdeteksi berubah sampai governed horizon",
                    "evidence_timestamp": "2026-09-25T02:37:34.626747+00:00",
                    "source_age_minutes": 495.4,
                    "freshness": "STALE",
                    "decision_implication": "MONITOR",
                }
            ]
        },
    )
    report = _deep_report([_route()], extra_sections=[s10])
    body = render_deep_text(report)
    assert "source_age_minutes" in body
    assert "freshness" in body
    assert "STALE" in body
    failures = validate_deep_decision_content_delivery(report, body)
    assert not [failure for failure in failures if failure.startswith("S10_PRICE_")]


def test_stage_a_required_ci_producer_repairs_are_fail_closed_without_new_math():
    regression = _stage_a_fixture("v12_semantic_regression_36126675342.json")
    old_s06 = next(
        row for row in regression["report"]["sections"]
        if row["section_id"] == "S06"
    )["content"]
    lineup = {
        "formation": old_s06["formation_comparison"][0]["formation"],
        "starting_xi": [],
        "bench": {"gk": None, "order": []},
        "captain": None,
        "vice_captain": None,
        "lineup_score": old_s06["lineup_score"],
        "formation_comparison": old_s06["formation_comparison"],
    }
    score = _lineup_content(lineup)
    assert score["xi_base_xpts"] == 49.777897
    assert score["captain_adjusted_xpts"] == 55.012527
    assert score["score_semantics"]["authority"] == "P1_7_LINEUP"
    assert score["score_semantics"]["relationship"] == "DISTINCT_BY_DESIGN"
    assert score["score_semantics"]["raw_xpts_mutated"] is False

    finance = {
        "bank": None,
        "bank_status": "UNAVAILABLE",
        "sell_value_status": "UNAVAILABLE",
        "free_transfers": None,
        "free_transfers_status": "NOT_SUPPORTED",
        "personal_evidence_source": "fixture:36126675342",
        "personal_evidence_observed_at": regression["_fixture_provenance"]["report_slot"],
    }
    route_state = _route_execution_economics_state(
        route_id="1:426->52",
        route_economics_status="PARTIAL",
        finance=finance,
    )
    assert route_state == {"status": "DEGRADED", "executable": False}

    s14 = next(
        row for row in regression["report"]["sections"]
        if row["section_id"] == "S14"
    )["content"]
    staging = _three_gw_staging(
        planning_gw=6,
        action="WAIT",
        stage3_decision={"selected_route_id": "HOLD", "reason": "fixture-regression"},
        stage3_visible={"package_routes": s14["package_routes"]},
        all15_rows=[],
        lineup=None,
        finance=finance,
    )
    assert staging["ft_authority"]["known"] is False
    assert staging["ft_saving_plan"] == "FT STATE UNAVAILABLE"
    assert "SAVE FT" not in str(staging).upper()
    assert "ROLL FT" not in str(staging).upper()

    s10 = next(
        row for row in regression["report"]["sections"]
        if row["section_id"] == "S10"
    )["content"]
    freshness = _price_source_freshness(
        s10["rows"][0]["evidence_timestamp"],
        regression["_fixture_provenance"]["report_slot"],
        "GREEN",
    )
    assert freshness["freshness"] == "STALE"
    assert 495.0 < freshness["source_age_minutes"] < 497.0

def _stage_b_position_evidence(position: str) -> dict:
    if position == "GK":
        return {
            "save_process": {"P_points_awarded": 0.8},
            "shot_stopping": {"rate": 0.7},
            "clean_sheet_environment": {"probability": 0.35},
            "goals_conceded_environment": {"mean": 1.2},
            "penalty_save_evidence": {"probability": 0.05},
            "hierarchy_security": {"p_start": 0.9, "xmins": 90},
        }
    if position == "DEF":
        return {
            "goal_process": {"rate": 0.08},
            "creation_process": {"rate": 0.12},
            "clean_sheet_environment": {"probability": 0.35},
            "defcon": {"expected_points": 0.7},
            "defensive_role": "FULLBACK",
            "matchup": {"wide_channel": "FAVOURABLE"},
        }
    if position == "MID":
        return {
            "goal_process": {"rate": 0.35},
            "creation_process": {"rate": 0.28},
            "penalty_process": {"role": "SECONDARY"},
            "set_piece_process": {"role": "CORNERS"},
            "advanced_role": "10",
            "matchup": {"central_space": "FAVOURABLE"},
        }
    return {
        "goal_process": {"rate": 0.5},
        "creation_process": {"rate": 0.16},
        "penalty_process": {"role": "PRIMARY"},
        "set_piece_process": {"role": "NONE"},
        "service_linkup": {"creator_dependency": "SUPPORTED"},
        "matchup": {"box_access": "FAVOURABLE"},
    }


def _stage_b_watch_universe(*, low_security_element: int | None = None) -> list[dict]:
    rows = []
    element = 100
    for position in ("GK", "DEF", "MID", "FWD"):
        for rank in range(1, 7):
            element += 1
            low = element == low_security_element
            rows.append(
                {
                    "element_id": element,
                    "name": f"{position}{rank}",
                    "position": position,
                    "eligible": True,
                    "canonical_evaluation_complete": True,
                    "canonical_rank": rank,
                    "football_score": 80.0 - rank,
                    "stage2_lineage": {"lineage_complete": True},
                    "p_available": 0.95,
                    "p_start": 0.55 if low else 0.90,
                    "p_dnp": 0.35 if low else 0.05,
                    "xmins": 52 if low else 82,
                    "position_specific_evidence": _stage_b_position_evidence(position),
                }
            )
    return rows


def test_stage_b_legacy_5_5_5_5_without_positional_contract_is_now_false_pass():
    positions = ["GK"] * 5 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 5
    report = {
        "sections": [
            {
                "section_id": "S02",
                "state": "COMPLETE",
                "content": {"rows": [{"element_id": i} for i in range(1, 16)]},
            },
            {
                "section_id": "S11",
                "state": "COMPLETE",
                "content": {
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "WATCHLIST20",
                        "payload_fingerprint": "legacy-fixture",
                    },
                    "rows": [
                        {"element_id": 100 + i, "position": position}
                        for i, position in enumerate(positions, start=1)
                    ],
                },
            },
        ]
    }
    body = render_deep_text(report)
    failures = validate_deep_decision_content_delivery(report, body)
    assert "WATCHLIST_POSITION_FORMULA_MISSING=1:GK" in failures
    assert "WATCHLIST_ADMISSION_GATE_MISSING=1" in failures
    assert "ACTIONABLE_WATCHLIST_PADDING_CONTRACT_MISSING" in failures
    assert "WATCHLIST_PRICE_PRIMARY_AUTHORITY" in failures


def test_stage_b_scanner20_is_exact_positional_and_actionable_is_unpadded_subset():
    universe = _stage_b_watch_universe(low_security_element=101)
    result = build_watchlist20(
        evaluated_universe=universe,
        owned_element_ids=[],
        universe_authority="FULL",
    )
    assert result["state"] == "COMPLETE"
    assert result["position_counts"] == {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}
    assert len(result["scanner20"]) == 20
    assert len({row["element_id"] for row in result["scanner20"]}) == 20
    assert result["actionable_watchlist_is_unpadded_subset"] is True
    assert result["watchlist_never_emits_act"] is True
    assert result["price_is_overlay_not_primary_authority"] is True
    assert all(row["action"] == "WATCH" for row in result["actionable_watchlist"])
    gk = next(row for row in result["scanner20"] if row["position"] == "GK")
    assert gk["position_specific_evidence"]["formula_id"] == "V12_WATCH_GK_EVIDENCE_V1"
    assert gk["position_specific_evidence"]["attacker_xgi_gate_required"] is False
    # Element 101 is still valid broad-monitoring Scanner20, but fails the
    # P1.1-derived security gate and must not be padded back into actionable.
    assert 101 in {row["element_id"] for row in result["scanner20"]}
    assert 101 not in {row["element_id"] for row in result["actionable_watchlist"]}


def test_stage_b_watchlist_excludes_owned_and_formula_drift_is_detected():
    universe = _stage_b_watch_universe()
    owned = [101, 107, 113, 119]
    result = build_watchlist20(
        evaluated_universe=universe,
        owned_element_ids=owned,
        universe_authority="FULL",
    )
    assert not (set(owned) & {row["element_id"] for row in result["scanner20"]})
    result["scanner20"][0]["position_specific_evidence"]["formula_id"] = "DRIFTED"
    result["rows"] = result["scanner20"]
    report = {
        "sections": [
            {
                "section_id": "S02",
                "state": "COMPLETE",
                "content": {"rows": [{"element_id": i} for i in range(1, 16)]},
            },
            {
                "section_id": "S11",
                "state": "COMPLETE",
                "content": {
                    **result,
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "WATCHLIST20",
                        "payload_fingerprint": "stage-b-drift",
                    },
                },
            },
        ]
    }
    failures = validate_deep_decision_content_delivery(report, render_deep_text(report))
    assert any(item.startswith("WATCHLIST_POSITION_FORMULA_MISSING=1:") for item in failures)


def test_stage_b_calendar_is_data_driven_and_never_applies_static_fatigue_penalty():
    fixtures = [
        {
            "id": 90,
            "event": 5,
            "team_h": 2,
            "team_a": 1,
            "kickoff_time": "2026-09-23T19:00:00+00:00",
        },
        {
            "id": 101,
            "event": 6,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-09-27T14:00:00+00:00",
        },
        {
            "id": 102,
            "event": 6,
            "team_h": 3,
            "team_a": 1,
            "kickoff_time": "2026-09-30T18:00:00+00:00",
        },
    ]
    schedule = [
        {
            "team_id": 1,
            "player_id": 201,
            "kickoff": "2026-09-25T18:00:00+00:00",
            "competition": "Verified International Fixture",
            "competition_category": "INTERNATIONAL",
            "minutes": 90,
            "started": True,
            "cross_border": True,
            "long_haul": True,
            "timezone_shift_hours": 5,
            "confirmed_call_up": True,
            "return_to_club_interval_hours": 30,
        }
    ]
    players = [
        {
            "element_id": 201,
            "name": "P201",
            "team_id": 1,
            "planning_fixture_evidence": [
                {
                    "fixture_id": 101,
                    "xpts": 5.2,
                    "xmins": 82,
                    "p_start": 0.91,
                    "matchup": "A",
                },
                {
                    "fixture_id": 102,
                    "xpts": 4.7,
                    "xmins": 76,
                    "p_start": 0.84,
                    "matchup": "B",
                },
            ],
        },
        {"element_id": 204, "name": "P204", "team_id": 4},
    ]
    context = build_calendar_workload_context(
        planning_gw=6,
        pl_fixtures=fixtures,
        team_ids=[1, 2, 3, 4],
        relevant_players=players,
        verified_schedule_events=schedule,
        non_pl_schedule_authority=True,
        report_timestamp="2026-09-26T00:00:00+00:00",
        weather_rows=[
            {
                "fixture_id": 101,
                "venue": "Ground A",
                "kickoff": "2026-09-27T14:00:00+00:00",
                "condition": "Dry",
                "temperature_c": 18,
                "precipitation_probability": 10,
                "wind_kph": 12,
                "fpl_impact": "NORMAL",
                "evidence_timestamp": "2026-09-26T00:00:00+00:00",
            }
        ],
        weather_forecast_horizon_hours=72,
    )
    assert context["state"] == "COMPLETE"
    assert context["gw_topology"] == "MIXED_DGW_BGW"
    assert context["period_flags"]["double_gw_teams"] == [1]
    assert 4 in context["period_flags"]["blank_gw_teams"]
    assert context["static_fatigue_penalty_applied"] is False
    assert context["weather_mutates_football_model"] is False
    assert context["dgw_cross_fixture_covariance_claimed"] is False
    p201 = next(row for row in context["player_workload"] if row["element_id"] == 201)
    assert p201["load_state"] == "LONG-HAUL RETURN"
    assert p201["gw_state"] == "DOUBLE"
    assert [row["xpts"] for row in p201["planning_gw_fixtures"]] == [5.2, 4.7]
    p204 = next(row for row in context["player_workload"] if row["element_id"] == 204)
    assert p204["gw_state"] == "BLANK"
    assert context["competition_coverage"]["competition_names_data_driven"] == [
        "Premier League",
        "Verified International Fixture",
    ]
    weather = {row["fixture_id"]: row for row in context["weather"]}
    assert weather[101]["fpl_impact"] == "NORMAL"
    assert weather[102]["state"] == "WEATHER UNAVAILABLE — OUTSIDE RELIABLE FORECAST HORIZON"

def _stage_c_scope_rows(denominator: int) -> list[dict]:
    return [
        {
            "element_id": element,
            "player": f"P{element}",
            "denominator": denominator,
            "ownership_count": min(denominator, 1),
            "ownership_pct": (100.0 / denominator if denominator else None),
            "starter_count": min(denominator, 1),
            "starter_pct": (100.0 / denominator if denominator else None),
            "bench_count": 0,
            "bench_pct": (0.0 if denominator else None),
            "captain_count": 0,
            "captain_pct": (0.0 if denominator else None),
            "vice_count": 0,
            "vice_pct": (0.0 if denominator else None),
            "effective_multiplier_sum": (1.0 if denominator else None),
            "eo_pct": (100.0 / denominator if denominator else None),
            "eo_supported": denominator > 0,
        }
        for element in range(1, 16)
    ]


def test_stage_c_legacy_captain_outside_final_xi_is_semantic_false_pass():
    report = {
        "sections": [
            {
                "section_id": "S02",
                "state": "COMPLETE",
                "content": {"rows": [{"element_id": i} for i in range(1, 16)]},
            },
            {
                "section_id": "S06",
                "state": "COMPLETE",
                "content": {
                    "starting_xi": [{"element": i} for i in range(1, 12)],
                    "formation": "3-5-2",
                    "bench": {"gk": {"element": 12}, "order": [13, 14, 15]},
                    "xi_base_xpts": 50.0,
                    "captain_adjusted_xpts": 55.0,
                    "score_semantics": {
                        "authority": "P1_7_LINEUP",
                        "relationship": "DISTINCT_BY_DESIGN",
                    },
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "P1_7_LINEUP",
                        "payload_fingerprint": "stage-c-s06",
                    },
                },
            },
            {
                "section_id": "S08",
                "state": "COMPLETE",
                "content": {
                    "captain": {"element_id": 12, "player": "P12"},
                    "vice_captain": {"element_id": 2, "player": "P2"},
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "P1_7_LINEUP",
                        "payload_fingerprint": "legacy-s08",
                    },
                },
            },
        ]
    }
    failures = validate_deep_decision_content_delivery(report, render_deep_text(report))
    assert "S08_CAPTAIN_NOT_IN_FINAL_XI" in failures
    assert "S08_CAPTAIN_DECISION_STATE_INVALID" in failures
    assert "S08_CAPTAIN_FRONTIER_MISSING" in failures


def test_stage_c_legacy_single_rival_denominator_cannot_masquerade_as_all_scopes():
    report = {
        "sections": [
            {
                "section_id": "S15B",
                "state": "COMPLETE",
                "content": {
                    "coverage_state": "FULL",
                    "expected_manager_count": 58,
                    "submitted_picks_available_count": 58,
                    "rival_exposure_denominator": 57,
                    "our15_rival_exposure": _stage_c_scope_rows(57),
                    "strategy_implication": {"human_posture": "BALANCED"},
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "P1_8",
                        "payload_fingerprint": "legacy-one-denominator",
                    },
                },
            }
        ]
    }
    failures = validate_deep_decision_content_delivery(report, render_deep_text(report))
    assert "S15B_LEAGUE_SCOPE_MUST_INCLUDE_US" in failures
    assert "S15B_RIVALS_SCOPE_MUST_EXCLUDE_US" in failures
    assert "S15B_DIRECT_SCOPE_MUST_EXCLUDE_US" in failures
    assert "S15B_BEHAVIOURAL_BASELINE_LABEL_MISSING" in failures


def test_stage_c_direct_scope_cannot_masquerade_as_league_denominator():
    scopes = {
        "LEAGUE": {
            "label": "LEAGUE58_INCL_US",
            "expected": 58,
            "collected": 58,
            "denominator": 58,
            "includes_us": True,
        },
        "RIVALS": {
            "label": "RIVALS57_EXCL_US",
            "expected": 57,
            "collected": 57,
            "denominator": 57,
            "includes_us": False,
        },
        "DIRECT": {
            # Deliberately false-pass shaped: DIRECT carries league-sized
            # label/denominator even though the requested cohort is six.
            "label": "LEAGUE58_INCL_US",
            "expected": 58,
            "collected": 58,
            "denominator": 58,
            "includes_us": False,
        },
    }
    report = {
        "sections": [
            {
                "section_id": "S15B",
                "state": "COMPLETE",
                "content": {
                    "coverage_state": "FULL",
                    "expected_manager_count": 58,
                    "submitted_picks_available_count": 58,
                    "disclosed_picks_label": "BEHAVIOURAL BASELINE",
                    "denominator_scopes": scopes,
                    "league_our15_exposure": _stage_c_scope_rows(58),
                    "rivals_our15_exposure": _stage_c_scope_rows(57),
                    "direct_rival_our15_exposure": _stage_c_scope_rows(58),
                    "direct_rival_scope": {
                        "requested_above_count": 6,
                        "standings_rival_count": 6,
                        "picks_available_count": 6,
                        "denominator": 58,
                    },
                    "direct_rivals": [],
                    "strategy_implication": {"human_posture": "BALANCED"},
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "P1_8",
                        "payload_fingerprint": "direct-mislabeled-as-league",
                    },
                },
            }
        ]
    }
    failures = validate_deep_decision_content_delivery(
        report,
        render_deep_text(report),
    )
    assert "S15B_DIRECT_SCOPE_LABEL_INVALID" in failures
    assert "S15B_DIRECT_SCOPE_COHORT_RELATION_INVALID" in failures


def test_stage_c_categorical_expected_rank_utility_name_is_forbidden():
    scopes = {
        "LEAGUE": {
            "label": "LEAGUE3_INCL_US",
            "expected": 3,
            "collected": 3,
            "denominator": 3,
            "includes_us": True,
        },
        "RIVALS": {
            "label": "RIVALS2_EXCL_US",
            "expected": 2,
            "collected": 2,
            "denominator": 2,
            "includes_us": False,
        },
        "DIRECT": {
            "label": "DIRECT6_ABOVE_US",
            "expected": 2,
            "collected": 2,
            "denominator": 2,
            "includes_us": False,
        },
    }
    report = {
        "sections": [
            {
                "section_id": "S15B",
                "state": "COMPLETE",
                "content": {
                    "coverage_state": "FULL",
                    "expected_manager_count": 3,
                    "submitted_picks_available_count": 3,
                    "disclosed_picks_label": "BEHAVIOURAL BASELINE",
                    "denominator_scopes": scopes,
                    "league_our15_exposure": _stage_c_scope_rows(3),
                    "rivals_our15_exposure": _stage_c_scope_rows(2),
                    "direct_rival_our15_exposure": _stage_c_scope_rows(2),
                    "direct_rival_scope": {"denominator": 2},
                    "captain_leverage": [
                        {
                            "element_id": 1,
                            "expected_rank_utility": "HIGH_LEVERAGE",
                        }
                    ],
                    "strategy_implication": {"human_posture": "BALANCED"},
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "P1_8",
                        "payload_fingerprint": "categorical-rank-utility",
                    },
                },
            }
        ]
    }
    failures = validate_deep_decision_content_delivery(report, render_deep_text(report))
    assert "S15B_CATEGORICAL_RANK_UTILITY_FORBIDDEN" in failures


def test_stage_c_legacy_s19_copy_without_s08_s15b_dependency_fails_closed():
    report = {
        "sections": [
            {
                "section_id": "S02",
                "state": "COMPLETE",
                "content": {"rows": [{"element_id": i} for i in range(1, 16)]},
            },
            {
                "section_id": "S06",
                "state": "COMPLETE",
                "content": {
                    "starting_xi": [{"element": i} for i in range(1, 12)],
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "P1_7_LINEUP",
                        "payload_fingerprint": "s06",
                    },
                },
            },
            {
                "section_id": "S08",
                "state": "DEGRADED",
                "content": {},
            },
            {
                "section_id": "S15B",
                "state": "DEGRADED",
                "content": {},
            },
            {
                "section_id": "S19",
                "state": "COMPLETE",
                "content": {
                    "final_judgement": {
                        "final_captain": {"element_id": 1, "player": "P1"},
                        "vice": {"element_id": 2, "player": "P2"},
                        "captain_state": "LOCK",
                    },
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "P1_7_LINEUP",
                        "payload_fingerprint": "legacy-s19",
                    },
                },
            },
        ]
    }
    failures = validate_deep_decision_content_delivery(report, render_deep_text(report))
    assert "S19_DID_NOT_CONSUME_S08_S15B" in failures
    assert "S19_CAPTAIN_STATE_CONTRADICTS_S08" in failures

def test_stage_d_legacy_single_wait_s01_cannot_satisfy_multi_axis_dashboard():
    report = {
        "sections": [
            _section(
                "S01",
                "DECISION / CURRENT STATUS",
                {
                    "operational_state": "WAIT",
                    "planning_gw": 6,
                    "primary_decision": "HOLD",
                    "key_decision_driver": "legacy",
                },
            )
        ]
    }
    body = render_deep_text(report)
    failures = validate_deep_decision_content_delivery(report, body)
    assert "MULTI-AXIS DECISION DASHBOARD" in body
    assert "S01_AXIS_INVALID=TRANSFER" in failures
    assert "S01_MULTI_AXIS_PAYLOAD_MISSING" in failures


def test_stage_d_legacy_compact_s02_missing_human_decision_fields_fails_closed():
    report = {
        "sections": [
            _section(
                "S02",
                "OUR15",
                {
                    "rows": [
                        {
                            "element_id": i,
                            "player": f"P{i:02d}",
                            "p_start": 0.9,
                            "xmins": 80,
                        }
                        for i in range(1, 16)
                    ],
                    "current15_authority": {
                        "source_class": "AUTH_CURRENT",
                        "observed_at": "2026-09-26T00:00:00+00:00",
                        "applicable_gw": 6,
                        "auth_state": "AUTH_AVAILABLE",
                        "finance_availability": "AVAILABLE",
                    },
                },
            )
        ]
    }
    body = render_deep_text(report)
    failures = validate_deep_decision_content_delivery(report, body)
    assert any(item.startswith("S02_HUMAN_FIELD_MISSING=1:") for item in failures)


def test_stage_d_s03_complete_without_previous_visible_deep_is_false_pass():
    report = {
        "sections": [
            _section(
                "S03",
                "DECISION DELTA",
                {
                    "decision_delta": {
                        "baseline_state": "UNAVAILABLE",
                        "rows": [],
                        "material_only": True,
                    }
                },
            )
        ]
    }
    body = render_deep_text(report)
    failures = validate_deep_decision_content_delivery(report, body)
    assert "S03_COMPLETE_WITHOUT_PREVIOUS_VISIBLE_DEEP" in failures


def test_stage_d_s03_degraded_baseline_does_not_invent_numeric_delta():
    report = {
        "sections": [
            _section(
                "S03",
                "DECISION DELTA",
                {
                    "decision_delta": {
                        "baseline_state": "UNAVAILABLE",
                        "rows": [],
                        "summary": "baseline unavailable",
                        "no_recomputation_no_numeric_delta": True,
                    }
                },
                state="DEGRADED",
            )
        ]
    }
    body = render_deep_text(report)
    failures = validate_deep_decision_content_delivery(report, body)
    assert "BASELINE UNAVAILABLE" in body
    assert "S03_NUMERIC_DELTA_GUARD_MISSING" not in failures
    assert "S03_DEGRADED_BASELINE_STATE_INVALID" not in failures


def test_stage_d_s18_requires_all_decision_axes():
    report = {
        "sections": [
            _section(
                "S18",
                "ACTION BOARD",
                {
                    "action_board": {
                        "axes": [
                            {
                                "axis": "TRANSFER",
                                "NOW": "WAIT",
                                "NEXT": "refresh",
                                "TRIGGER TO ACT": "gate",
                                "LATEST SAFE DECISION POINT": "deadline",
                                "COST OF WAITING": "none",
                                "ABORT / REVERSAL": "change",
                            }
                        ],
                        "best_alternative": None,
                        "best_alternative_executable": None,
                    },
                    "NOW": {"TRANSFER": "WAIT"},
                    "NEXT": {"TRANSFER": "refresh"},
                    "TRIGGER TO ACT": {"TRANSFER": "gate"},
                    "LATEST SAFE DECISION POINT": {"TRANSFER": "deadline"},
                    "COST OF WAITING": {"TRANSFER": "none"},
                    "ABORT / REVERSAL": {"TRANSFER": "change"},
                    "BEST ALTERNATIVE": None,
                },
            )
        ]
    }
    body = render_deep_text(report)
    failures = validate_deep_decision_content_delivery(report, body)
    assert "S18_MULTI_AXIS_INCOMPLETE" in failures


def test_stage_d_s16_renderer_uses_compact_semantics_not_raw_posterior_dict():
    row = {
        "element_id": 1,
        "player": "P01",
        "availability": 0.98,
        "p_start": 0.94,
        "xmins": 84,
        "probabilities": {
            "p_goal": 0.3,
            "p_assist": 0.2,
            "p_return": 0.45,
            "p_haul": 0.22,
            "p_blank": 0.37,
        },
        "projection_1gw": 6.1,
        "projection_3gw": 18.0,
        "projection_5gw": 29.0,
        "underlying": {
            "xg90": 0.4,
            "npxg90": 0.35,
            "xa90": 0.2,
            "xgi90": 0.6,
            "shots": 3,
            "shots_in_box": 2,
            "shots_on_target": 1,
            "big_chances": 1,
            "box_touches": 7,
            "key_passes": 2,
            "chances_created": 2,
        },
        "posterior_signal": {"posterior_rates": {"goal": 0.31}},
        "bayesian_state": {"status": "POSTERIOR_AVAILABLE", "confidence": "MEDIUM"},
        "role_detail": {"tactical_role": "9", "penalty": "TAKER", "set_piece": "NONE"},
        "fixture_detail": {"opponent": "OPP", "home": True},
        "defensive_contribution": "UNAVAILABLE",
        "workload_context": {"load_state": "NORMAL LOAD", "days_rest": 6},
        "price_optionality": {"current_price": 90},
        "mini_league_relevance": {"direct": {"eo_pct": 50.0}},
        "main_upside": 12,
        "main_risk": {"Q10": 2, "warning": "NONE_MATERIAL"},
    }
    report = {
        "sections": [
            _section(
                "S16",
                "ALL15 TACTICAL / PROBABILITY REVIEW",
                {
                    "rows": [row, *[{**row, "element_id": i, "player": f"P{i:02d}"} for i in range(2, 16)]],
                    "position_mechanisms": [{"element_id": i} for i in range(1, 16)],
                },
            )
        ]
    }
    body = render_deep_text(report)
    failures = validate_deep_decision_content_delivery(report, body)
    assert "posterior_rates" not in body
    assert "Pgoal" in body and "xGI90" in body and "ML relevance" in body
    assert "S16_RAW_POSTERIOR_DICT_VISIBLE" not in failures



def test_stage_b_bgw_requires_cross_section_decision_propagation():
    current15 = [{"element_id": i} for i in range(1, 16)]
    bgw = {
        "source_section": "S05",
        "planning_gw": 6,
        "gw_topology": "BLANK_GW",
        "active": True,
        "blank_team_ids": [4],
        "blank_owned_element_ids": [1],
        "blank_owned_in_final_xi": [],
        "decision_math_mutated": False,
        "context_only": True,
    }
    s05 = {
        "planning_gw": 6,
        "gw_topology": "BLANK_GW",
        "period_flags": {
            "blank_gw_teams": [4],
            "double_gw_teams": [],
        },
        "competition_coverage": {
            "official_pl": True,
            "verified_non_pl_schedule_bound": False,
        },
        "player_workload": [
            {
                "element_id": 1,
                "gw_state": "BLANK",
                "planning_gw_fixtures": [],
            }
        ],
        "weather": [],
        "workload_feeds_p1_1_review_only": True,
        "static_fatigue_penalty_applied": False,
        "weather_mutates_football_model": False,
        "dgw_cross_fixture_covariance_claimed": False,
    }
    report = {
        "sections": [
            _section("S02", "OUR15", {"rows": current15}),
            _section("S05", "FIXTURES / GW CALENDAR / WORKLOAD / REST / CONDITIONS", s05, state="DEGRADED"),
            _section("S06", "FORMATION / XI / BENCH", {}, state="DEGRADED"),
            _section("S09", "CHIP STRATEGY", {}, state="DEGRADED"),
            _section("S14", "PACKAGE OPTIMIZER / TRANSFER FRONTIER", {}, state="DEGRADED"),
            _section("S14B", "3-GW SQUAD STAGING", {}, state="DEGRADED"),
            _section("S19", "FINAL JUDGEMENT", {"final_judgement": {}}),
        ]
    }
    failures = validate_deep_decision_content_delivery(report, render_deep_text(report))
    for sid in ("S06", "S09", "S14", "S14B", "S19"):
        assert f"S05_BGW_NOT_PROPAGATED_{sid}" in failures

    report["sections"][2]["content"].update({
        "bgw_context": dict(bgw),
        "bgw_lineup_review_required": True,
    })
    report["sections"][3]["content"].update({
        "bgw_context": dict(bgw),
        "bgw_chip_review_required": True,
    })
    report["sections"][4]["content"].update({
        "bgw_context": dict(bgw),
        "bgw_frontier_review_required": True,
        "bgw_is_context_not_second_optimizer": True,
    })
    report["sections"][5]["content"].update({
        "bgw_context": dict(bgw),
        "bgw_reoptimization_trigger": True,
    })
    report["sections"][6]["content"]["final_judgement"].update({
        "bgw_context": dict(bgw),
        "bgw_reconciled": True,
    })
    repaired = validate_deep_decision_content_delivery(report, render_deep_text(report))
    for sid in ("S06", "S09", "S14", "S14B", "S19"):
        assert f"S05_BGW_NOT_PROPAGATED_{sid}" not in repaired
    assert "S05_BGW_S06_REVIEW_MISSING" not in repaired
    assert "S05_BGW_S09_CHIP_REVIEW_MISSING" not in repaired
    assert "S05_BGW_S14_FRONTIER_REVIEW_MISSING" not in repaired
    assert "S05_BGW_S14B_REOPTIMIZE_MISSING" not in repaired
    assert "S05_BGW_S19_RECONCILIATION_MISSING" not in repaired
