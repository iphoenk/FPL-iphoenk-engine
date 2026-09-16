from __future__ import annotations

import pytest

from src.runtime_v6.delivery_integrity import MANDATORY_SECTIONS, plan_exact_scope_retrieval, resolve_report_slot_decision
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_contract import resolve_report_scope, resolve_report_scope_matrix
from src.runtime_v6.report_delivery import build_delivery_proof
from src.runtime_v6.report_qa import validate_pre_render_qa
from src.runtime_v6.report_recovery import plan_report_catch_up
from src.runtime_v6.report_recovery_closeout import REGRESSION_SCENARIO_IDS, evaluate_regression_acceptance
from src.runtime_v6.workflow_control import resolve_data_slot_decision
from test_support.report_rank20 import rank20_rows
from test_support.report_sections import r4_section_payloads


LOGICAL_SLOT = "2026-09-16T04:30:00+07:00"
REPORT_SLOT_ID = "2026-09-16T04:30+07:00|DEEP"
CATCH_UP_DEADLINE = "2026-09-16T05:00:00+07:00"


def _scope(**overrides):
    value = {
        "required": True,
        "auth_required": False,
        "volatile": True,
        "fresh_v6_available": True,
        "v6_scope_state": "CURRENT",
        "retrieval_state": "COMPLETE",
        "direct_fresh_available": False,
        "last_good_available": False,
    }
    value.update(overrides)
    return value


def _our15():
    return [
        *({"id": player_id, "position": "GK"} for player_id in range(1, 3)),
        *({"id": player_id, "position": "DEF"} for player_id in range(3, 8)),
        *({"id": player_id, "position": "MID"} for player_id in range(8, 13)),
        *({"id": player_id, "position": "FWD"} for player_id in range(13, 16)),
    ]


def _watchlist20():
    rows = []
    player_id = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for _ in range(5):
            rows.append({"id": player_id, "position": position})
            player_id += 1
    return rows


def _compute(
    *,
    our15_rows=None,
    starting_xi_ids=None,
    bench_ids=None,
    watchlist_rows=None,
    rise_rows=None,
    fall_rows=None,
):
    resolved_our15 = _our15() if our15_rows is None else our15_rows
    return build_report_compute_contract(
        scope_matrix_report_ready=True,
        our15_rows=resolved_our15,
        starting_xi_ids=(
            [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14]
            if starting_xi_ids is None
            else starting_xi_ids
        ),
        bench_ids=[2, 7, 12, 15] if bench_ids is None else bench_ids,
        watchlist_rows=_watchlist20() if watchlist_rows is None else watchlist_rows,
        rise_rows=rank20_rows(201, "RISE") if rise_rows is None else rise_rows,
        fall_rows=rank20_rows(301, "FALL") if fall_rows is None else fall_rows,
        section_payloads=r4_section_payloads(resolved_our15),
        facts={"price_fact": {"source": "official_fpl"}},
        models={"price_model": {"model": "v6_price_model"}},
    )


def _r01() -> bool:
    matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(),
            "price_predictor": _scope(),
            "private_ft_itb_sell_value": _scope(required=False, auth_required=True),
        },
        auth_status="OK",
    )
    return bool(
        matrix["report_ready"]
        and not matrix["blocking_scopes"]
        and all(row["source"] == "FRESH_V6" for row in matrix["scopes"].values())
        and matrix["legacy_fallback_allowed"] is False
    )


def _r02() -> bool:
    matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(),
            "fixtures": _scope(),
            "price_predictor": _scope(),
        },
        auth_status="NOT REQUESTED",
    )
    return bool(
        matrix["report_ready"]
        and not matrix["blocking_scopes"]
        and not matrix["degraded_scopes"]
        and all(row["source"] == "FRESH_V6" for row in matrix["scopes"].values())
    )


def _r03() -> bool:
    matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(),
            "fixtures": _scope(),
            "private_ft_itb_sell_value": _scope(required=False, auth_required=True),
        },
        auth_status="EXPIRED",
    )
    private = matrix["scopes"]["private_ft_itb_sell_value"]
    return bool(
        matrix["report_ready"]
        and matrix["scopes"]["official_universe"]["source"] == "FRESH_V6"
        and private["status"] == "DEGRADED"
        and private["report_blocking"] is False
        and private["reason"] == "AUTH_EXPIRED"
    )


