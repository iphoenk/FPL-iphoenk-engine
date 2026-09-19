from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.report_plane.delivery_integrity import MANDATORY_SECTIONS
from src.runtime_v6.domains.report_plane.report_qa import (
    _FULL_DEEP_VISIBLE_ORDER,
    _MATCH_VISIBLE_ORDER,
    _POST_ALL_MATCH_ORDER,
    _PRICE_VISIBLE_ORDER,
    _validate_v12_rendered_body,
    validate_post_render_qa,
    validate_pre_render_qa,
    validate_v12_visible_content_contract,
)
from test_support.report_visible_body import valid_visible_body


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


def _degraded(section, available, expected, reason="authoritative source incomplete", **extra):
    return {
        "state": "DEGRADED",
        "available_count": available,
        "expected_count": expected,
        "degradation_reason": reason,
        **extra,
    }


def test_19_watchlist_complete_17_of_20_is_hard_failure():
    payload = _deep()
    payload["watchlist20"] = payload["watchlist20"][:17]
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert result["report_can_continue"] is False
    assert result["severity"] == "FAIL"
    assert "WATCHLIST20_COUNT=17" in result["hard_failures"]


def test_20_watchlist_degraded_17_of_20_continues_truthfully():
    payload = _deep()
    payload["watchlist20"] = payload["watchlist20"][:17]
    payload["section_states"] = {
        "WATCHLIST20": _degraded("WATCHLIST20", 17, 20, "3 candidates lack valid current canonical evaluation")
    }
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert result["hard_failures"] == []
    assert result["report_can_continue"] is True
    assert result["severity"] == "DEGRADED"
    assert result["section_degradations"][0]["available_count"] == 17
    assert result["section_degradations"][0]["expected_count"] == 20


def test_21_rise_fall_partial_provider_coverage_continues():
    payload = _deep()
    payload["section_states"] = {
        "RISE20": _degraded("RISE20", 13, 20, "price provider partial"),
        "FALL20": _degraded("FALL20", 11, 20, "price provider partial"),
    }
    payload["rise20"] = [{"element_id": index} for index in range(201, 214)]
    payload["fall20"] = [{"element_id": index} for index in range(301, 312)]
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert result["hard_failures"] == []
    assert result["report_can_continue"] is True
    assert {row["section"] for row in result["section_degradations"]} >= {"RISE20", "FALL20"}


def test_22_all15_personal_scope_unavailable_continues_without_fabrication():
    payload = _deep()
    payload["all15"] = []
    payload["section_states"] = {
        "ALL15": _degraded("ALL15", 0, 15, "authenticated personal scope unavailable")
    }
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert result["hard_failures"] == []
    assert result["report_can_continue"] is True
    assert payload["all15"] == []


def test_23_icon_unavailable_continues_without_current_rank_or_eo_requirement():
    payload = _match()
    payload["icon"] = {"status": "UNAVAILABLE", "freshness": "UNAVAILABLE"}
    payload["section_states"] = {
        "ICON+": {
            "state": "UNAVAILABLE",
            "degradation_reason": "mini-league source unavailable",
        }
    }
    result = validate_v12_visible_content_contract(report_mode="MATCH", content_contract=payload)
    assert result["hard_failures"] == []
    assert result["report_can_continue"] is True
    assert result["severity"] == "DEGRADED"


def test_24_final_missing_ft_state_degrades_package_but_report_continues():
    payload = _final()
    del payload["gw_lock_package"]["ft_hit_treatment"]
    payload["section_states"] = {
        "GW_LOCK_PACKAGE": {
            "state": "DEGRADED",
            "degradation_reason": "authoritative FT state unavailable after bounded recovery",
            "missing_fields": ["ft_hit_treatment"],
        }
    }
    result = validate_v12_visible_content_contract(report_mode="FINAL", content_contract=payload)
    assert result["hard_failures"] == []
    assert result["report_can_continue"] is True
    assert any(row["section"] == "GW_LOCK_PACKAGE" for row in result["section_degradations"])


def test_25_final_complete_with_malformed_xi_is_hard_failure():
    payload = _final()
    payload["gw_lock_package"]["xi_exact11"] = payload["gw_lock_package"]["xi_exact11"][:10]
    result = validate_v12_visible_content_contract(report_mode="FINAL", content_contract=payload)
    assert result["report_can_continue"] is False
    assert "GW_LOCK_PACKAGE_XI_INVALID" in result["hard_failures"]


def test_26_post_all_match_complete_missing_fixture_is_hard_failure():
    payload = _post_all_match()
    payload["match_scout"] = payload["match_scout"][:1]
    result = validate_v12_visible_content_contract(report_mode="POST_ALL_MATCH", content_contract=payload)
    assert result["report_can_continue"] is False
    assert "MATCH_SCOUT_FIXTURE_COVERAGE_MISMATCH" in result["hard_failures"]


