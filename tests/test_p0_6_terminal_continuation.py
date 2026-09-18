from __future__ import annotations

from pathlib import Path

import pytest

from src.runtime_v6.delivery_integrity import build_report_slot_id
from src.runtime_v6.domains.report_plane.decision_context import (
    build_persisted_decision_context_state,
    load_decision_context_state,
    persist_decision_context_state,
)
from src.runtime_v6.domains.report_plane.report_contract import (
    evaluate_rolling_natural_acceptance,
    resolve_report_data_readiness,
    resolve_terminal_continuation,
)
from src.runtime_v6.domains.report_plane.report_delivery import record_visible_emission
from src.runtime_v6.domains.report_plane.report_prefetch import (
    evaluate_report_prefetch_readiness,
    resolve_report_prefetch_continuation,
)


SLOT = "2026-09-18T18:30:00+07:00"
REPORT_SLOT_ID = build_report_slot_id(logical_slot=SLOT, report_type="DEADLINE")
RUN_ID = "35339771399"


def _publication(*, generated_at="2026-09-18T18:20:00+07:00", sha="a" * 40):
    return {
        "generated_at": generated_at,
        "authoritative_runtime_snapshot": True,
        "publish_integrity": "PASS",
        "provenance_valid": True,
        "available_scopes": ["deadline_report"],
        "publication_sha": sha,
    }


def _post_render_pass():
    return {
        "status": "PASS",
        "qa_stage": "POST_RENDER",
        "qa_passed": True,
        "delivery_ready": False,
        "report_state": "BUILDING",
        "next_action": "BUILD_DELIVERY_PROOF",
        "legacy_fallback_allowed": False,
        "compute_fingerprint": "a" * 64,
        "render_contract_token": "b" * 64,
        "mandatory_scope_gate_pass": True,
        "input_completeness_pass": True,
        "pre_render_qa_pass": True,
        "post_render_qa_pass": True,
        "report_contract_pass": True,
        "can_emit": True,
        "report_slot_id": REPORT_SLOT_ID,
    }


def test_01_1830_in_progress_then_success_requires_terminal_continuation():
    result = resolve_terminal_continuation(
        report_slot_id=REPORT_SLOT_ID,
        workflow_run_id=RUN_ID,
        workflow_reads=[
            {
                "workflow_run_id": RUN_ID,
                "state": "IN_PROGRESS",
                "observed_at": "2026-09-18T18:28:31+07:00",
            },
            {
                "workflow_run_id": RUN_ID,
                "state": "PUBLICATION_READY",
                "observed_at": "2026-09-18T18:28:58+07:00",
            },
        ],
        started_at="2026-09-18T18:28:31+07:00",
        evaluated_at="2026-09-18T18:28:58+07:00",
    )
    assert result["status"] == "TERMINAL_SUCCESS"
    assert result["continue_same_run"] is True
    assert result["resume_same_report_pipeline"] is True
    assert result["intermediate_user_output_allowed"] is False
    assert result["status_only_final_output_allowed"] is False
    assert result["next_action"] == "RESUME_CANONICAL_REPORT_PIPELINE"
    assert result["pipeline_resume_steps"][-2:] == ["DELIVERY", "SAME_SLOT_DELIVERY_RECEIPT"]


def test_02_in_progress_with_fresh_prior_snapshot_is_nonblocking_not_degraded():
    result = resolve_report_data_readiness(
        current_acquisition_state="ACQUISITION_IN_PROGRESS",
        current_acquisition_id=RUN_ID,
        current_publication=None,
        authoritative_publications=[_publication()],
        observed_at="2026-09-18T18:28:35+07:00",
        maximum_age_minutes=45,
        required_scope="deadline_report",
        waited_seconds=4,
    )
    assert result["status"] == "PASS"
    assert result["evidence_class"] == "FRESHEST_VALID_AUTHORITATIVE_SNAPSHOT"
    assert result["blanket_degraded"] is False
    assert result["poll_same_acquisition"] is True
    assert result["start_new_acquisition"] is False


