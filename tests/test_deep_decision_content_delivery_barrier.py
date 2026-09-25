from __future__ import annotations

from datetime import datetime, timezone
import inspect
import json
from pathlib import Path

import pytest

from src.engines import v12_integrated_report_runner as integrated_runner
from src.engines.v12_deep_delivery import (
    select_personal_evidence,
    validate_deep_decision_content_delivery,
)
from src.engines.v12_integrated_report_runner import (
    _fingerprint,
    _personal_evidence_resolution,
    run_deep,
)
from src.engines.v12_package_utility import (
    select_stage3_material_mc_routes,
)
from src.engines.v12_report_orchestration import (
    _render_deep_visible_contract_lines,
    build_price20,
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
    if state == "COMPLETE" and section_id in {"S06", "S08", "S11", "S12", "S13", "S14", "S15B", "S16", "S16B"}:
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
        "football_frontier_status": "COMPLETE",
        "execution_economics_status": "COMPLETE",
        "executable": True,
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
            "football_frontier_status": "COMPLETE",
            "execution_economics_status": "COMPLETE",
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
                    "football_frontier_status": "COMPLETE",
                    "execution_economics_status": "NOT_REQUIRED",
                    "executable": True,
                    "affordability": "NOT_REQUIRED",
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


def test_p1_explicit_current15_state_outranks_stale_previous_gw_runtime(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    state = json.loads(
        (root / "control/fpl_master_v12/FPL_MASTER_STATE_V12.json").read_text(
            encoding="utf-8"
        )
    )
    confirmed = dict(state["confirmed_current_squad_state"])
    planning_gw = int(confirmed["applicable_planning_gw"])

    confirmed_rows = []
    for group in ("goalkeepers", "defenders", "midfielders", "forwards"):
        confirmed_rows.extend(
            dict(row) for row in confirmed.get(group) or []
        )
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

SEMANTIC_REGRESSION_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "v12_run_36126675342_semantic_regression.json"
)


def _semantic_regression_fixture() -> dict:
    return json.loads(
        SEMANTIC_REGRESSION_FIXTURE.read_text(encoding="utf-8")
    )


def test_semantic_regression_36126675342_auth_false_pass_is_rejected():
    evidence = _semantic_regression_fixture()
    report = {
        "sections": [
            _section(
                "S17",
                "SOURCE HEALTH / FRESHNESS / LINEAGE",
                {
                    "source_health": {
                        "authenticated_personal_scope": evidence["s17"][
                            "prior_visible_authenticated_personal_scope"
                        ],
                    },
                    "bound_authoritative_health": {
                        "auth_state": evidence["s17"]["bound_auth_state"],
                        "personal_status": evidence["s17"][
                            "bound_personal_status"
                        ],
                    },
                },
            ),
        ]
    }
    failures = validate_deep_decision_content_delivery(
        report,
        "## 17. SOURCE HEALTH / FRESHNESS / LINEAGE",
    )
    assert "S17_AUTH_CONTRADICTION=HEALTHY!=AUTH_EXPIRED" in failures


def test_semantic_regression_36126675342_unknown_ft_never_claims_save_or_roll():
    evidence = _semantic_regression_fixture()
    bad = {
        "sections": [
            _section(
                "S14B",
                "3-GW SQUAD STAGING",
                {
                    "ft_authority": {
                        "known": False,
                        "free_transfers": None,
                    },
                    "ft_saving_plan": evidence["s14b"]["prior_ft_saving_plan"],
                    "order_of_transfers": evidence["s14b"]["prior_planned_move"],
                    "staging_rows": [
                        {
                            "planned_move": evidence["s14b"][
                                "prior_planned_move"
                            ],
                        }
                    ],
                },
            )
        ]
    }
    failures = validate_deep_decision_content_delivery(
        bad,
        "## 14B. 3-GW SQUAD STAGING",
    )
    assert "FT_UNKNOWN_BUT_SAVE_OR_ROLL_CLAIMED" in failures

    staging = integrated_runner._three_gw_staging(
        planning_gw=6,
        action="WAIT",
        stage3_decision={
            "selected_route_id": "HOLD",
            "reason": "NO_POSITIVE_ROUTE",
        },
        stage3_visible={
            "package_routes": [
                {
                    "route": "HOLD",
                    "moves": {"out": [], "in": []},
                    "three_gw": 0.0,
                }
            ]
        },
        all15_rows=[],
        lineup={"formation": "5-4-1", "starting_xi": []},
        finance={
            "free_transfers": None,
            "free_transfers_authoritative": False,
            "free_transfers_status": "NOT_SUPPORTED",
            "bank": None,
            "bank_status": "UNAVAILABLE",
            "sell_value_status": "UNAVAILABLE",
        },
    )
    assert staging["ft_saving_plan"] == "FT STATE UNAVAILABLE"
    assert staging["order_of_transfers"] == "NO TRANSFER NOW"
    assert staging["ft_authority"]["known"] is False
    assert all(
        "SAVE FT" not in str(row.get("planned_move") or "").upper()
        and "ROLL FT" not in str(row.get("planned_move") or "").upper()
        for row in staging["staging_rows"]
    )


def test_semantic_regression_36126675342_score_semantics_reconcile():
    evidence = _semantic_regression_fixture()["s06"]
    content = integrated_runner._lineup_content(
        {
            "formation": evidence["selected_formation"],
            "starting_xi": list(range(1, 12)),
            "bench": {"gk": 12, "order": [13, 14, 15]},
            "captain": {"element": 1},
            "vice_captain": {"element": 2},
            "lineup_score": {
                "xpts_mean": evidence["xi_base_xpts"],
                "captain_multiplier_value": evidence[
                    "captain_multiplier_value"
                ],
                "vice_fallback_value": evidence["vice_fallback_value"],
            },
            "formation_comparison": [
                {
                    "formation": evidence["selected_formation"],
                    "expected_fpl_points_with_captain_vice": evidence[
                        "selected_captain_adjusted_xpts"
                    ],
                    "route_utility": evidence[
                        "selected_lineup_route_utility"
                    ],
                    "selected": True,
                }
            ],
        }
    )
    semantics = content["score_semantics"]
    assert semantics["xi_base_xpts"] == pytest.approx(49.777897)
    assert semantics["captain_adjusted_xpts"] == pytest.approx(55.012527)
    assert semantics["lineup_route_utility"] == pytest.approx(54.817245)
    assert semantics["derived_captain_adjusted_xpts"] == pytest.approx(
        semantics["captain_adjusted_xpts"]
    )

    visible, _ = _render_deep_visible_contract_lines(
        section_id="S06",
        content=content,
        owned_ids=set(range(1, 16)),
        owned_names={index: f"P{index}" for index in range(1, 16)},
    )
    body = "\n".join(visible)
    assert "XI_BASE_XPTS: 49.777897" in body
    assert "CAPTAIN_ADJUSTED_XPTS: 55.012527" in body
    assert "LINEUP_ROUTE_UTILITY: 54.817245" in body
    assert "PROJECTED XI SCORE:" not in body


def test_semantic_regression_36126675342_unresolved_finance_not_executable():
    evidence = _semantic_regression_fixture()["s14"]
    route_id = evidence["sample_non_hold_route"]
    report = {
        "sections": [
            _section(
                "S14",
                "PACKAGE OPTIMIZER / TRANSFER FRONTIER",
                {
                    "football_frontier_status": "COMPLETE",
                    "execution_economics_status": "DEGRADED",
                    "package_routes": [
                        {
                            "route": route_id,
                            "execution_economics_status": "DEGRADED",
                            "executable": True,
                            "action_verdict": "ACT",
                        }
                    ],
                    "frontier": [{}],
                },
            )
        ]
    }
    failures = validate_deep_decision_content_delivery(
        report,
        (
            "FOOTBALL FRONTIER STATUS: COMPLETE "
            "EXECUTION ECONOMICS STATUS: DEGRADED EXECUTABLE YES "
            "OUT → IN 1GW 2GW 3GW 5GW P>HOLD Q10 Q90 "
            "BANK BEFORE BANK AFTER BEST ALTERNATIVE"
        ),
    )
    assert (
        "S14_DEGRADED_ECONOMICS_MARKED_EXECUTABLE=" + route_id
        in failures
    )


def test_semantic_regression_36126675342_stale_price_cannot_be_complete():
    evidence = _semantic_regression_fixture()["price"]
    rows = [
        {
            "element_id": 1000 + index,
            "name": f"P{index}",
            "direction": "RISE",
            "rank": index,
            "estimate_source": "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
        }
        for index in range(1, 21)
    ]
    result = build_price20(
        predictor_artifact={
            "health": "GREEN",
            "checked_at": evidence["predictor_checked_at"],
            "rows": rows,
        },
        direction="RISE",
        as_of=evidence["report_slot"],
    )
    assert result["freshness_state"] == "STALE"
    assert result["source_age_seconds"] > result[
        "freshness_threshold_seconds"
    ]
    assert result["state"] == "DEGRADED"
    assert "stale" in result["degradation_reason"].lower()