def _r04() -> bool:
    matrix = resolve_report_scope_matrix(
        {
            "icon_mini_league": _scope(),
            "private_ft_itb_sell_value": _scope(required=False, auth_required=True),
        },
        auth_status="EXPIRED",
    )
    return bool(
        matrix["report_ready"]
        and matrix["scopes"]["icon_mini_league"]["source"] == "FRESH_V6"
        and matrix["scopes"]["private_ft_itb_sell_value"]["degraded"] is True
    )


def _r05() -> bool:
    matrix = resolve_report_scope_matrix(
        {
            "price_predictor": _scope(),
            "private_ft_itb_sell_value": _scope(required=False, auth_required=True),
        },
        auth_status="EXPIRED",
    )
    return bool(
        matrix["report_ready"]
        and matrix["scopes"]["price_predictor"]["source"] == "FRESH_V6"
        and matrix["scopes"]["private_ft_itb_sell_value"]["report_blocking"] is False
    )


def _r06() -> bool:
    decision = plan_exact_scope_retrieval(
        v6_scope_id="bootstrap",
        v6_scope_state="CURRENT",
        retrieval_state="CONNECTOR_TRUNCATED",
    )
    return bool(
        decision["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
        and decision["scope_lock_required"] is True
        and decision["direct_fresh_allowed"] is False
        and decision["final_unavailable_allowed"] is False
        and decision["legacy_fallback_allowed"] is False
    )


def _r07() -> bool:
    matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(
                fresh_v6_available=False,
                v6_scope_state="V6_SCOPE_FAILED",
                direct_fresh_available=True,
            ),
            "price_predictor": _scope(),
            "icon_mini_league": _scope(),
        },
        auth_status="NOT REQUESTED",
    )
    return bool(
        matrix["report_ready"]
        and matrix["direct_fresh_scopes"] == ["official_universe"]
        and matrix["scopes"]["official_universe"]["source"] == "DIRECT_FRESH"
        and matrix["scopes"]["price_predictor"]["source"] == "FRESH_V6"
        and matrix["scopes"]["icon_mini_league"]["source"] == "FRESH_V6"
    )


def _r08() -> bool:
    nonvolatile = resolve_report_scope(
        scope_id="submitted_picks",
        auth_status="NOT REQUESTED",
        **_scope(
            volatile=False,
            fresh_v6_available=False,
            v6_scope_state="V6_SCOPE_MISSING",
            direct_fresh_available=False,
            last_good_available=True,
        ),
    )
    volatile = resolve_report_scope(
        scope_id="live",
        auth_status="NOT REQUESTED",
        **_scope(
            volatile=True,
            fresh_v6_available=False,
            v6_scope_state="V6_SCOPE_MISSING",
            direct_fresh_available=False,
            last_good_available=True,
        ),
    )
    return bool(
        nonvolatile["source"] == "LAST_GOOD_NONVOLATILE"
        and nonvolatile["status"] == "PASS"
        and volatile["source"] == "UNAVAILABLE"
        and volatile["status"] == "BLOCKED"
    )


def _r09() -> bool:
    result = _compute(our15_rows=_our15()[:-1])
    checks = result["SECTION_CONTRACT"]["checks"]
    return bool(
        result["status"] == "FAIL"
        and "SECTION_CONTRACT" in result["failures"]
        and checks["OUR15"]["status"] == "FAIL"
    )


def _r10() -> bool:
    result = _compute(watchlist_rows=_watchlist20()[:-1])
    checks = result["SECTION_CONTRACT"]["checks"]
    return bool(
        result["status"] == "FAIL"
        and "SECTION_CONTRACT" in result["failures"]
        and checks["WATCHLIST20"]["status"] == "FAIL"
    )


def _r11() -> bool:
    result = _compute(
        rise_rows=rank20_rows(201, "RISE")[:-1],
        fall_rows=rank20_rows(301, "FALL")[:-1],
    )
    checks = result["SECTION_CONTRACT"]["checks"]
    return bool(
        result["status"] == "FAIL"
        and "SECTION_CONTRACT" in result["failures"]
        and checks["RISE20"]["status"] == "FAIL"
        and checks["FALL20"]["status"] == "FAIL"
    )


def _r12() -> bool:
    result = _compute(
        starting_xi_ids=[1, 3, 4, 5, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 6, 7, 12, 15],
    )
    xi_bench = result["SECTION_CONTRACT"]["checks"]["XI_BENCH"]
    return bool(
        result["status"] == "FAIL"
        and "SECTION_CONTRACT" in result["failures"]
        and xi_bench["status"] == "FAIL"
        and xi_bench["XI"]["status"] == "FAIL"
        and xi_bench["BENCH"]["status"] == "FAIL"
    )


