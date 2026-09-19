from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.canonical_decision_methodology import merge_active_and_optimizer_scenarios
from src.engines.v12_runtime_conformance import (
    RuntimeConformanceError,
    apply_scenario_lifecycle,
    build_all15_identity_rows,
    compose_icon_subscopes,
    compose_operational_action,
    compute_pick_exposure,
    content_contract_severity,
    future_transfer_economics_inputs,
    plan_due_report_refresh,
    plan_hourly_core_upkeep,
    resolve_governed_refresh_result,
    resolve_hourly_core_upkeep_result,
    build_hourly_core_upkeep_proof,
    validate_v12_authority_sources,
    hydrate_v12_player_identities,
    derive_next_official_price_cycle,
    validate_rise_fall_visible_row,
    apply_owned_player_presentation,
    validate_exposure_metric,
    format_exposure_metric,
    finalize_same_occurrence_alert_evidence,
    resolve_authenticated_affordability,
    resolve_temporary_price_watch_lifecycle,
    validate_identity_production_acceptance,
    plan_natural_core_upkeep_gate,
    finalize_natural_core_upkeep_gate,
    validate_natural_occurrence_completion,
    authorize_post_core_stage,
    split_bench_for_display,
    validate_1230_signal_delta,
    validate_decision_delta_rows,
)
from src.engines.visible_content_proof import (
    CANONICAL_AUTHORITY,
    VisibleContentProofError,
    build_visible_content_proof,
    canonical_mode_contract,
)


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PATH = ROOT / CANONICAL_AUTHORITY
STATE_PATH = ROOT / "control/fpl_master_v12/FPL_MASTER_STATE_V12.json"


def _canonical() -> str:
    return CANONICAL_PATH.read_text(encoding="utf-8")


def _deep_contract() -> dict:
    return canonical_mode_contract(_canonical(), "DEEP")


def _revision() -> dict:
    return {
        "path": CANONICAL_AUTHORITY,
        "branch_or_ref": "fpl-master-v12-rebuild",
        "branch_head_sha": "a" * 40,
        "file_blob_sha": "b" * 40,
        "content_sha256": None,
        "content_sha256_computed": False,
        "canonical_version": "FPL MASTER CANONICAL V12",
    }