def test_03_in_progress_to_failure_uses_fail_operational_recovery_not_status_output():
    result = resolve_terminal_continuation(
        report_slot_id=REPORT_SLOT_ID,
        workflow_run_id=RUN_ID,
        workflow_reads=[
            {"state": "ACQUISITION_IN_PROGRESS"},
            {"state": "ACQUISITION_FAILED"},
        ],
        started_at="2026-09-18T18:28:31+07:00",
        evaluated_at="2026-09-18T18:28:50+07:00",
    )
    assert result["status"] == "TERMINAL_FAILURE"
    assert result["next_action"] == "FAIL_OPERATIONAL_REPORT_RECOVERY"
    assert result["continue_same_run"] is True
    assert result["status_only_final_output_allowed"] is False
    assert "FRESHEST_VALID_AUTHORITATIVE_SNAPSHOT" in result["pipeline_resume_steps"]
    assert "PRE_RENDER_QA" in result["pipeline_resume_steps"]


def test_04_publish_in_progress_after_collect_success_must_continue_to_publication_ready():
    first = resolve_terminal_continuation(
        report_slot_id=REPORT_SLOT_ID,
        workflow_run_id=RUN_ID,
        workflow_reads=[
            {"state": "PUBLICATION_IN_PROGRESS"},
        ],
        started_at="2026-09-18T18:28:31+07:00",
        evaluated_at="2026-09-18T18:28:40+07:00",
    )
    assert first["status"] == "TRANSITIONAL"
    assert first["next_action"] == "RE_READ_SAME_WORKFLOW"
    assert first["intermediate_user_output_allowed"] is False

    second = resolve_terminal_continuation(
        report_slot_id=REPORT_SLOT_ID,
        workflow_run_id=RUN_ID,
        workflow_reads=[
            {"state": "PUBLICATION_IN_PROGRESS"},
            {"state": "PUBLICATION_READY"},
        ],
        started_at="2026-09-18T18:28:31+07:00",
        evaluated_at="2026-09-18T18:28:46+07:00",
    )
    assert second["status"] == "TERMINAL_SUCCESS"
    assert second["next_action"] == "RESUME_CANONICAL_REPORT_PIPELINE"


def test_05_core_success_prefetch_missing_gets_exactly_one_recovery_then_continues():
    initial = evaluate_report_prefetch_readiness(
        None,
        report_kind="deadline_review",
        requested_logical_slot=SLOT,
        maximum_age_minutes=45,
        refresh_attempt=0,
        max_refresh_attempts=1,
        scope=("personal", "mini_league"),
        observed_at="2026-09-18T18:29:00+07:00",
    )
    assert initial["refresh_required"] is True

    refreshed_snapshot = {
        "report_kind": "deadline_review",
        "target_logical_report_slot": SLOT,
        "scope": ["personal", "mini_league"],
        "generated_at": "2026-09-18T18:29:05+07:00",
        "public_core_complete": True,
        "complete": True,
        "report_prefetch_run_id": "prefetch-1830",
    }
    refreshed = evaluate_report_prefetch_readiness(
        refreshed_snapshot,
        report_kind="deadline_review",
        requested_logical_slot=SLOT,
        maximum_age_minutes=45,
        refresh_attempt=1,
        max_refresh_attempts=1,
        scope=("personal", "mini_league"),
        observed_at="2026-09-18T18:29:10+07:00",
    )
    continuation = resolve_report_prefetch_continuation(
        report_slot_id=REPORT_SLOT_ID,
        initial_readiness=initial,
        refreshed_readiness=refreshed,
    )
    assert continuation["status"] == "PASS"
    assert continuation["refresh_count"] == 1
    assert continuation["next_action"] == "RESUME_CANONICAL_REPORT_PIPELINE"
    assert continuation["core_acquisition_satisfied_by_prefetch"] is False