def _r13() -> bool:
    compute = _compute()
    manifest = [
        {"section_id": section_id, "status": "COMPLETE"}
        for section_id in MANDATORY_SECTIONS
    ]
    result = validate_pre_render_qa(
        compute_contract=compute,
        section_manifest=manifest,
        mini_league_denominator_complete=False,
    )
    return bool(
        result["status"] == "FAIL"
        and result["qa_passed"] is False
        and "MINI_LEAGUE_DENOMINATOR_INCOMPLETE" in result["failures"]
    )


def _r14() -> bool:
    post_render_qa = {
        "status": "PASS",
        "qa_stage": "POST_RENDER",
        "qa_passed": True,
        "delivery_ready": False,
        "report_state": "BUILDING",
        "next_action": "BUILD_DELIVERY_PROOF",
        "legacy_fallback_allowed": False,
        "compute_fingerprint": "a" * 64,
        "render_contract_token": "b" * 64,
    }
    result = build_delivery_proof(
        post_render_qa=post_render_qa,
        report_slot_id=REPORT_SLOT_ID,
        delivery_status="ACKNOWLEDGED",
        delivery_channel="chat",
        delivery_target="fpl-master-user",
        provider_receipt_id="",
        delivered_at="2026-09-16T04:31:00+07:00",
    )
    return bool(
        result["status"] == "FAIL"
        and result["report_delivered"] is False
        and result["next_action"] == "DELIVERY_PROOF_RECOVERY"
        and "PROVIDER_RECEIPT_ID_MISSING" in result["failures"]
    )


def _r15() -> bool:
    data = resolve_data_slot_decision(already_published=True)
    report = resolve_report_slot_decision(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        report_state="NOT_STARTED",
        v6_already_published=True,
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )
    return bool(
        data["skip_new_acquisition"] is True
        and data["reuse_last_valid_publication"] is True
        and data["continue_report_pipeline"] is True
        and report["report_required"] is True
        and report["start_build"] is True
        and report["report_slot_id"] == REPORT_SLOT_ID
    )


def _r16() -> bool:
    inside = plan_report_catch_up(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        observed_at="2026-09-16T04:45:00+07:00",
        catch_up_deadline=CATCH_UP_DEADLINE,
        report_state="NOT_STARTED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )
    expired = plan_report_catch_up(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        observed_at="2026-09-16T05:00:01+07:00",
        catch_up_deadline=CATCH_UP_DEADLINE,
        report_state="NOT_STARTED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )
    return bool(
        inside["report_slot_id"] == REPORT_SLOT_ID
        and inside["catch_up_required"] is True
        and inside["start_build"] is True
        and expired["report_slot_id"] == REPORT_SLOT_ID
        and expired["catch_up_required"] is False
        and expired["start_build"] is False
        and expired["next_action"] == "CATCH_UP_WINDOW_EXPIRED"
    )


SCENARIO_RUNNERS = {
    "R01": _r01,
    "R02": _r02,
    "R03": _r03,
    "R04": _r04,
    "R05": _r05,
    "R06": _r06,
    "R07": _r07,
    "R08": _r08,
    "R09": _r09,
    "R10": _r10,
    "R11": _r11,
    "R12": _r12,
    "R13": _r13,
    "R14": _r14,
    "R15": _r15,
    "R16": _r16,
}


@pytest.mark.parametrize("scenario_id", REGRESSION_SCENARIO_IDS)
def test_locked_recovery_regression_scenario(scenario_id: str):
    assert set(SCENARIO_RUNNERS) == set(REGRESSION_SCENARIO_IDS)
    assert SCENARIO_RUNNERS[scenario_id](), f"locked recovery regression failed: {scenario_id}"


def test_behavioral_matrix_drives_exact_r01_r16_acceptance():
    results = {
        scenario_id: {
            "status": "PASS" if SCENARIO_RUNNERS[scenario_id]() else "FAIL",
            "detail": "runtime_behavior",
        }
        for scenario_id in REGRESSION_SCENARIO_IDS
    }

    acceptance = evaluate_regression_acceptance(results)

    assert acceptance["status"] == "PASS"
    assert acceptance["regression_ready"] is True
    assert acceptance["scenario_count"] == 16
    assert acceptance["passed_count"] == 16
    assert acceptance["failed_or_missing_count"] == 0
    assert acceptance["scenario_ids"] == list(REGRESSION_SCENARIO_IDS)
    assert acceptance["legacy_fallback_allowed"] is False