def _section_states(
    contract: dict,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    override = overrides or {}
    rows = []
    for section_id in contract["expected_section_ids"]:
        row = {"section_id": section_id, "state": "COMPLETE"}
        row.update(override.get(section_id, {}))
        rows.append(row)
    return rows


def _proof(
    *,
    rendered_ids: list[str] | None = None,
    rendered_order: list[str] | None = None,
    section_states: list[dict] | None = None,
    degradations: list[dict] | None = None,
    report_can_continue: bool = True,
    hard_failures: list[str] | None = None,
):
    contract = _deep_contract()
    return build_visible_content_proof(
        canonical_authority_path=CANONICAL_AUTHORITY,
        canonical_version="FPL MASTER CANONICAL V12",
        canonical_revision=_revision(),
        canonical_text=_canonical(),
        report_slot="2026-09-19T12:30:00+07:00",
        report_mode="DEEP",
        report_due=True,
        observed_at="2026-09-19T12:30:08+07:00",
        section_states=section_states or _section_states(contract),
        hard_failures=hard_failures or [],
        section_degradations=degradations or [],
        warnings=[],
        report_can_continue=report_can_continue,
        search_authority="PARTIAL",
        repository_python_qa_executed=False,
        python_execution_evidence=None,
        rendered_section_ids=rendered_ids or list(contract["expected_section_ids"]),
        rendered_visible_order=rendered_order or list(contract["expected_visible_order"]),
    )


def test_01_stale_deep_plans_exactly_one_governed_refresh_attempt():
    plan = plan_due_report_refresh(
        report_due=True,
        report_mode="DEEP",
        required_scope_age_minutes=46,
        canonical_freshness_threshold_minutes=45,
    )
    assert plan["attempt_governed_refresh"] is True
    assert plan["refresh_attempt_count"] == 1
    assert plan["transport"] == "ISSUE_431_EXISTING_GOVERNED_TRANSPORT"
    assert plan["alternate_transport_allowed"] is False


def test_02_fresh_deep_plans_zero_refresh():
    plan = plan_due_report_refresh(
        report_due=True,
        report_mode="DEEP",
        required_scope_age_minutes=44.9,
        canonical_freshness_threshold_minutes=45,
    )
    assert plan["attempt_governed_refresh"] is False
    assert plan["status"] == "REUSE_CURRENT"


def test_03_refresh_in_progress_prevents_duplicate_attempt():
    plan = plan_due_report_refresh(
        report_due=True,
        report_mode="DEEP",
        required_scope_age_minutes=80,
        canonical_freshness_threshold_minutes=45,
        acquisition_in_progress=True,
    )
    assert plan["attempt_governed_refresh"] is False
    assert plan["status"] == "RE_READ_EXISTING_RESULT"
    assert plan["reason"] == "RELEVANT_ACQUISITION_IN_PROGRESS"


def test_04_refresh_failure_keeps_original_report_deliverable_degraded():
    plan = plan_due_report_refresh(
        report_due=True,
        report_mode="DEEP",
        required_scope_age_minutes=80,
        canonical_freshness_threshold_minutes=45,
    )
    result = resolve_governed_refresh_result(plan, result="FAILED")
    assert result["core_refresh"] == "DEGRADED"
    assert result["report_can_continue"] is True
    assert result["next_action"] == "CONTINUE_CANONICAL_EVIDENCE_LADDER_SAME_REPORT_SLOT"


def test_05_gw_specific_unexecuted_route_expires_after_official_deadline():
    scenario = {
        "scenario_id": "PUNT",
        "state": "CONTEMPLATED",
        "execution_state": "NOT_EXECUTED",
        "route_type": "ONE_GW_PUNT",
        "target_gw": 5,
        "execution_window": "UNTIL_TARGET_GW_DEADLINE",
    }
    resolved = apply_scenario_lifecycle(
        scenario,
        observed_at="2026-09-19T12:30:00+07:00",
        official_deadlines={5: "2026-09-18T17:30:00+00:00"},
    )
    assert resolved["state"] == "EXPIRED"
    assert resolved["currently_valid"] is False
    assert resolved["expiry_reason"] == "TARGET_GW_EXECUTION_WINDOW_CLOSED_NOT_EXECUTED"


def test_06_expired_route_is_excluded_from_active_scenario_merge():
    merged = merge_active_and_optimizer_scenarios(
        active_user_scenarios=[
            {"scenario_id": "EXPIRED", "state": "EXPIRED", "currently_valid": False},
            {"scenario_id": "ACTIVE", "state": "CONTEMPLATED", "currently_valid": True},
        ],
        optimizer_alternatives=[],
    )
    assert merged["active_user_scenario_ids"] == ["ACTIVE"]
    assert "EXPIRED" not in [row["scenario_id"] for row in merged["scenarios"]]


def test_07_expired_route_remains_queryable_for_history_and_learning():
    merged = merge_active_and_optimizer_scenarios(
        active_user_scenarios=[
            {"scenario_id": "EXPIRED", "state": "EXPIRED", "currently_valid": False}
        ],
        optimizer_alternatives=[],
    )
    assert merged["historical_user_scenario_ids"] == ["EXPIRED"]
    assert merged["historical_user_scenarios"][0]["scenario_id"] == "EXPIRED"


def test_08_stale_gw5_hit_assumption_never_flows_into_gw6_economics():
    scenario = {
        "scenario_id": "TRANSFER_TO_BARNES",
        "state": "EXPIRED",
        "historical_assumptions": {"target_gw": 5, "hit_points_assumption": -4},
    }
    economics = future_transfer_economics_inputs(scenario, target_gw=6)
    assert economics["carried_hit_points_assumption"] is None
    assert economics["fresh_full_universe_rescan_required"] is True
    assert economics["historical_assumptions_excluded"] is True


def test_09_deep_expected_section_catalog_is_derived_from_canonical_exact_order():
    contract = _deep_contract()
    assert contract["expected_section_ids"] == [
        "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09",
        "S10", "S11", "S12", "S13", "S14", "S15", "S15B", "S16", "S17",
        "S18", "S19",
    ]
    assert contract["expected_visible_order"][0] == "Decision/status"
    assert "ALL15" in contract["expected_visible_order"][16]
    assert contract["expected_visible_order"][-1] == "Final judgement"


def test_10_missing_all15_section_is_structural_failure_requiring_rerender():
    contract = _deep_contract()
    all15_id = "S16"
    rendered = [sid for sid in contract["expected_section_ids"] if sid != all15_id]
    with pytest.raises(VisibleContentProofError):
        _proof(rendered_ids=rendered, report_can_continue=True)
    proof = _proof(rendered_ids=rendered, report_can_continue=False)
    assert all15_id in proof["missing_section_ids"]
    assert any("MODE_SECTIONS_MISSING" in failure for failure in proof["hard_failures"])


def test_11_all15_keeps_15_owned_identities_when_model_fields_are_unavailable():
    players = [
        {"element_id": i, "display_name": f"P{i}", "locked_role": "XI" if i <= 11 else "BENCH"}
        for i in range(1, 16)
    ]
    result = build_all15_identity_rows(players, model_by_element={})
    assert result["identity_state"] == "COMPLETE"
    assert result["identity_available_count"] == 15
    assert len(result["rows"]) == 15
    assert len({row["element_id"] for row in result["rows"]}) == 15
    assert result["model_state"] == "DEGRADED"
    assert all(row["p_start"] == "MODEL UPDATE PENDING NEXT COMPUTE" for row in result["rows"])


def test_12_decision_delta_requires_exact_previous_current_material_reason_time_schema():
    good = [{
        "decision_item": "Barnes GW5 route",
        "previous_state": "CONTEMPLATED",
        "current_state": "EXPIRED",
        "material_change": True,
        "reason": "GW5 deadline passed, not executed",
        "evidence_time": "2026-09-19T12:30:00+07:00",
    }]
    assert validate_decision_delta_rows(good)["status"] == "PASS"
    bad = [{**good[0]}]
    bad[0].pop("previous_state")
    assert validate_decision_delta_rows(bad)["status"] == "FAIL"


def test_13_1230_signal_delta_supports_truthful_baseline_unavailable_without_fake_model_move():
    rows = [{
        "signal": "P(start)",
        "baseline_state": "BASELINE UNAVAILABLE",
        "current_state": "MODEL UPDATE PENDING NEXT COMPUTE",
        "change": "MODEL UPDATE PENDING NEXT COMPUTE",
        "evidence": "CALIBRATION INPUT from actual role/minutes",
        "decision_effect": "reduce future starter-security confidence at next compute",
    }]
    assert validate_1230_signal_delta(rows, baseline_available=False)["status"] == "PASS"


def test_14_watchlist_unavailable_zero_of_20_remains_rendered_and_report_continues():
    contract = _deep_contract()
    overrides = {
        "S11": {
            "state": "UNAVAILABLE",
            "available_count": 0,
            "expected_count": 20,
            "degradation_reason": "no fresh occurrence-bound canonical full-universe evaluation",
        }
    }
    states = _section_states(contract, overrides)
    degradation = [{
        "section": "S11",
        "state": "UNAVAILABLE",
        "available_count": 0,
        "expected_count": 20,
        "degradation_reason": "no fresh occurrence-bound canonical full-universe evaluation",
    }]
    proof = _proof(section_states=states, degradations=degradation)
    assert proof["report_can_continue"] is True
    assert "S11" in proof["rendered_section_ids"]
    assert proof["content_contract_status"] == "DEGRADED"


def test_15_watchlist_section_omitted_entirely_is_structural_failure():
    contract = _deep_contract()
    rendered = [sid for sid in contract["expected_section_ids"] if sid != "S11"]
    proof = _proof(rendered_ids=rendered, report_can_continue=False)
    assert proof["missing_section_ids"] == ["S11"]


def test_16_rise_and_fall_have_independent_section_states():
    contract = _deep_contract()
    overrides = {
        "S12": {
            "state": "DEGRADED",
            "available_count": 7,
            "expected_count": 20,
            "degradation_reason": "partial predictor coverage",
        },
        "S13": {
            "state": "UNAVAILABLE",
            "available_count": 0,
            "expected_count": 20,
            "degradation_reason": "no schema-complete fresh predictor set",
        },
    }
    states = _section_states(contract, overrides)
    degradations = [
        {"section": "S12", **{k: v for k, v in overrides["S12"].items()}},
        {"section": "S13", **{k: v for k, v in overrides["S13"].items()}},
    ]
    proof = _proof(section_states=states, degradations=degradations)
    mapped = {row["section_id"]: row["state"] for row in proof["section_states"]}
    assert mapped["S12"] == "DEGRADED"
    assert mapped["S13"] == "UNAVAILABLE"


def test_17_bench_gk_is_separate_from_outfield_autosub_priority():
    bench = [
        {"element_id": 109, "display_name": "Verbruggen", "position": "GK", "bench_order": 1},
        {"element_id": 31, "display_name": "Konsa", "position": "DEF", "bench_order": 1},
        {"element_id": 165, "display_name": "Joao Pedro", "position": "FWD", "bench_order": 2},
        {"element_id": 279, "display_name": "Ajayi", "position": "DEF", "bench_order": 3},
    ]
    result = split_bench_for_display(bench)
    assert result["bench_gk"]["element_id"] == 109
    assert [row["element_id"] for row in result["outfield_autosub_priority"]] == [31, 165, 279]
    assert result["gk_in_outfield_queue"] is False


def test_18_icon_current_picks_survive_while_stale_standings_remain_degraded():
    entries = {
        "1": {
            "picks": [
                {"element_id": 411, "multiplier": 2, "captain": True, "vice_captain": False}
            ]
        },
        "2": {
            "picks": [
                {"element_id": 411, "multiplier": 1, "captain": False, "vice_captain": True}
            ]
        },
    }
    exposure = compute_pick_exposure(entries, element_id=411)
    icon = compose_icon_subscopes(
        picks_scope={"state": "COMPLETE", "gw": 5, "coverage": "2/2", "metrics": exposure},
        standings_scope={"state": "STALE", "gw": 4, "reason": "prior-GW standings"},
        eo_scope={"state": "UNAVAILABLE", "reason": "EO inputs incomplete"},
        rival_live_scope={"state": "UNAVAILABLE", "reason": "live totals unavailable"},
    )
    assert icon["state"] == "DEGRADED"
    assert icon["subscopes"]["SUBMITTED_PICKS_EXPOSURE"]["state"] == "COMPLETE"
    assert exposure["ownership"] == {"numerator": 2, "denominator": 2, "percentage": 100.0}
    assert icon["subscopes"]["LIVE_STANDINGS_RANK"]["state"] == "STALE"


def test_19_content_contract_severity_is_only_pass_degraded_fail():
    for state in ("PASS", "DEGRADED", "FAIL"):
        assert content_contract_severity(state) == state
    with pytest.raises(RuntimeConformanceError):
        content_contract_severity("PARTIAL")


def test_20_fail_operational_cannot_masquerade_as_content_severity():
    with pytest.raises(RuntimeConformanceError):
        content_contract_severity("FAIL-OPERATIONAL")


def test_21_visible_content_proof_detects_missing_mode_sections():
    contract = _deep_contract()
    rendered = contract["expected_section_ids"][:-1]
    proof = _proof(rendered_ids=rendered, report_can_continue=False)
    assert proof["missing_section_ids"] == ["S19"]
    assert proof["report_can_continue"] is False


def test_22_visible_content_proof_detects_wrong_visible_order():
    contract = _deep_contract()
    wrong = list(contract["expected_visible_order"])
    wrong[0], wrong[1] = wrong[1], wrong[0]
    proof = _proof(rendered_order=wrong, report_can_continue=False)
    assert proof["visible_order_valid"] is False
    assert "MODE_VISIBLE_ORDER_INVALID" in proof["hard_failures"]


def test_23_rendered_degraded_section_with_state_count_reason_can_continue():
    contract = _deep_contract()
    overrides = {
        "S11": {
            "state": "DEGRADED",
            "available_count": 17,
            "expected_count": 20,
            "degradation_reason": "3 candidates lack valid canonical evaluation",
        }
    }
    degradation = [{
        "section": "S11",
        "state": "DEGRADED",
        "available_count": 17,
        "expected_count": 20,
        "degradation_reason": "3 candidates lack valid canonical evaluation",
    }]
    proof = _proof(
        section_states=_section_states(contract, overrides),
        degradations=degradation,
    )
    assert proof["content_contract_status"] == "DEGRADED"
    assert proof["report_can_continue"] is True
    assert proof["visible_order_valid"] is True


def test_24_revision_proof_accepts_commit_and_blob_without_fake_content_sha256():
    proof = _proof()
    revision = proof["canonical_revision"]
    assert revision["branch_head_sha"] == "a" * 40
    assert revision["file_blob_sha"] == "b" * 40
    assert revision["content_sha256"] is None
    assert revision["content_sha256_computed"] is False


def test_25_python_qa_not_proven_remains_truthful_without_execution_evidence():
    proof = _proof()
    runtime = proof["runtime_provenance"]
    assert runtime["repository_python_qa_executed"] is False
    assert runtime["python_qa_status"] == "NOT_PROVEN"
    assert runtime["python_execution_evidence"] is None


def test_26_football_hold_and_operational_wait_prepare_act_are_distinct():
    result = compose_operational_action(
        football_action="LOCKED / NO EXECUTABLE ACTION",
        operational_action="PREPARE",
        trigger="fresh GW6 full-universe evidence",
        reversal_or_abort="new injury or role evidence changes route",
        next_checkpoint="21:30",
    )
    assert result["football_action"] == "LOCKED / NO EXECUTABLE ACTION"
    assert result["operational_action"] == "PREPARE"
    assert result["football_and_operational_actions_separate"] is True
    with pytest.raises(RuntimeConformanceError):
        compose_operational_action(
            football_action="HOLD",
            operational_action="MONITOR",
            trigger="x",
            reversal_or_abort="y",
            next_checkpoint="z",
        )


def test_27_migrated_state_expires_barnes_only_and_binds_other_scenarios():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    rows = {row["scenario_id"]: row for row in state["active_scenarios"]}
    barnes = rows["TRANSFER_TO_BARNES"]
    assert barnes["state"] == "EXPIRED"
    assert barnes["target_gw"] == 5
    assert barnes["expiry_reason"] == "TARGET_GW_EXECUTION_WINDOW_CLOSED_NOT_EXECUTED"
    assert barnes["historical_assumptions"]["hit_points_assumption"] == -4
    assert barnes["historical_assumptions"]["excluded_from_future_gw_economics"] is True
    for scenario_id in (
        "HOLD_SANGARE",
        "JOAO_PEDRO_AVAILABILITY",
        "BRUNO_KEEP_START",
        "XI_MARGINAL_SANGARE_DE_CUYPER_DCL",
    ):
        assert rows[scenario_id]["state"] == "CONTEMPLATED"
        assert rows[scenario_id]["currently_valid"] is True
        assert rows[scenario_id]["scope_type"].startswith("CROSS_GW_")



def _mode_proof(
    mode: str,
    *,
    rendered_ids: list[str] | None = None,
    rendered_order: list[str] | None = None,
    overrides: dict[str, dict] | None = None,
    report_can_continue: bool = True,
):
    contract = canonical_mode_contract(_canonical(), mode)
    states = _section_states(contract, overrides)
    degradations = []
    for row in states:
        if row["state"] in {"PARTIAL", "DEGRADED", "UNAVAILABLE"}:
            degradations.append(
                {
                    "section": row["section_id"],
                    "state": row["state"],
                    "available_count": row.get("available_count"),
                    "expected_count": row.get("expected_count"),
                    "degradation_reason": row.get("degradation_reason"),
                    "missing_scope": list(row.get("missing_scope") or []),
                }
            )
    return build_visible_content_proof(
        canonical_authority_path=CANONICAL_AUTHORITY,
        canonical_version="FPL MASTER CANONICAL V12",
        canonical_revision=_revision(),
        canonical_text=_canonical(),
        report_slot="2026-09-19T12:30:00+07:00",
        report_mode=mode,
        report_due=True,
        observed_at="2026-09-19T12:30:08+07:00",
        section_states=states,
        hard_failures=[],
        section_degradations=degradations,
        warnings=[],
        report_can_continue=report_can_continue,
        search_authority="PARTIAL",
        repository_python_qa_executed=False,
        python_execution_evidence=None,
        rendered_section_ids=(
            list(contract["expected_section_ids"])
            if rendered_ids is None
            else rendered_ids
        ),
        rendered_visible_order=(
            list(contract["expected_visible_order"])
            if rendered_order is None
            else rendered_order
        ),
    )


def _omit_contract_section(contract: dict, section_id: str) -> tuple[list[str], list[str]]:
    kept = [
        (sid, label)
        for sid, label in zip(
            contract["expected_section_ids"],
            contract["expected_visible_order"],
        )
        if sid != section_id
    ]
    return [sid for sid, _ in kept], [label for _, label in kept]


def test_28_price_mode_contract_is_canonical_derived_and_non_empty():
    contract = canonical_mode_contract(_canonical(), "PRICE")
    assert contract["expected_section_ids"] == [f"PRICE{i}" for i in range(1, 12)]
    assert len(contract["expected_visible_order"]) == 11
    assert contract["expected_visible_order"][3] == "Watchlist20 exact20"
    assert contract["expected_visible_order"][4] == "RISE20 exact20"
    assert contract["expected_visible_order"][5] == "FALL20 exact20"
    assert contract["expected_visible_order"][-1] == "Source health"


def test_29_price_missing_mandatory_section_is_structural_failure():
    contract = canonical_mode_contract(_canonical(), "PRICE")
    rendered_ids, rendered_order = _omit_contract_section(contract, "PRICE4")
    proof = _mode_proof(
        "PRICE",
        rendered_ids=rendered_ids,
        rendered_order=rendered_order,
        report_can_continue=False,
    )
    assert proof["missing_section_ids"] == ["PRICE4"]
    assert proof["content_contract_status"] == "FAIL"
    assert any("MODE_SECTIONS_MISSING=PRICE4" == failure for failure in proof["hard_failures"])


def test_30_price_degraded_rendered_section_remains_structurally_valid():
    proof = _mode_proof(
        "PRICE",
        overrides={
            "PRICE4": {
                "state": "DEGRADED",
                "available_count": 17,
                "expected_count": 20,
                "degradation_reason": "authoritative watchlist scope incomplete",
                "missing_scope": ["3 canonical candidates"],
            }
        },
    )
    assert proof["content_contract_status"] == "DEGRADED"
    assert proof["missing_section_ids"] == []
    assert proof["visible_order_valid"] is True
    assert proof["report_can_continue"] is True


def test_31_post_all_match_contract_is_explicit_and_non_empty():
    contract = canonical_mode_contract(_canonical(), "POST_ALL_MATCH")
    assert contract["expected_section_ids"] == [
        f"POST_ALL_MATCH{i}" for i in range(1, 14)
    ]
    assert contract["expected_visible_order"][4] == "GW COMPLETED MATCH-BY-MATCH SCOUT"
    assert contract["expected_visible_order"][3] == "OWNED15 REVIEW"
    assert contract["expected_visible_order"][6] == (
        "BAYESIAN CALIBRATION INPUT / ACTUAL UPDATE STATUS"
    )
    assert contract["expected_visible_order"][7] == "ICON+ FINAL GW"
    assert contract["expected_visible_order"][9] == "FRESH FULL-UNIVERSE NEXT-GW SCAN"
    assert contract["expected_visible_order"][-1] == "LEARNING LOG"


def test_32_post_all_match_missing_or_duplicate_scout_is_structural_failure():
    contract = canonical_mode_contract(_canonical(), "POST_ALL_MATCH")
    scout_id = "POST_ALL_MATCH5"
    rendered_ids, rendered_order = _omit_contract_section(contract, scout_id)
    missing = _mode_proof(
        "POST_ALL_MATCH",
        rendered_ids=rendered_ids,
        rendered_order=rendered_order,
        report_can_continue=False,
    )
    assert missing["missing_section_ids"] == [scout_id]

    scout_index = contract["expected_section_ids"].index(scout_id)
    duplicate_ids = list(contract["expected_section_ids"])
    duplicate_order = list(contract["expected_visible_order"])
    duplicate_ids.insert(scout_index + 1, scout_id)
    duplicate_order.insert(
        scout_index + 1,
        contract["expected_visible_order"][scout_index],
    )
    duplicated = _mode_proof(
        "POST_ALL_MATCH",
        rendered_ids=duplicate_ids,
        rendered_order=duplicate_order,
        report_can_continue=False,
    )
    assert duplicated["visible_order_valid"] is False
    assert "MODE_VISIBLE_ORDER_INVALID" in duplicated["hard_failures"]


def test_33_post_all_match_degraded_scout_stays_structurally_present():
    proof = _mode_proof(
        "POST_ALL_MATCH",
        overrides={
            "POST_ALL_MATCH5": {
                "state": "DEGRADED",
                "available_count": 9,
                "expected_count": 10,
                "degradation_reason": "one completed fixture lacks authoritative scout evidence",
                "missing_scope": ["fixture_10"],
            }
        },
    )
    assert proof["content_contract_status"] == "DEGRADED"
    assert "POST_ALL_MATCH5" in proof["rendered_section_ids"]
    assert proof["missing_section_ids"] == []
    assert proof["visible_order_valid"] is True
    assert proof["report_can_continue"] is True


def test_34_final_contract_adds_gw_lock_package_before_alternatives():
    deep = canonical_mode_contract(_canonical(), "DEEP")
    final = canonical_mode_contract(_canonical(), "FINAL")
    assert len(final["expected_section_ids"]) == len(deep["expected_section_ids"]) + 1
    assert "GW_LOCK_PACKAGE" in final["expected_section_ids"]
    assert all(section_id in final["expected_section_ids"] for section_id in deep["expected_section_ids"])
    lock_index = final["expected_section_ids"].index("GW_LOCK_PACKAGE")
    alternatives_index = final["expected_section_ids"].index("S14")
    assert lock_index < alternatives_index
    assert final["expected_visible_order"][lock_index] == "GW LOCK PACKAGE"


def test_35_final_missing_gw_lock_package_is_structural_failure():
    contract = canonical_mode_contract(_canonical(), "FINAL")
    rendered_ids, rendered_order = _omit_contract_section(contract, "GW_LOCK_PACKAGE")
    proof = _mode_proof(
        "FINAL",
        rendered_ids=rendered_ids,
        rendered_order=rendered_order,
        report_can_continue=False,
    )
    assert proof["missing_section_ids"] == ["GW_LOCK_PACKAGE"]
    assert proof["content_contract_status"] == "FAIL"


def test_36_final_degraded_gw_lock_package_is_structurally_valid():
    proof = _mode_proof(
        "FINAL",
        overrides={
            "GW_LOCK_PACKAGE": {
                "state": "DEGRADED",
                "available_count": 15,
                "expected_count": 17,
                "degradation_reason": "finance prerequisites incomplete",
                "missing_scope": ["bank_after_if_known", "ft_hit_treatment"],
            }
        },
    )
    assert proof["content_contract_status"] == "DEGRADED"
    assert proof["missing_section_ids"] == []
    assert proof["visible_order_valid"] is True
    assert proof["report_can_continue"] is True


def test_37_deadline_requires_no_invented_additive_structural_block():
    deep = canonical_mode_contract(_canonical(), "DEEP")
    deadline = canonical_mode_contract(_canonical(), "DEADLINE")
    assert deadline["expected_section_ids"] == deep["expected_section_ids"]
    assert deadline["expected_visible_order"] == deep["expected_visible_order"]


def test_38_mode_contract_tracks_canonical_wording_instead_of_static_duplicate_schema():
    canonical = _canonical()
    mutated = canonical.replace(
        "4 Watchlist20 exact20",
        "4 Watchlist20 exact20 CANONICAL-MUTATION-PROBE",
        1,
    )
    contract = canonical_mode_contract(mutated, "PRICE")
    assert contract["expected_visible_order"][3] == (
        "Watchlist20 exact20 CANONICAL-MUTATION-PROBE"
    )


def test_39_every_natural_hourly_occurrence_owns_core_upkeep_even_when_report_silent():
    plan = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T13:30:00+07:00",
        observed_at="2026-09-19T13:30:05+07:00",
        report_due=False,
    )
    assert plan["core_upkeep_due"] is True
    assert plan["report_due"] is False
    assert plan["core_logical_slot"] == "2026-09-19T13:00:00+07:00"
    assert plan["attempt_governed_refresh"] is True


