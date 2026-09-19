from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.report_plane.report_qa import (
    _FULL_DEEP_VISIBLE_ORDER,
    _MATCH_VISIBLE_ORDER,
    _POST_ALL_MATCH_ORDER,
    _PRICE_VISIBLE_ORDER,
    _validate_v12_rendered_body,
    validate_v12_visible_content_contract,
)


def _bench():
    return {
        "bench_gk": "GK2",
        "outfield_autosub_priority": ["D5", "M5", "F3"],
        "position_by_player": {"GK2": "GK", "D5": "DEF", "M5": "MID", "F3": "FWD"},
    }


def _delta_changed():
    return {
        "rows": [
            {
                "decision_item": "XI status",
                "previous_state": "OPEN",
                "current_state": "LOCKED",
                "material_change": True,
                "reason": "official team news",
                "evidence_time": "2026-09-19T09:30:00+07:00",
            }
        ],
        "no_material_decision_change": False,
    }


def _delta_no_change():
    return {"rows": [], "no_material_decision_change": True}


def _all15():
    rows = []
    for index in range(1, 16):
        rows.append(
            {
                "element_id": index,
                "player": f"P{index}",
                "opponent": "OPP",
                "recommended_or_locked_role": "START" if index <= 11 else "BENCH",
                "p_available": 0.99,
                "p_start": 0.85,
                "p_cameo": 0.08,
                "p_dnp": 0.07,
                "xmins": 75.0,
                "tactical_role": "ROLE",
                "set_piece_penalty_role": "NONE",
                "matchup": "NEUTRAL",
                "gw_plus_1": 4.0,
                "three_gw": 12.0,
                "five_gw": 20.0,
                "uncertainty_floor_upside": "3.0 / 7.0",
                "action": "HOLD",
            }
        )
    return rows


def _watchlist20():
    rows = []
    element = 100
    for position in ("GK", "DEF", "MID", "FWD"):
        for _ in range(5):
            element += 1
            rows.append(
                {
                    "element_id": element,
                    "rank": len(rows) + 1,
                    "player": f"W{element}",
                    "position": position,
                    "club": "CLUB",
                    "price": 5.0,
                    "next_opponent": "OPP",
                    "football_score": 0.72,
                    "p_start": 0.9,
                    "xmins": 80,
                    "gw_plus_1": 4.2,
                    "three_gw": 12.7,
                    "five_gw": 21.4,
                    "role_set_piece_note": "ROLE",
                    "main_upside": "UPSIDE",
                    "main_risk": "RISK",
                    "action": "WATCH",
                    "owned": False,
                }
            )
    return rows


def _routes():
    fields = {
        "moves": 0,
        "transfer_cost": 0,
        "gw1_net": 0.0,
        "two_gw_if_relevant": None,
        "three_gw": 0.0,
        "five_gw": 0.0,
        "p_beats_hold": 0.5,
        "expected_regret": 0.0,
        "robustness": "BASELINE",
        "price_risk": "LOW",
        "structure_effect": "NONE",
        "action_verdict": "HOLD",
    }
    return [
        {"route": "HOLD", **fields},
        {
            "route": "A_TO_B",
            **{**fields, "moves": 1, "gw1_net": 1.1, "three_gw": 2.3, "five_gw": 3.1, "action_verdict": "WATCH"},
        },
    ]


def _icon():
    def metric(n, d):
        return {"numerator": n, "denominator": d, "percentage": round(n / d * 100.0, 1)}
    return {
        "status": "FRESH",
        "metrics": {
            "ownership": metric(51, 58),
            "starter_share": metric(49, 58),
            "captain_share": metric(31, 58),
            "vice_share": metric(10, 58),
            "eo": {"percentage": 138.4},
        },
    }


def _base():
    return {
        "prior_visible_report": True,
        "decision_delta": _delta_no_change(),
        "calibration_items": [{"status": "CALIBRATION_INPUT"}],
        "bench_presentation": _bench(),
        "icon": _icon(),
        "football_optimal_baseline_before_icon": True,
        "report_due": True,
        "optional_scope_degraded": False,
        "visible_report_suppressed": False,
    }


def _match():
    payload = _base()
    payload.update(
        {
            "visible_order": list(_MATCH_VISIBLE_ORDER),
            "locked_team": {"status": "CURRENT_IMMUTABLE"},
            "personal_impact": [
                {
                    "element_id": 8,
                    "personal_state": "CAMEO_BLOCKED_AUTOSUB",
                    "autosub_activates": False,
                }
            ],
            "global_autosub_state": {"final_substitution_map": {}},
            "captain_vice_consequence": {},
            "owned_live_final_points": [],
            "bonus_bps": {"provisional": True},
            "cards_injury_defcon_role_events": [],
            "league_wide_signals": [],
            "next_gw_learning": [],
            "next_critical_observation": "next fixture",
            "source_freshness": {},
        }
    )
    return payload