def test_27_post_all_match_degraded_missing_fixture_continues():
    payload = _post_all_match()
    payload["match_scout"] = payload["match_scout"][:1]
    payload["section_states"] = {
        "MATCH_SCOUT": _degraded(
            "MATCH_SCOUT",
            1,
            2,
            "fixture 102 source unavailable",
            missing_scope=["fixture:102"],
        )
    }
    result = validate_v12_visible_content_contract(report_mode="POST_ALL_MATCH", content_contract=payload)
    assert result["hard_failures"] == []
    assert result["report_can_continue"] is True
    scout = next(row for row in result["section_degradations"] if row["section"] == "MATCH_SCOUT")
    assert scout["missing_scope"] == ["fixture:102"]


def test_28_package_optimizer_unavailable_continues_without_fabricated_hold():
    payload = _deep()
    payload["package_routes"] = []
    payload["section_states"] = {
        "PACKAGE_FRONTIER": {
            "state": "UNAVAILABLE",
            "degradation_reason": "optimizer/search scope unavailable after bounded recovery",
        }
    }
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert result["hard_failures"] == []
    assert result["report_can_continue"] is True
    assert payload["package_routes"] == []


def test_29_package_complete_without_hold_is_hard_failure():
    payload = _deep()
    payload["package_routes"] = payload["package_routes"][1:]
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert result["report_can_continue"] is False
    assert "PACKAGE_HOLD_BASELINE_MISSING" in result["hard_failures"]


def test_30_multiple_degraded_optional_scopes_still_allow_due_report():
    payload = _deep()
    payload["watchlist20"] = payload["watchlist20"][:17]
    payload["package_routes"] = []
    payload["icon"] = {"status": "UNAVAILABLE", "freshness": "UNAVAILABLE"}
    payload["section_states"] = {
        "WATCHLIST20": _degraded("WATCHLIST20", 17, 20, "canonical evaluation partial"),
        "PACKAGE_FRONTIER": {
            "state": "UNAVAILABLE",
            "degradation_reason": "optimizer unavailable",
        },
        "ICON+": {
            "state": "UNAVAILABLE",
            "degradation_reason": "mini-league source unavailable",
        },
    }
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert result["hard_failures"] == []
    assert result["report_can_continue"] is True
    assert result["severity"] == "DEGRADED"
    assert len(result["section_degradations"]) >= 3


def test_31_rendered_body_must_visibly_label_every_degraded_section():
    payload = _deep()
    payload["watchlist20"] = payload["watchlist20"][:17]
    payload["section_states"] = {
        "WATCHLIST20": _degraded("WATCHLIST20", 17, 20, "canonical evaluation partial")
    }
    failures = _validate_v12_rendered_body(
        report_mode="DEEP",
        rendered_body="WATCHLIST20\n17 rows available",
        content_contract=payload,
    )
    assert "VISIBLE_DEGRADATION_LABEL_MISSING=WATCHLIST20:DEGRADED" in failures
    failures = _validate_v12_rendered_body(
        report_mode="DEEP",
        rendered_body="WATCHLIST20\nSTATE=DEGRADED\nAVAILABLE=17 EXPECTED=20",
        content_contract=payload,
    )
    assert "VISIBLE_DEGRADATION_LABEL_MISSING=WATCHLIST20:DEGRADED" not in failures


def test_32_placeholder_rows_are_hard_failure_even_in_degraded_section():
    payload = _deep()
    payload["watchlist20"] = payload["watchlist20"][:17]
    payload["watchlist20"].append(
        {
            **_watchlist20()[17],
            "placeholder": True,
            "row_origin": "QA_FILL",
        }
    )
    payload["section_states"] = {
        "WATCHLIST20": _degraded("WATCHLIST20", 18, 20, "canonical evaluation partial")
    }
    result = validate_v12_visible_content_contract(report_mode="DEEP", content_contract=payload)
    assert result["report_can_continue"] is False
    assert "WATCHLIST20_FABRICATED_PLACEHOLDER_ROW=18" in result["hard_failures"]

def _fake_compute_contract_for_severity():
    return {
        "status": "PASS",
        "compute_ready": True,
        "next_action": "PRE_RENDER_QA",
        "delivery_ready": False,
        "legacy_fallback_allowed": False,
        "compute_fingerprint": "a" * 64,
        "OUR15": {"status": "PASS", "total": 15},
        "XI": {"status": "PASS", "total": 11},
        "BENCH": {"status": "PASS", "total": 4},
        "WATCHLIST20": {"status": "PASS", "total": 20},
        "RISE20": {"status": "PASS", "total": 20},
        "FALL20": {"status": "PASS", "total": 20},
        "FACT_MODEL": {
            "status": "PASS",
            "overlap": [],
            "fact_keys": ["official_price"],
            "model_keys": ["projection"],
            "inference_keys": ["decision"],
        },
        "SECTION_CONTRACT": {"status": "PASS", "failures": []},
        "failures": [],
    }