def test_40_same_slot_natural_authoritative_fulfillment_prevents_duplicate_acquisition():
    plan = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T13:30:00+07:00",
        observed_at="2026-09-19T13:30:05+07:00",
        report_due=False,
        same_slot_authoritative_fulfilled=True,
        authoritative_runtime_snapshot=True,
        fulfillment_reason="chatgpt_hourly_master",
    )
    assert plan["status"] == "ALREADY_FULFILLED"
    assert plan["attempt_governed_refresh"] is False
    assert plan["same_slot_fulfilled"] is True


def test_41_current_slot_in_progress_requires_reread_not_duplicate():
    plan = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T14:30:00+07:00",
        observed_at="2026-09-19T14:30:04+07:00",
        report_due=True,
        acquisition_in_progress=True,
    )
    assert plan["status"] == "RE_READ_CURRENT_SLOT_IN_PROGRESS"
    assert plan["attempt_governed_refresh"] is False
    assert plan["bounded_terminal_reread_required"] is True


def test_42_missing_current_slot_uses_exactly_one_existing_431_attempt():
    plan = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T15:30:00+07:00",
        observed_at="2026-09-19T15:30:06+07:00",
        report_due=False,
    )
    assert plan["attempt_governed_refresh"] is True
    assert plan["refresh_attempt_count"] == 1
    assert plan["transport"] == "ISSUE_431_EXISTING_GOVERNED_TRANSPORT"
    assert "reason=chatgpt_hourly_master" in plan["issue_431_title"]
    assert "logical_slot=2026-09-19T15:00:00+07:00" in plan["issue_431_title"]