def _deep():
    payload = _base()
    payload.update(
        {
            "visible_order": list(_FULL_DEEP_VISIBLE_ORDER),
            "all15": _all15(),
            "watchlist20": _watchlist20(),
            "watchlist_full_universe_derived": True,
            "package_routes": _routes(),
            "serious_comparison": True,
            "search_authority": "FULL",
            "search_authority_visible": True,
        }
    )
    return payload


def _final():
    payload = _deep()
    payload.update(
        {
            "gw_lock_package": {
                "target_gw": 5,
                "transfers_out": [],
                "transfers_in": [],
                "number_of_moves": 0,
                "ft_hit_treatment": "UNKNOWN FT / NO FABRICATION",
                "bank_after_if_known": "UNKNOWN",
                "formation": "3-5-2",
                "xi_exact11": list(range(1, 12)),
                "bench_gk": 12,
                "outfield_bench_priority_1_3": [13, 14, 15],
                "captain": 9,
                "vice_captain": 5,
                "chip": "NONE",
                "primary_action": "HOLD",
                "abort_trigger": "material team news",
                "fallback": "WAIT",
                "evidence_timestamp": "2026-09-19T09:30:00+07:00",
                "canonical_authority_version": "FPL MASTER CANONICAL V12",
            },
            "selected_package_unambiguous": True,
        }
    )
    return payload


def _scout_row(fixture_id):
    return {
        "fixture_id": fixture_id,
        "result": "1-0",
        "formation_system": "4-3-3",
        "coach_pattern": "stable",
        "player_roles": "documented",
        "minutes_substitution_pattern": "documented",
        "xg_xa_xgi_shots_chances": "available",
        "set_pieces_penalties": "available",
        "defcon": "available",
        "opponent_channels": "wide",
        "sustainable_vs_noisy": "mixed",
        "implication_for_our15": "review",
        "implication_for_next_opponent": "review",
        "posterior_calibration_implication": "CALIBRATION INPUT",
    }


def _post_all_match():
    payload = _deep()
    payload.update(
        {
            "visible_order": list(_POST_ALL_MATCH_ORDER),
            "completed_fixture_ids": [101, 102],
            "match_scout": [_scout_row(101), _scout_row(102)],
        }
    )
    return payload


def _match_body(*, extra=""):
    blocks = [
        "MATCH CHECKPOINT / GW STATUS",
        "LOCKED PERSONAL TEAM",
        "PERSONAL IMPACT FIRST\nP8: CAMEO_BLOCKED_AUTOSUB",
        "GLOBAL AUTOSUB STATE",
        "CAPTAIN / VICE CONSEQUENCE",
        "OWNED LIVE/FINAL POINTS",
        "BONUS/BPS",
        "CARDS / INJURY / DEFCON / ROLE EVENTS",
        "RELEVANT LEAGUE-WIDE SIGNALS",
        "ICON+ LIVE",
        "NEXT-GW LEARNING",
        "NEXT CRITICAL OBSERVATION",
        "SOURCE / FRESHNESS STATUS",
        "Bench GK: GK2",
        "Outfield autosub priority: 1 D5, 2 M5, 3 F3",
        "DECISION DELTA",
        extra,
    ]
    return "\n".join(blocks)


def test_01_pure_match_owned_cameo_precedes_generic_story():
    payload = _match()
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert result["status"] == "PASS"
    rendered = _validate_v12_rendered_body(report_mode="MATCH", rendered_body=_match_body(), content_contract=payload)
    assert "PURE_MATCH_RENDER_ORDER_INVALID" not in rendered


def test_02_dnp_autosub_displayed_from_final_global_map():
    payload = _match()
    payload["personal_impact"] = [{"element_id": 7, "personal_state": "DNP_WITH_AUTOSUB_POSSIBLE"}]
    payload["global_autosub_state"] = {"final_substitution_map": {"7": 13}}
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert result["status"] == "PASS"


def test_03_bench_dnp_cannot_claim_own_autosub_activation():
    payload = _match()
    payload["personal_impact"] = [
        {
            "element_id": 15,
            "personal_state": "BENCH_DNP_NO_DIRECT_XI_AUTOSUB_EFFECT",
            "autosub_activates": True,
        }
    ]
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert "BENCH_DNP_FALSE_AUTOSUB_ACTIVATION=1" in result["failures"]


def test_04_bench_gk_is_visually_separate_from_outfield_priority():
    payload = _match()
    payload["bench_presentation"]["outfield_autosub_priority"][0] = "GK2"
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert "BENCH_GK_RENDERED_AS_OUTFIELD_PRIORITY" in result["failures"]


def test_05_normal_report_rejects_repair_debug_language():
    failures = _validate_v12_rendered_body(
        report_mode="MATCH",
        rendered_body=_match_body(extra="personal-team reconciliation corrected"),
        content_contract=_match(),
    )
    assert any(item.startswith("VISIBLE_DEBUG_LANGUAGE=") for item in failures)