def _severity_manifest():
    return [{"section_id": section_id, "status": "COMPLETE"} for section_id in MANDATORY_SECTIONS]


def _degraded_watchlist_body(pre, *, include_label=True):
    body = valid_visible_body(pre)
    output = []
    for line in body.splitlines():
        if any(line.startswith(f"| {rank} |") for rank in (18, 19, 20)):
            continue
        output.append(line)
        if include_label and line.startswith("## 10."):
            output.extend([
                "WATCHLIST20 STATE=DEGRADED",
                "AVAILABLE=17 EXPECTED=20",
                "REASON=canonical evaluation partial",
            ])
    output.extend(["DECISION DELTA", "NO MATERIAL DECISION CHANGE"])
    return "\n".join(output) + "\n"


def test_33_pre_render_allows_matching_compute_count_failure_when_section_is_truthfully_degraded():
    payload = _deep()
    payload["watchlist20"] = payload["watchlist20"][:17]
    payload["section_states"] = {
        "WATCHLIST20": _degraded("WATCHLIST20", 17, 20, "canonical evaluation partial")
    }
    compute = _fake_compute_contract_for_severity()
    compute.update(
        {
            "status": "FAIL",
            "compute_ready": False,
            "next_action": "RECOMPUTE",
            "WATCHLIST20": {"status": "FAIL", "total": 17},
            "SECTION_CONTRACT": {"status": "FAIL", "failures": ["WATCHLIST20"]},
            "failures": ["SECTION_CONTRACT"],
        }
    )
    pre = validate_pre_render_qa(
        compute_contract=compute,
        section_manifest=_severity_manifest(),
        mini_league_denominator_complete=True,
        report_mode="DEEP",
        weather_contract_state="DIRECT_CHATGPT",
        visible_content_contract=payload,
    )
    assert pre["status"] == "PASS"
    assert pre["qa_severity"] == "DEGRADED"
    assert pre["report_can_continue"] is True
    assert pre["hard_failures"] == []
    assert "WATCHLIST20" not in pre["expected_counts"]


def test_34_pre_and_post_render_agree_on_truthful_degradation_and_visible_label():
    payload = _deep()
    payload["watchlist20"] = payload["watchlist20"][:17]
    payload["section_states"] = {
        "WATCHLIST20": _degraded("WATCHLIST20", 17, 20, "canonical evaluation partial")
    }
    pre = validate_pre_render_qa(
        compute_contract=_fake_compute_contract_for_severity(),
        section_manifest=_severity_manifest(),
        mini_league_denominator_complete=True,
        report_mode="DEEP",
        weather_contract_state="DIRECT_CHATGPT",
        visible_content_contract=payload,
    )
    assert pre["status"] == "PASS"
    assert pre["qa_severity"] == "DEGRADED"
    rendered_counts = dict(pre["expected_counts"])
    rendered_counts["WATCHLIST20"] = 17

    post = validate_post_render_qa(
        pre_render_qa=pre,
        rendered_body=_degraded_watchlist_body(pre, include_label=True),
        rendered_section_ids=list(pre["expected_section_ids"]),
        rendered_section_states={row["section_id"]: row["status"] for row in pre["section_manifest"]},
        rendered_compute_fingerprint=pre["compute_fingerprint"],
        render_contract_token=pre["render_contract_token"],
        rendered_counts=rendered_counts,
        rendered_fact_keys=list(pre["expected_fact_keys"]),
        rendered_model_keys=list(pre["expected_model_keys"]),
        rendered_mini_league_denominator_complete=True,
        rendered_weather_direct_chat_present=True,
        rendered_visible_content_contract=payload,
        truncated=False,
    )
    assert post["status"] == "PASS"
    assert post["qa_severity"] == "DEGRADED"
    assert post["report_can_continue"] is True
    assert post["hard_failures"] == []

    post_missing = validate_post_render_qa(
        pre_render_qa=pre,
        rendered_body=_degraded_watchlist_body(pre, include_label=False),
        rendered_section_ids=list(pre["expected_section_ids"]),
        rendered_section_states={row["section_id"]: row["status"] for row in pre["section_manifest"]},
        rendered_compute_fingerprint=pre["compute_fingerprint"],
        render_contract_token=pre["render_contract_token"],
        rendered_counts=rendered_counts,
        rendered_fact_keys=list(pre["expected_fact_keys"]),
        rendered_model_keys=list(pre["expected_model_keys"]),
        rendered_mini_league_denominator_complete=True,
        rendered_weather_direct_chat_present=True,
        rendered_visible_content_contract=payload,
        truncated=False,
    )
    assert post_missing["status"] == "FAIL"
    assert "VISIBLE_DEGRADATION_LABEL_MISSING=WATCHLIST20:DEGRADED" in post_missing["hard_failures"]