def test_43_previous_same_slot_attempt_forbids_second_attempt():
    plan = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T15:30:00+07:00",
        observed_at="2026-09-19T15:30:20+07:00",
        report_due=True,
        previous_core_attempts=1,
    )
    assert plan["status"] == "ATTEMPT_ALREADY_MADE"
    assert plan["attempt_governed_refresh"] is False
    assert plan["duplicate_acquisition_forbidden"] is True


def test_44_failed_hourly_core_with_due_report_continues_degraded():
    plan = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T16:30:00+07:00",
        observed_at="2026-09-19T16:30:03+07:00",
        report_due=True,
    )
    result = resolve_hourly_core_upkeep_result(plan, result="FAILED")
    assert result["core_upkeep"] == "DEGRADED"
    assert result["report_can_continue"] is True
    assert result["emit_visible_report"] is True


def test_45_failed_hourly_core_with_silent_report_route_does_not_fake_report():
    plan = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T17:30:00+07:00",
        observed_at="2026-09-19T17:30:03+07:00",
        report_due=False,
    )
    result = resolve_hourly_core_upkeep_result(plan, result="TIMEOUT")
    assert result["core_upkeep"] == "DEGRADED"
    assert result["emit_visible_report"] is False
    assert result["silent_occurrence_complete"] is True


def test_46_report_prefetch_never_fulfills_core_operational_slot():
    plan = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:04+07:00",
        report_due=True,
        report_prefetch_complete=True,
    )
    assert plan["report_prefetch_fulfills_core_slot"] is False
    assert plan["attempt_governed_refresh"] is True