def test_06_observation_cannot_be_claimed_as_posterior_update_without_execution_proof():
    payload = _match()
    failures = _validate_v12_rendered_body(
        report_mode="MATCH",
        rendered_body=_match_body(extra="posterior updated after this cameo"),
        content_contract=payload,
    )
    assert "UNPROVEN_MODEL_RECOMPUTATION_CLAIM" in failures

    payload["calibration_items"] = [
        {
            "status": "ACTUAL_MODEL_UPDATE",
            "execution_proof": {
                "executed": True,
                "previous_value": 0.84,
                "current_value": 0.71,
                "evidence_time": "2026-09-19T09:30:00+07:00",
            },
        }
    ]
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert result["status"] == "PASS"


def test_07_decision_delta_changed_case():
    payload = _match()
    payload["decision_delta"] = _delta_changed()
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert result["status"] == "PASS"


def test_08_decision_delta_no_change_case():
    payload = _match()
    payload["decision_delta"] = _delta_no_change()
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert result["status"] == "PASS"


def test_09_all15_requires_exactly_15_unique_owned_rows():
    payload = _deep()
    assert validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)["status"] == "PASS"
    payload["all15"] = payload["all15"][:-1]
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert "ALL15_COUNT=14" in result["failures"]


def test_10_watchlist_requires_exact20_and_5_5_5_5():
    payload = _deep()
    assert validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)["status"] == "PASS"
    payload["watchlist20"][0]["position"] = "DEF"
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert "WATCHLIST20_GK=4" in result["failures"]
    assert "WATCHLIST20_DEF=6" in result["failures"]


def test_11_package_table_must_include_hold_baseline():
    payload = _deep()
    payload["package_routes"] = payload["package_routes"][1:]
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert "PACKAGE_HOLD_BASELINE_MISSING" in result["failures"]


def test_12_final_contains_exact_unambiguous_lock_package():
    payload = _final()
    result = validate_v12_visible_content_contract(report_mode="FINAL", content_contract=payload)
    assert result["status"] == "PASS"
    payload["gw_lock_package"]["xi_exact11"] = payload["gw_lock_package"]["xi_exact11"][:-1]
    result = validate_v12_visible_content_contract(report_mode="FINAL", content_contract=payload)
    assert "GW_LOCK_PACKAGE_XI_INVALID" in result["failures"]


def test_13_full_match_overlap_rejects_duplicated_report_blocks():
    payload = _deep()
    payload["visible_block_ids"] = ["DECISION", "OUR15", "PERSONAL_IMPACT", "PERSONAL_IMPACT"]
    result = validate_v12_visible_content_contract(report_mode="OVERLAP", content_contract=payload)
    assert "FULL_MATCH_DUPLICATED_REPORT_BLOCK" in result["failures"]


def test_14_post_all_match_represents_every_completed_fixture_exactly_once():
    payload = _post_all_match()
    result = validate_v12_visible_content_contract(report_mode="POST_ALL_MATCH", content_contract=payload)
    assert result["status"] == "PASS"
    payload["match_scout"].append(_scout_row(101))
    result = validate_v12_visible_content_contract(report_mode="POST_ALL_MATCH", content_contract=payload)
    assert "MATCH_SCOUT_FIXTURE_DUPLICATE" in result["failures"]
    assert "MATCH_SCOUT_FIXTURE_COVERAGE_MISMATCH" in result["failures"]


def test_15_icon_denominator_arithmetic_must_be_consistent():
    payload = _match()
    payload["icon"]["metrics"]["ownership"]["percentage"] = 90.0
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert "ICON_ARITHMETIC_MISMATCH=ownership" in result["failures"]


def test_16_optional_degraded_scope_never_suppresses_due_report():
    payload = _match()
    payload["optional_scope_degraded"] = True
    payload["visible_report_suppressed"] = False
    assert validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)["status"] == "PASS"
    payload["visible_report_suppressed"] = True
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert "OPTIONAL_DEGRADED_SCOPE_SUPPRESSED_DUE_REPORT" in result["failures"]


def test_17_price_report_compares_price_risk_with_information_value_of_waiting():
    payload = _base()
    payload.update(
        {
            "visible_order": list(_PRICE_VISIBLE_ORDER),
            "material_price_route_count": 1,
            "price_waiting_comparison": [
                {
                    "route": "A_TO_B",
                    "affordable_now": True,
                    "after_target_plus_0_1": False,
                    "after_owned_minus_0_1": False,
                    "sell_value_impact": -0.1,
                    "route_survival": "FRAGILE",
                    "football_information_benefit_of_waiting": "HIGH",
                }
            ],
        }
    )
    assert validate_v12_visible_content_contract(report_mode="PRICE", content_contract=payload)["status"] == "PASS"


def test_18_2130_deep_requires_overnight_risk_board():
    payload = _deep()
    payload["checkpoint_time"] = "21:30"
    payload["deep_emphasis"] = "LATE_NEWS_OVERNIGHT_PRICE_DEADLINE_RISK"
    payload["overnight_risk_board"] = [
        {
            "player_or_route": "P8",
            "current_action": "WAIT",
            "possible_change_event": "team news",
            "materiality": "HIGH",
            "next_checkpoint": "04:30",
        }
    ]
    assert validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)["status"] == "PASS"
    payload["overnight_risk_board"] = []
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert "OVERNIGHT_RISK_BOARD_MISSING" in result["failures"]
