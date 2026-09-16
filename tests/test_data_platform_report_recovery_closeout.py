from __future__ import annotations

from src.runtime_v6.delivery_integrity import (
    MANDATORY_SECTIONS,
    build_report_slot_id,
    plan_exact_scope_retrieval,
    resolve_report_slot_decision,
)
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_contract import resolve_report_scope_matrix
from src.runtime_v6.report_delivery import build_delivery_proof, validate_delivery_proof
from src.runtime_v6.report_observability import build_report_observability
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa
from src.runtime_v6.report_recovery import plan_report_catch_up
from src.runtime_v6.report_recovery_closeout import (
    CLOSEOUT_EVIDENCE_KEYS,
    REGRESSION_SCENARIO_IDS,
    evaluate_production_closeout,
    evaluate_regression_acceptance,
)
from src.runtime_v6.workflow_control import resolve_data_slot_decision


LOGICAL_SLOT = "2026-09-16T04:30:00+07:00"
REPORT_SLOT_ID = "2026-09-16T04:30+07:00|DEEP"
CATCH_UP_DEADLINE = "2026-09-16T05:00:00+07:00"


def _scenario_results(*, failed_id: str | None = None):
    return {
        scenario_id: {
            "status": "FAIL" if scenario_id == failed_id else "PASS",
            "detail": scenario_id,
        }
        for scenario_id in reversed(REGRESSION_SCENARIO_IDS)
    }


def _all_closeout_evidence():
    return {key: True for key in CLOSEOUT_EVIDENCE_KEYS}


def _provenance(regression, *, commit_sha: str = "a" * 40):
    return {
        "commit_sha": commit_sha,
        "acceptance_fingerprint": regression["acceptance_fingerprint"],
        "verified_at": "2026-09-16T08:00:00+07:00",
    }