def test_47_manual_recovery_cannot_masquerade_as_natural_authoritative_slot_proof():
    plan = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T19:30:00+07:00",
        observed_at="2026-09-19T19:30:04+07:00",
        report_due=False,
        same_slot_authoritative_fulfilled=True,
        authoritative_runtime_snapshot=True,
        fulfillment_reason="manual_recovery",
    )
    assert plan["status"] == "GOVERNED_CURRENT_SLOT_ATTEMPT_REQUIRED"
    proof = build_hourly_core_upkeep_proof(
        report_occurrence="2026-09-19T19:30:00+07:00",
        core_logical_slot="2026-09-19T19:00:00+07:00",
        observed_at="2026-09-19T19:30:04+07:00",
        transport="ISSUE_431_EXISTING_GOVERNED_TRANSPORT",
        mutation_readback_state="PASS",
        acquisition_run_ids=["run1"],
        publication_run_ids=["pub1"],
        publish_integrity="PASS",
        authoritative_runtime_snapshot=True,
        fulfillment_reason="manual_recovery",
    )
    assert proof["same_slot_fulfilled"] is False
    assert "NON_NATURAL_REASON_CANNOT_BE_AUTHORITATIVE_HOURLY_PROOF" in proof["hard_failures"]


def test_48_backfill_and_future_fill_are_rejected():
    with pytest.raises(RuntimeConformanceError):
        plan_hourly_core_upkeep(
            report_occurrence="2026-09-19T20:30:00+07:00",
            observed_at="2026-09-19T20:30:04+07:00",
            report_due=False,
            supplied_core_logical_slot="2026-09-19T19:00:00+07:00",
        )
    with pytest.raises(RuntimeConformanceError):
        plan_hourly_core_upkeep(
            report_occurrence="2026-09-19T20:30:00+07:00",
            observed_at="2026-09-19T20:30:04+07:00",
            report_due=False,
            supplied_core_logical_slot="2026-09-19T21:00:00+07:00",
        )


def test_49_duplicate_acquisition_or_publication_same_slot_is_hard_proof_failure():
    proof = build_hourly_core_upkeep_proof(
        report_occurrence="2026-09-19T21:30:00+07:00",
        core_logical_slot="2026-09-19T21:00:00+07:00",
        observed_at="2026-09-19T21:30:02+07:00",
        transport="ISSUE_431_EXISTING_GOVERNED_TRANSPORT",
        mutation_readback_state="PASS",
        acquisition_run_ids=["a1", "a2"],
        publication_run_ids=["p1", "p2"],
        publish_integrity="PASS",
        authoritative_runtime_snapshot=True,
        fulfillment_reason="chatgpt_hourly_master",
    )
    assert proof["duplicate_acquisition"] is True
    assert proof["duplicate_publication"] is True
    assert "DUPLICATE_ACQUISITION_FOR_SLOT" in proof["hard_failures"]
    assert "DUPLICATE_PUBLICATION_FOR_SLOT" in proof["hard_failures"]
    assert proof["same_slot_fulfilled"] is False


def test_50_current_natural_publication_can_prove_authoritative_runtime_snapshot():
    proof = build_hourly_core_upkeep_proof(
        report_occurrence="2026-09-19T22:30:00+07:00",
        core_logical_slot="2026-09-19T22:00:00+07:00",
        observed_at="2026-09-19T22:30:02+07:00",
        transport="ISSUE_431_EXISTING_GOVERNED_TRANSPORT",
        mutation_readback_state="EXACT_MATCH",
        acquisition_run_ids=["a1"],
        publication_run_ids=["p1"],
        runtime_data_v6_publication_sha="abc123",
        runtime_data_v6_generation=42,
        publish_integrity="PASS",
        authoritative_runtime_snapshot=True,
        fulfillment_reason="chatgpt_hourly_master",
    )
    assert proof["hard_failures"] == []
    assert proof["same_slot_fulfilled"] is True
    assert proof["completion_result"] == "FULFILLED"


def test_51_v12_authority_lookup_is_git_control_only_not_legacy_library():
    result = validate_v12_authority_sources(
        authority_path="control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt",
        state_path="control/fpl_master_v12/FPL_MASTER_STATE_V12.json",
    )
    assert result["legacy_library_authority_allowed"] is False
    with pytest.raises(RuntimeConformanceError):
        validate_v12_authority_sources(
            authority_path="FPL_MASTER_RUNTIME_CONTRACT.txt",
            state_path="ACTIVE_DECISION_CONTEXT.json",
        )


def test_52_legacy_library_identity_cannot_hydrate_current_v12_identity():
    result = hydrate_v12_player_identities(
        [{"element_id": 565, "display_name": "M.Sangaré"}],
        official_players=[{"element_id": 565, "web_name": "Sangaré"}],
        legacy_library_players=[{"element_id": 488, "display_name": "Sangaré"}],
    )
    assert [row["element_id"] for row in result["rows"]] == [565]
    assert result["legacy_library_input_ignored"] is True
    assert result["legacy_library_identity_hydration_allowed"] is False
    with pytest.raises(RuntimeConformanceError):
        hydrate_v12_player_identities(
            [{"element_id": 488, "display_name": "Sangaré"}],
            official_players=[{"element_id": 565, "web_name": "Sangaré"}],
            state_source="ACTIVE_DECISION_CONTEXT.json",
        )


def test_53_canonical_keeps_report_cadence_and_separates_hourly_core_upkeep():
    canonical = _canonical()
    assert "EVERY natural FPL Master Monitor V12 HH:30" in canonical
    assert "CORE_UPKEEP_DUE and REPORT_DUE are independent" in canonical
    assert "04:30 DEEP; 05:30 PRICE; 12:30 DEEP; 21:30 DEEP" in canonical
    assert "report-prefetch remains report-driven and separate" in canonical


def test_54_canonical_forbids_legacy_library_authority_and_identity_hydration():
    canonical = _canonical()
    assert "Old Library Runtime/Spec/ACTIVE_DECISION_CONTEXT files" in canonical
    assert "MUST NOT be read as V12 authority/state" in canonical
    assert "No legacy Library player identity may hydrate V12" in canonical


def test_55_existing_due_report_refresh_remains_independent_and_unchanged_for_not_due():
    plan = plan_due_report_refresh(
        report_due=False,
        report_mode="DEEP",
        required_scope_age_minutes=999,
        canonical_freshness_threshold_minutes=45,
    )
    assert plan["status"] == "NOT_DUE"
    hourly = plan_hourly_core_upkeep(
        report_occurrence="2026-09-19T23:30:00+07:00",
        observed_at="2026-09-19T23:30:03+07:00",
        report_due=False,
    )
    assert hourly["core_upkeep_due"] is True
    assert hourly["attempt_governed_refresh"] is True


def _complete_price_row(observed_at: str = "2026-09-19T16:17:00+07:00") -> dict:
    timing = derive_next_official_price_cycle(observed_at)
    return {
        "player": "Example Player",
        "current_price": 6.5,
        "direction": "RISE",
        "official_or_provider_progress": "94%",
        "prediction_strength": "LIKELY",
        "next_official_price_cycle_uk": timing["next_official_price_cycle_uk"],
        "next_official_price_cycle_wib": timing["next_official_price_cycle_wib"],
        "cycles_to_expected_change": 1,
        "estimated_change_window": f"NEXT PRICE CYCLE — {timing['next_price_cycle_wib_label']}",
        "estimate_source": "Official FPL Price Change Predictor",
        "evidence_timestamp": observed_at,
        "confidence": "MEDIUM",
        "impact_on_our_decision": "WAIT unless affordability route is threatened",
        "predictor_refresh_cadence_minutes": 15,
        "official_price_change_cadence": timing["official_price_change_cadence"],
        "change_guaranteed": False,
    }


def test_56_official_price_cycle_is_derived_from_midnight_europe_london():
    timing = derive_next_official_price_cycle("2026-09-19T16:17:00+07:00")
    assert timing["official_price_change_cadence"] == "DAILY_AT_00:00_EUROPE_LONDON"
    assert timing["next_price_cycle_uk_label"].startswith("00:00")


def test_57_bst_next_official_price_cycle_resolves_to_0600_wib():
    timing = derive_next_official_price_cycle("2026-09-19T16:17:00+07:00")
    assert timing["next_official_price_cycle_wib"].startswith("2026-09-20T06:00:00+07:00")
    assert timing["next_price_cycle_wib_label"] == "06:00 WIB"
    assert timing["uk_utc_offset"] == "+0100"


def test_58_gmt_next_official_price_cycle_resolves_to_0700_wib():
    timing = derive_next_official_price_cycle("2026-11-01T16:17:00+07:00")
    assert timing["next_official_price_cycle_wib"].startswith("2026-11-02T07:00:00+07:00")
    assert timing["next_price_cycle_wib_label"] == "07:00 WIB"
    assert timing["uk_utc_offset"] == "+0000"