def test_06_active_scenarios_persist_durably_in_report_plane_state(tmp_path: Path):
    # Named players are regression fixture data only, never production code constants.
    state = build_persisted_decision_context_state(
        updated_at="2026-09-18T18:20:00+07:00",
        confirmed_current_squad_state={"state_ref": "LATEST_EXPLICIT_USER_SQUAD"},
        scenario_events=[
            {
                "scenario_id": "bruno-route",
                "state": "CONTEMPLATED",
                "updated_at": "2026-09-18T18:15:00+07:00",
                "player_candidates": ["Bruno Fernandes"],
                "route": {"out": "Bruno Fernandes", "in": "candidate"},
            },
            {
                "scenario_id": "jp-route",
                "state": "CONTEMPLATED",
                "updated_at": "2026-09-18T18:16:00+07:00",
                "player_candidates": ["João Pedro"],
                "route": {"out": "João Pedro", "in": "candidate"},
            },
            {
                "scenario_id": "sangare-route",
                "state": "CONTEMPLATED",
                "updated_at": "2026-09-18T18:17:00+07:00",
                "player_candidates": ["Sangaré"],
                "route": {"out": "Sangaré", "in": "candidate"},
            },
        ],
        one_gw_punt_routes=[{"route_id": "punt-1"}],
        multi_gw_routes=[{"route_id": "3-5gw-1"}],
        formation_branches=[{"formation": "3-5-2"}],
        xi_branches=[{"branch_id": "xi-a"}],
        bench_branches=[{"branch_id": "bench-a"}],
        cvc_branches=[{"captain": "candidate", "vice": "candidate"}],
        ft_hit_assumptions={"ft": 1, "hit": 0},
        reversal_conditions=["late team news"],
    )
    path = tmp_path / "report_plane" / "current_decision_context.json"
    persist_decision_context_state(state, path=path)
    loaded = load_decision_context_state(path=path)
    assert loaded is not None
    assert loaded["source"] == "user_explicit"
    assert loaded["report_plane_state"] is True
    assert loaded["v6_factual_data_plane_owner"] is False
    assert len(loaded["unresolved_named_scenarios"]) == 3

    with pytest.raises(Exception):
        persist_decision_context_state(state, path=tmp_path / "data" / "v6" / "context.json")


def test_07_intermediate_status_candidate_is_rejected_by_delivery_lifecycle():
    visible = record_visible_emission(
        post_render_qa=_post_render_pass(),
        report_slot_id=REPORT_SLOT_ID,
        occurrence_identity="natural-1830",
        producer_identity="FPL_MASTER_REPORT_PLANE",
        emitted_at="2026-09-18T18:30:20+07:00",
        status_only=True,
    )
    assert visible["status"] == "FAIL"
    assert visible["visible_emitted"] is False
    assert visible["delivery_proof_valid"] is False


def test_08_1830_golden_fixture_remains_historical_fail_but_repaired_path_would_continue():
    old_behavior = resolve_terminal_continuation(
        report_slot_id=REPORT_SLOT_ID,
        workflow_run_id=RUN_ID,
        workflow_reads=[
            {"state": "ACQUISITION_IN_PROGRESS"},
        ],
        started_at="2026-09-18T18:28:31+07:00",
        evaluated_at="2026-09-18T18:28:31+07:00",
    )
    assert old_behavior["status"] == "TRANSITIONAL"
    assert old_behavior["intermediate_user_output_allowed"] is False

    repaired = resolve_terminal_continuation(
        report_slot_id=REPORT_SLOT_ID,
        workflow_run_id=RUN_ID,
        workflow_reads=[
            {"state": "ACQUISITION_IN_PROGRESS"},
            {"state": "PUBLICATION_READY"},
        ],
        started_at="2026-09-18T18:28:31+07:00",
        evaluated_at="2026-09-18T18:28:58+07:00",
    )
    assert repaired["status"] == "TERMINAL_SUCCESS"
    assert repaired["resume_same_report_pipeline"] is True
    assert "PRE_RENDER_QA" in repaired["pipeline_resume_steps"]
    assert "POST_RENDER_QA" in repaired["pipeline_resume_steps"]
    assert "SAME_SLOT_DELIVERY_RECEIPT" in repaired["pipeline_resume_steps"]

    historical = evaluate_rolling_natural_acceptance([
        {
            "natural": True,
            "schedule_kind": "chatgpt_scheduler",
            "logical_slot": SLOT,
            "core_acceptance": "PASS",
            "mandatory_visible_report": True,
            "report_slot_id": REPORT_SLOT_ID,
            "occurrence_identity": "natural-1830",
            "report_contract_pass": False,
            "report_slot_fulfilled": False,
            "visible_emitted": False,
            "delivery_proof_valid": False,
        }
    ])
    assert historical["latest_window"][0]["acceptance"] == "FAIL"