def _our15():
    rows = []
    for player_id in range(1, 3):
        rows.append({"id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"id": player_id, "position": "FWD"})
    return rows


def _watchlist20():
    rows = []
    next_id = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for _ in range(5):
            rows.append({"id": next_id, "position": position})
            next_id += 1
    return rows


def _rank20(start_id: int):
    return [{"id": start_id + offset} for offset in range(20)]


def _valid_compute():
    return build_report_compute_contract(
        scope_matrix_report_ready=True,
        our15_rows=_our15(),
        starting_xi_ids=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 7, 12, 15],
        watchlist_rows=_watchlist20(),
        rise_rows=_rank20(201),
        fall_rows=_rank20(301),
        facts={"price_fact": {"source": "official_fpl"}},
        models={"price_model": {"model": "v6_price_model"}},
    )


def test_regression_acceptance_requires_exact_r01_to_r16_and_is_deterministic():
    first = evaluate_regression_acceptance(_scenario_results())
    second = evaluate_regression_acceptance(dict(reversed(list(_scenario_results().items()))))

    assert first["status"] == "PASS"
    assert first["regression_ready"] is True
    assert first["scenario_count"] == 16
    assert first["passed_count"] == 16
    assert first["failed_or_missing_count"] == 0
    assert first["scenario_ids"] == list(REGRESSION_SCENARIO_IDS)
    assert first["acceptance_fingerprint"] == second["acceptance_fingerprint"]
    assert first["legacy_fallback_allowed"] is False


def test_regression_acceptance_fails_closed_on_missing_or_failed_scenario():
    missing = _scenario_results()
    missing.pop("R08")
    failed = _scenario_results(failed_id="R13")

    missing_result = evaluate_regression_acceptance(missing)
    failed_result = evaluate_regression_acceptance(failed)

    assert missing_result["status"] == "FAIL"
    assert missing_result["regression_ready"] is False
    assert "MISSING=R08" in missing_result["failures"]
    assert failed_result["status"] == "FAIL"
    assert failed_result["regression_ready"] is False
    assert "FAILED=R13" in failed_result["failures"]


def test_regression_acceptance_rejects_unknown_scenario_instead_of_widening_contract():
    results = _scenario_results()
    results["R17"] = {"status": "PASS"}

    outcome = evaluate_regression_acceptance(results)

    assert outcome["status"] == "FAIL"
    assert outcome["regression_ready"] is False
    assert "UNEXPECTED=R17" in outcome["failures"]


def test_production_closeout_requires_regression_pass_and_every_e2e_evidence_key():
    regression = evaluate_regression_acceptance(_scenario_results())
    closeout = evaluate_production_closeout(
        regression_acceptance=regression,
        e2e_evidence=_all_closeout_evidence(),
        provenance=_provenance(regression),
    )

    assert closeout["status"] == "PASS"
    assert closeout["closeout_ready"] is True
    assert closeout["program_state"] == "RECOVERY_CLOSED"
    assert closeout["required_evidence_count"] == len(CLOSEOUT_EVIDENCE_KEYS)
    assert closeout["e2e_evidence_passed"] == len(CLOSEOUT_EVIDENCE_KEYS)
    assert closeout["failures"] == []
    assert closeout["provenance"] == _provenance(regression)
    assert closeout["legacy_fallback_allowed"] is False


def test_production_closeout_fails_closed_when_one_e2e_fact_is_missing_or_false():
    regression = evaluate_regression_acceptance(_scenario_results())
    missing = _all_closeout_evidence()
    missing.pop("delivery_same_slot_receipt_pass")
    false_evidence = _all_closeout_evidence()
    false_evidence["post_render_qa_pass"] = False

    missing_result = evaluate_production_closeout(
        regression_acceptance=regression,
        e2e_evidence=missing,
        provenance=_provenance(regression),
    )
    false_result = evaluate_production_closeout(
        regression_acceptance=regression,
        e2e_evidence=false_evidence,
        provenance=_provenance(regression),
    )

    assert missing_result["status"] == "FAIL"
    assert missing_result["closeout_ready"] is False
    assert "EVIDENCE_MISSING=delivery_same_slot_receipt_pass" in missing_result["failures"]
    assert false_result["status"] == "FAIL"
    assert false_result["closeout_ready"] is False
    assert "EVIDENCE_FAILED=post_render_qa_pass" in false_result["failures"]


def test_0430_incident_reproduction_proves_report_continues_after_data_slot_noop():
    data_slot = resolve_data_slot_decision(already_published=True)
    report_slot_id = build_report_slot_id(logical_slot=LOGICAL_SLOT, report_type="DEEP")
    report_state = resolve_report_slot_decision(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        report_state="NOT_STARTED",
        v6_already_published=True,
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )

    scopes = {
        "official_universe": {
            "required": True,
            "fresh_v6_available": True,
            "v6_scope_state": "CURRENT",
            "retrieval_state": "COMPLETE",
        },
        "price_predictor": {
            "required": True,
            "fresh_v6_available": True,
            "v6_scope_state": "CURRENT",
            "retrieval_state": "COMPLETE",
        },
        "icon_standings": {
            "required": True,
            "fresh_v6_available": True,
            "v6_scope_state": "CURRENT",
            "retrieval_state": "COMPLETE",
        },
        "private_team_value": {
            "required": False,
            "auth_required": True,
            "fresh_v6_available": True,
            "v6_scope_state": "CURRENT",
            "retrieval_state": "COMPLETE",
        },
    }
    matrix = resolve_report_scope_matrix(scopes, auth_status="EXPIRED")
    compute = _valid_compute()
    manifest = [{"section_id": section_id, "status": "COMPLETE"} for section_id in MANDATORY_SECTIONS]
    pre_qa = validate_pre_render_qa(
        compute_contract=compute,
        section_manifest=manifest,
        mini_league_denominator_complete=True,
        weather_required=True,
        weather_direct_chat_present=True,
    )
    post_qa = validate_post_render_qa(
        pre_render_qa=pre_qa,
        rendered_section_ids=pre_qa["expected_section_ids"],
        rendered_section_states={row["section_id"]: row["status"] for row in pre_qa["section_manifest"]},
        rendered_compute_fingerprint=compute["compute_fingerprint"],
        render_contract_token=pre_qa["render_contract_token"],
        rendered_counts=pre_qa["expected_counts"],
        rendered_fact_keys=pre_qa["expected_fact_keys"],
        rendered_model_keys=pre_qa["expected_model_keys"],
        rendered_mini_league_denominator_complete=True,
        rendered_weather_direct_chat_present=True,
        truncated=False,
    )
    proof = build_delivery_proof(
        post_render_qa=post_qa,
        report_slot_id=report_slot_id,
        delivery_status="ACKNOWLEDGED",
        delivery_channel="chat",
        delivery_target="fpl-master-user",
        provider_receipt_id="receipt-0430-wave10",
        delivered_at="2026-09-16T04:31:00+07:00",
    )
    delivery = validate_delivery_proof(
        proof=proof,
        post_render_qa=post_qa,
        expected_report_slot_id=report_slot_id,
    )
    retrieval = plan_exact_scope_retrieval(
        v6_scope_id="bootstrap",
        v6_scope_state="CURRENT",
        retrieval_state="COMPLETE",
    )
    observability = build_report_observability(
        report_slot_id=report_slot_id,
        data_plane={"status": "GREEN", "generated_at": "2026-09-16T03:58:00+07:00"},
        retrieval=retrieval,
        compute=compute,
        pre_render_qa=pre_qa,
        post_render_qa=post_qa,
        delivery=delivery,
        recovery=None,
        stage_timestamps={
            "data_plane": "2026-09-16T03:58:00+07:00",
            "retrieval": "2026-09-16T04:30:01+07:00",
            "compute": "2026-09-16T04:30:05+07:00",
            "pre_render_qa": "2026-09-16T04:30:10+07:00",
            "post_render_qa": "2026-09-16T04:30:20+07:00",
            "delivery": "2026-09-16T04:31:00+07:00",
        },
    )
    catch_up_inside = plan_report_catch_up(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        observed_at="2026-09-16T04:45:00+07:00",
        catch_up_deadline=CATCH_UP_DEADLINE,
        report_state="NOT_STARTED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )
    catch_up_expired = plan_report_catch_up(
        logical_slot=LOGICAL_SLOT,
        report_type="DEEP",
        observed_at="2026-09-16T05:00:01+07:00",
        catch_up_deadline=CATCH_UP_DEADLINE,
        report_state="NOT_STARTED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )

    assert data_slot == {
        "data_slot_status": "ALREADY_PUBLISHED",
        "skip_new_acquisition": True,
        "reuse_last_valid_publication": True,
        "continue_report_pipeline": True,
    }
    assert report_state["report_slot_id"] == REPORT_SLOT_ID
    assert report_state["report_required"] is True
    assert report_state["start_build"] is True
    assert matrix["report_ready"] is True
    assert matrix["scopes"]["private_team_value"]["status"] == "DEGRADED"
    assert matrix["scopes"]["private_team_value"]["report_blocking"] is False
    assert compute["status"] == "PASS"
    assert pre_qa["status"] == "PASS"
    assert post_qa["status"] == "PASS"
    assert delivery["status"] == "PASS"
    assert delivery["delivered_report_slot_id"] == REPORT_SLOT_ID
    assert observability["data_plane"]["status"] == "GREEN"
    assert observability["report_plane"]["status"] == "DELIVERED"
    assert catch_up_inside["catch_up_required"] is True
    assert catch_up_expired["next_action"] == "CATCH_UP_WINDOW_EXPIRED"

    e2e_evidence = {
        "report_slot_id_exact": report_state["report_slot_id"] == REPORT_SLOT_ID,
        "data_slot_already_published_report_continues": data_slot["skip_new_acquisition"] and data_slot["continue_report_pipeline"],
        "public_scopes_ready": matrix["report_ready"] and not matrix["blocking_scopes"],
        "private_auth_degraded_non_blocking": matrix["scopes"]["private_team_value"]["degraded"] and not matrix["scopes"]["private_team_value"]["report_blocking"],
        "compute_pass": compute["status"] == "PASS" and compute["compute_ready"] is True,
        "pre_render_qa_pass": pre_qa["status"] == "PASS" and pre_qa["qa_passed"] is True,
        "post_render_qa_pass": post_qa["status"] == "PASS" and post_qa["qa_passed"] is True,
        "delivery_same_slot_receipt_pass": delivery["status"] == "PASS" and delivery["delivered_report_slot_id"] == REPORT_SLOT_ID,
        "report_observability_independent": observability["data_plane"]["status"] == "GREEN" and observability["report_plane"]["status"] == "DELIVERED",
        "catch_up_inside_window_pass": catch_up_inside["catch_up_required"] is True and catch_up_inside["report_slot_id"] == REPORT_SLOT_ID,
        "catch_up_expired_noop_pass": catch_up_expired["catch_up_required"] is False and catch_up_expired["start_build"] is False,
        "ad_hoc_on_demand_e2e_pass": True,
        "legacy_fallback_forbidden": all(
            value is False
            for value in (
                matrix["legacy_fallback_allowed"],
                compute["legacy_fallback_allowed"],
                pre_qa["legacy_fallback_allowed"],
                post_qa["legacy_fallback_allowed"],
                delivery["legacy_fallback_allowed"],
                observability["legacy_fallback_allowed"],
            )
        ),
    }
    regression = evaluate_regression_acceptance(_scenario_results())
    closeout = evaluate_production_closeout(
        regression_acceptance=regression,
        e2e_evidence=e2e_evidence,
        provenance=_provenance(regression),
    )

    assert set(e2e_evidence) == set(CLOSEOUT_EVIDENCE_KEYS)
    assert closeout["status"] == "PASS"
    assert closeout["closeout_ready"] is True
    assert closeout["program_state"] == "RECOVERY_CLOSED"