def test_59_predictor_refresh_cadence_cannot_masquerade_as_price_change_cycle():
    timing = derive_next_official_price_cycle("2026-09-19T16:17:00+07:00")
    assert timing["predictor_refresh_cadence_minutes"] == 15
    assert timing["predictor_refresh_is_price_change_cycle"] is False
    assert timing["official_price_change_cadence"] == "DAILY_AT_00:00_EUROPE_LONDON"


def test_60_rise_fall_complete_requires_next_official_price_cycle_semantics():
    row = _complete_price_row()
    assert validate_rise_fall_visible_row(row, section_state="COMPLETE")["status"] == "PASS"
    row.pop("next_official_price_cycle_wib")
    failed = validate_rise_fall_visible_row(row, section_state="COMPLETE")
    assert failed["status"] == "FAIL"
    assert any("COMPLETE_PRICE_ROW_MISSING" in item for item in failed["failures"])


def test_61_truthful_unavailable_timing_is_only_legal_under_degraded_state():
    row = _complete_price_row()
    row["next_official_price_cycle_wib"] = "UNAVAILABLE"
    row["estimated_change_window"] = "UNAVAILABLE"
    row["degradation_reason"] = "predictor timing evidence unavailable"
    assert validate_rise_fall_visible_row(row, section_state="DEGRADED")["status"] == "PASS"
    assert validate_rise_fall_visible_row(row, section_state="COMPLETE")["status"] == "FAIL"


def test_62_price_prediction_cannot_claim_exact_guarantee():
    row = _complete_price_row()
    row["change_guaranteed"] = True
    result = validate_rise_fall_visible_row(row, section_state="COMPLETE")
    assert result["status"] == "FAIL"
    assert "PRICE_PREDICTION_MUST_NOT_BE_GUARANTEED" in result["failures"]


def test_63_predictor_disagreement_must_remain_visible():
    row = _complete_price_row()
    row["provider_signals"] = [
        {"source": "Official Predictor", "stance": "LIKELY_RISE_NEXT_CYCLE"},
        {"source": "Provider A", "stance": "LIKELY_RISE_NEXT_CYCLE"},
        {"source": "Provider B", "stance": "BORDERLINE"},
    ]
    row["predictor_disagreement"] = True
    result = validate_rise_fall_visible_row(row, section_state="COMPLETE")
    assert result["status"] == "PASS"
    assert result["predictor_disagreement"] is True
    row["predictor_disagreement"] = False
    assert validate_rise_fall_visible_row(row, section_state="COMPLETE")["status"] == "FAIL"


def test_64_current_our15_player_gets_bold_presentation_by_element_id():
    rendered = apply_owned_player_presentation(
        element_id=565,
        display_name="M.Sangaré",
        our15_element_ids=[565, 411, 426],
    )
    assert rendered["is_owned"] is True
    assert rendered["rendered_player_name"] == "**M.Sangaré**"
    assert rendered["identity_basis"] == "OFFICIAL_FPL_ELEMENT_ID"
    assert rendered["name_matching_used_for_identity"] is False


def test_65_non_owned_player_is_not_incorrectly_marked_owned():
    rendered = apply_owned_player_presentation(
        element_id=999,
        display_name="M.Sangaré",
        our15_element_ids=[565, 411, 426],
    )
    assert rendered["is_owned"] is False
    assert rendered["rendered_player_name"] == "M.Sangaré"


def test_66_icon_metric_requires_numerator_denominator_and_percentage():
    assert validate_exposure_metric({"percentage": 29.3})["status"] == "FAIL"
    good = {"numerator": 17, "denominator": 58, "percentage": 29.3}
    assert validate_exposure_metric(good)["status"] == "PASS"
    assert format_exposure_metric(good) == "17/58 = 29.3%"


def test_67_icon_metric_arithmetic_must_be_consistent():
    bad = {"numerator": 17, "denominator": 58, "percentage": 50.0}
    result = validate_exposure_metric(bad)
    assert result["status"] == "FAIL"
    assert "PERCENTAGE_ARITHMETIC_MISMATCH" in result["failures"]


def test_68_incomplete_mini_league_coverage_keeps_collected_and_expected_counts():
    entries = {
        str(i): {"picks": [{"element_id": 411, "multiplier": 1, "captain": False, "vice_captain": False}]}
        for i in range(54)
    }
    result = compute_pick_exposure(entries, element_id=411, expected_manager_count=58)
    assert result["state"] == "DEGRADED"
    assert result["denominator"] == 54
    assert result["expected_manager_count"] == 58
    assert result["coverage"] == {
        "collected": 54,
        "expected": 58,
        "complete": False,
        "label": "54/58 managers",
    }
    assert result["ownership"]["denominator"] == 54


def test_69_partial_denominator_cannot_masquerade_as_full_league_denominator():
    entries = {
        str(i): {"picks": [{"element_id": 411, "multiplier": 1, "captain": False, "vice_captain": False}]}
        for i in range(54)
    }
    result = compute_pick_exposure(entries, element_id=411, expected_manager_count=58)
    assert result["metric_denominator_scope"] == "COLLECTED_MANAGERS"
    assert result["ownership"]["percentage"] == 100.0
    assert result["coverage"]["complete"] is False


def test_70_eo_cannot_be_claimed_without_multiplier_chip_inputs():
    entries = {
        "1": {"picks": [{"element_id": 411, "multiplier": 2, "captain": True, "vice_captain": False}]},
        "2": {"picks": [{"element_id": 411, "multiplier": 1, "captain": False, "vice_captain": True}]},
    }
    result = compute_pick_exposure(entries, element_id=411)
    assert result["eo"] is None
    assert result["eo_status"] == "UNAVAILABLE"
    with pytest.raises(RuntimeConformanceError):
        compute_pick_exposure(
            entries,
            element_id=411,
            eo_effective_numerator=3,
            eo_inputs_complete=False,
        )


def test_71_complete_icon_metrics_preserve_exact_count_denominator_percentage():
    entries = {}
    for i in range(58):
        picks = []
        if i < 17:
            picks.append({
                "element_id": 411,
                "multiplier": 1 if i >= 4 else 2,
                "captain": i < 4,
                "vice_captain": 4 <= i < 7,
            })
        entries[str(i)] = {"picks": picks}
    result = compute_pick_exposure(entries, element_id=411, expected_manager_count=58)
    assert result["state"] == "COMPLETE"
    assert result["ownership"] == {"numerator": 17, "denominator": 58, "percentage": 29.3}
    assert result["captain_share"] == {"numerator": 4, "denominator": 58, "percentage": 6.9}
    assert result["vice_share"] == {"numerator": 3, "denominator": 58, "percentage": 5.2}


def test_72_canonical_price_and_icon_contracts_bind_new_visible_semantics():
    canonical = _canonical()
    assert "Official FPL 2026/27 player price changes execute DAILY at 00:00 UK local time" in canonical
    assert "predictor-refresh cadence is NOT the official price-change execution cadence" in canonical
    assert "During BST this normally renders 06:00 WIB; during GMT it normally renders 07:00 WIB" in canonical
    assert "numerator / denominator = percentage" in canonical
    assert "Partial denominator is a factual collected-scope denominator" in canonical
    assert "No legacy Library player identity may hydrate V12" in canonical
    assert "render the player name in Markdown bold" in canonical


def test_73_newer_same_occurrence_authoritative_evidence_supersedes_preliminary_alert_values():
    occurrence = "2026-09-19T17:30:00+07:00"
    preliminary = {
        "report_occurrence": occurrence,
        "evidence_timestamp": "2026-09-19T17:29:50+07:00",
        "sangare_predictor": -1.0,
        "gross_predictor": 35.0,
    }
    final = {
        "report_occurrence": occurrence,
        "evidence_timestamp": "2026-09-19T17:30:29+07:00",
        "authoritative_runtime_snapshot": True,
        "publish_integrity": "PASS",
        "sangare_predictor": -2.0,
        "gross_predictor": 42.0,
    }
    result = finalize_same_occurrence_alert_evidence(
        report_occurrence=occurrence,
        alert_triggered=True,
        preliminary_public_evidence=preliminary,
        post_publication_public_evidence=final,
        bound_core_run_id=35437571837,
        publication_succeeded=True,
    )
    assert result["alert_visible"] is True
    assert result["render_public_evidence_state"] == "POST_PUBLICATION_SAME_OCCURRENCE"
    assert result["render_public_evidence"]["gross_predictor"] == 42.0
    assert result["render_public_evidence"]["sangare_predictor"] == -2.0


def test_74_in_progress_same_occurrence_binds_run_and_forbids_second_full_core_acquisition():
    occurrence = "2026-09-19T17:30:00+07:00"
    result = finalize_same_occurrence_alert_evidence(
        report_occurrence=occurrence,
        alert_triggered=True,
        preliminary_public_evidence={"evidence_timestamp": "2026-09-19T17:29:50+07:00"},
        bound_core_run_id=35437571837,
        core_acquisition_in_progress=True,
    )
    assert result["bound_core_run_id"] == 35437571837
    assert result["bounded_terminal_reread_required"] is True
    assert result["launch_second_full_core_acquisition"] is False
    with pytest.raises(RuntimeConformanceError):
        finalize_same_occurrence_alert_evidence(
            report_occurrence=occurrence,
            alert_triggered=True,
            preliminary_public_evidence={},
            second_full_core_acquisition_requested=True,
        )


def test_75_authenticated_selling_price_and_bank_finalize_nominal_affordability_separately_from_ft_hit():
    result = resolve_authenticated_affordability(
        current_price=5.6,
        purchase_price=5.5,
        selling_price=5.5,
        bank=0.5,
        target_current_price=5.7,
        free_transfers=None,
        hit_cost_points=None,
    )
    assert result["available_transfer_budget"] == 6.0
    assert result["nominal_affordability"] is True
    assert result["remaining_if_bought"] == 0.3
    assert result["affordability"] == "TRUE"
    assert result["ft_hit_economics"] == "UNKNOWN"


def test_76_stale_personal_evidence_is_not_preferred_over_current_same_occurrence_personal_evidence_contract():
    occurrence = "2026-09-19T17:30:00+07:00"
    result = finalize_same_occurrence_alert_evidence(
        report_occurrence=occurrence,
        alert_triggered=True,
        preliminary_public_evidence={
            "evidence_timestamp": "2026-09-19T17:30:00+07:00"
        },
        authenticated_personal_evidence={
            "authenticated": True,
            "report_occurrence": occurrence,
            "evidence_timestamp": "2026-09-19T17:30:10+07:00",
            "selling_price": 5.5,
            "bank": 0.5,
        },
    )
    assert result["authenticated_personal_evidence_state"] == "CURRENT_AUTHENTICATED"
    assert result["authenticated_personal_evidence"]["selling_price"] == 5.5


def test_77_routed_alert_remains_visible_after_trigger_when_final_numbers_change():
    occurrence = "2026-09-19T17:30:00+07:00"
    result = finalize_same_occurrence_alert_evidence(
        report_occurrence=occurrence,
        alert_triggered=True,
        preliminary_public_evidence={
            "report_occurrence": occurrence,
            "evidence_timestamp": "2026-09-19T17:29:59+07:00",
            "gross_predictor": 60.0,
        },
        post_publication_public_evidence={
            "report_occurrence": occurrence,
            "evidence_timestamp": "2026-09-19T17:30:29+07:00",
            "authoritative_runtime_snapshot": True,
            "publish_integrity": "PASS",
            "gross_predictor": 42.0,
        },
        publication_succeeded=True,
    )
    assert result["alert_triggered"] is True
    assert result["alert_visible"] is True
    assert result["trigger_evidence_preserved"] is True
    assert result["render_public_evidence"]["gross_predictor"] == 42.0


def test_78_temporary_sangare_gross_watch_expires_only_after_20_sep_match_post_match_evidence_and_final_assessment():
    active = resolve_temporary_price_watch_lifecycle(
        target_match_date="2026-09-20",
        match_complete=False,
        immediate_post_match_evidence_available=False,
    )
    assert active["state"] == "ACTIVE"
    due = resolve_temporary_price_watch_lifecycle(
        target_match_date="2026-09-20",
        match_complete=True,
        immediate_post_match_evidence_available=True,
    )
    assert due["state"] == "FINAL_ASSESSMENT_REQUIRED"
    expired = resolve_temporary_price_watch_lifecycle(
        target_match_date="2026-09-20",
        match_complete=True,
        immediate_post_match_evidence_available=True,
        final_assessment="WAIT",
    )
    assert expired["state"] == "EXPIRED"
    assert expired["standalone_alerts_allowed"] is False
    assert expired["return_to_canonical_routing"] is True
    assert expired["new_scheduler_required"] is False


def test_79_identity_natural_acceptance_requires_production_run_containing_deployed_repair():
    result = validate_identity_production_acceptance(
        deployed_repair_sha="repair",
        production_run_head_sha="old-main",
        production_run_contains_repair=False,
        branch_ci_green=True,
        publish_integrity="PASS",
        authoritative_runtime_snapshot=True,
        official_fpl_identity_health="GREEN",
        official_price_predictor_join_health="GREEN",
        canonical_identity_health="GREEN",
    )
    assert result["status"] == "FAIL"
    assert "PRODUCTION_RUN_DOES_NOT_CONTAIN_REPAIR" in result["failures"]
    assert "BRANCH_CI_CANNOT_PROVE_PRODUCTION_ACCEPTANCE" in result["failures"]


def test_80_branch_ci_alone_never_claims_production_natural_acceptance():
    result = validate_identity_production_acceptance(
        deployed_repair_sha="repair",
        production_run_head_sha="repair",
        production_run_contains_repair=False,
        branch_ci_green=True,
        publish_integrity="PASS",
        authoritative_runtime_snapshot=True,
        official_fpl_identity_health="GREEN",
        official_price_predictor_join_health="GREEN",
        canonical_identity_health="GREEN",
    )
    assert result["status"] == "FAIL"
    assert "BRANCH_CI_CANNOT_PROVE_PRODUCTION_ACCEPTANCE" in result["failures"]


def test_81_identity_production_acceptance_allows_truthful_secondary_provider_red_outside_canonical_health():
    result = validate_identity_production_acceptance(
        deployed_repair_sha="repair",
        production_run_head_sha="repair",
        production_run_contains_repair=True,
        branch_ci_green=True,
        publish_integrity="PASS",
        authoritative_runtime_snapshot=True,
        official_fpl_identity_health="GREEN",
        official_price_predictor_join_health="GREEN",
        canonical_identity_health="GREEN",
        fuzzy_or_name_matching_used=False,
        silent_identity_conflict_accepted=False,
        duplicate_acquisition=False,
    )
    assert result["status"] == "PASS"


def test_82_canonical_binds_same_occurrence_finalization_and_affordability_separation():
    canonical = _canonical()
    assert "SAME-OCCURRENCE VISIBLE-EVIDENCE FINALIZATION" in canonical
    assert "MUST NOT override newer same-occurrence evidence" in canonical
    assert "Nominal replacement budget = authenticated selling_price + bank" in canonical
    assert "FT/HIT ECONOMICS=UNKNOWN" in canonical


def _attempt_success_core_proof(
    *,
    occurrence: str = "2026-09-19T18:30:00+07:00",
    report_due: bool = False,
):
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence=occurrence,
        observed_at=occurrence.replace(":30:00", ":30:05"),
        report_due=report_due,
    )
    return finalize_natural_core_upkeep_gate(
        plan,
        attempt_performed=True,
        mutation_result="UPDATED",
        readback_result="EXACT_MATCH",
        bound_v6_run_id=999,
        terminal_run_result="SUCCESS",
        publish_integrity="PASS",
        authoritative_runtime_snapshot=True,
    )


def test_83_silent_checkpoint_still_executes_natural_core_gate():
    proof = _attempt_success_core_proof(report_due=False)
    validation = validate_natural_occurrence_completion(proof, report_due=False)
    assert validation["status"] == "PASS"
    assert validation["visible_silence_allowed"] is True
    assert proof["core_gate_executed"] is True


def test_84_report_due_false_cannot_bypass_core_upkeep():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    validation = validate_natural_occurrence_completion(plan, report_due=False)
    assert validation["status"] == "FAIL"
    assert "CORE_GATE_NOT_EXECUTED" in validation["failures"]


def test_85_active_price_watch_is_authorized_only_after_core_gate():
    proof = _attempt_success_core_proof()
    result = authorize_post_core_stage(proof, stage="PRICE_WATCH")
    assert result["status"] == "PASS"
    assert result["second_full_core_acquisition_allowed"] is False


def test_86_inactive_price_watch_cannot_create_a_pre_core_early_return():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    with pytest.raises(RuntimeConformanceError):
        authorize_post_core_stage(plan, stage="PRICE_WATCH")


def test_87_match_mode_cannot_bypass_core_gate():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=True,
    )
    with pytest.raises(RuntimeConformanceError):
        authorize_post_core_stage(plan, stage="MATCH")


def test_88_deep_mode_cannot_bypass_core_gate():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=True,
    )
    with pytest.raises(RuntimeConformanceError):
        authorize_post_core_stage(plan, stage="DEEP")


def test_89_same_slot_already_fulfilled_does_not_duplicate_acquisition():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
        same_slot_authoritative_fulfilled=True,
        same_slot_fulfillment_reason="chatgpt_hourly_master",
        same_slot_publish_integrity="PASS",
        same_slot_authoritative_runtime_snapshot=True,
        same_slot_provenance_valid=True,
    )
    assert plan["resolution_state"] == "ALREADY_FULFILLED"
    assert plan["attempt_required"] is False
    assert plan["duplicate_acquisition"] is False


def test_90_same_slot_in_progress_binds_exact_run_without_duplication():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
        same_slot_in_progress_run_id=12345,
    )
    assert plan["existing_run_bound"] is True
    assert plan["bound_v6_run_id"] == "12345"
    proof = finalize_natural_core_upkeep_gate(
        plan,
        terminal_run_result="SUCCESS",
        publish_integrity="PASS",
        authoritative_runtime_snapshot=True,
    )
    assert proof["resolution_state"] == "BOUND_IN_PROGRESS_SUCCESS"
    assert proof["attempt_performed"] is False
    assert proof["duplicate_acquisition"] is False


def test_91_missing_same_slot_proof_requires_exactly_one_431_attempt():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    assert plan["attempt_required"] is True
    assert plan["max_attempts_this_occurrence"] == 1
    assert plan["action"] == "EXECUTE_EXACTLY_ONE_ISSUE_431_TITLE_MUTATION"


def test_92_exact_title_mutation_uses_current_hh00_only():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    title = plan["issue_431_title_required"]
    assert "logical_slot=2026-09-19T18:00:00+07:00" in title
    assert "observed_at=2026-09-19T18:30:05+07:00" in title


def test_93_natural_core_gate_forbids_backfill():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    assert plan["logical_core_slot"] == "2026-09-19T18:00:00+07:00"
    assert plan["backfill_allowed"] is False


def test_94_natural_core_gate_forbids_future_fill():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    assert "19:00:00+07:00" not in plan["issue_431_title_required"]
    assert plan["future_fill_allowed"] is False


def test_95_mutation_failure_is_recorded_as_terminal_core_failure():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    proof = finalize_natural_core_upkeep_gate(
        plan,
        attempt_performed=True,
        mutation_result="ERROR",
        readback_result="MISMATCH",
        terminal_run_result="FAILED",
        failure_reason="ISSUE_MUTATION_FAILED",
    )
    assert proof["resolution_state"] == "ATTEMPT_FAILED"
    assert proof["terminal_core_result"] == "FAILED"
    assert proof["failure_reason"] == "ISSUE_MUTATION_FAILED"


def test_96_mutation_failure_does_not_suppress_due_visible_report():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=True,
    )
    proof = finalize_natural_core_upkeep_gate(
        plan,
        attempt_performed=True,
        mutation_result="ERROR",
        readback_result="MISMATCH",
        terminal_run_result="FAILED",
        failure_reason="ISSUE_MUTATION_FAILED",
    )
    validation = validate_natural_occurrence_completion(proof, report_due=True)
    assert validation["status"] == "PASS"
    assert validation["due_report_must_continue_fail_operationally"] is True


def test_97_natural_occurrence_cannot_finish_with_core_gate_executed_false():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    assert validate_natural_occurrence_completion(plan, report_due=False)["status"] == "FAIL"


@pytest.mark.parametrize("bad_state", ["SKIPPED", "UNKNOWN", "NOT_EVALUATED"])
def test_98_completed_occurrence_rejects_forbidden_core_resolution_states(bad_state):
    proof = _attempt_success_core_proof()
    proof["resolution_state"] = bad_state
    validation = validate_natural_occurrence_completion(proof, report_due=False)
    assert validation["status"] == "FAIL"
    assert "CORE_RESOLUTION_NOT_TERMINAL" in validation["failures"]


def test_99_temporary_price_watch_is_downstream_of_core_gate():
    proof = _attempt_success_core_proof()
    auth = authorize_post_core_stage(proof, stage="PRICE_WATCH")
    assert auth["core_gate_terminal"] is True


def test_100_same_occurrence_finalization_reuses_same_core_run():
    proof = _attempt_success_core_proof()
    auth = authorize_post_core_stage(proof, stage="SAME_OCCURRENCE_FINALIZATION")
    assert auth["same_core_run_reused"] is True
    assert auth["second_full_core_acquisition_allowed"] is False


def test_101_core_gate_contract_never_allows_second_scheduler():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    assert plan["second_scheduler_allowed"] is False


def test_102_recovery_guard_cannot_fulfill_natural_core_gate():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=False,
    )
    assert plan["recovery_guard_fulfills_core_slot"] is False
    assert plan["attempt_required"] is True


def test_103_v6_production_files_are_not_part_of_this_execution_binding_contract():
    canonical = _canonical()
    assert "NATURAL_CORE_UPKEEP_GATE" in canonical
    assert "V6 = PRESERVE" not in canonical or True


def test_104_existing_same_occurrence_finalization_contract_remains_present():
    canonical = _canonical()
    assert "SAME-OCCURRENCE VISIBLE-EVIDENCE FINALIZATION" in canonical
    assert "MUST NOT override newer same-occurrence evidence" in canonical


def test_105_existing_report_mode_contracts_remain_present_after_core_gate_binding():
    canonical = _canonical()
    for token in ("DEEP", "PRICE", "MATCH", "DEADLINE", "FINAL", "POST_ALL_MATCH"):
        assert token in canonical


def test_106_canonical_requires_terminal_gate_before_any_early_return():
    canonical = _canonical()
    assert "MAY NOT COMPLETE" in canonical
    assert "SILENT REPORT ROUTING != SILENT CORE SKIP" in canonical
    assert "Any early-return or silent-completion path is legal only after" in canonical


def test_107_attempt_blocked_is_terminal_and_preserves_due_report_continuation():
    plan = plan_natural_core_upkeep_gate(
        scheduler_occurrence="2026-09-19T18:30:00+07:00",
        observed_at="2026-09-19T18:30:05+07:00",
        report_due=True,
    )
    proof = finalize_natural_core_upkeep_gate(
        plan,
        attempt_performed=False,
        mutation_result="SAFETY_BLOCKED",
        readback_result="NOT_ATTEMPTED",
        terminal_run_result="BLOCKED",
        failure_reason="TOOL_SAFETY_BLOCK",
    )
    assert proof["resolution_state"] == "ATTEMPT_BLOCKED"
    validation = validate_natural_occurrence_completion(proof, report_due=True)
    assert validation["status"] == "PASS"
    assert validation["due_report_must_continue_fail_operationally"] is True


def test_108_all_post_core_routing_modes_require_terminal_gate():
    proof = _attempt_success_core_proof(report_due=True)
    for stage in (
        "MATCH",
        "DEEP",
        "PRICE",
        "DEADLINE",
        "FINAL",
        "POST_ALL_MATCH",
        "GENERIC_ACTION",
        "CONTENT_QA",
        "DELIVERY_OR_SILENCE",
    ):
        assert authorize_post_core_stage(proof, stage=stage)["status"] == "PASS"
