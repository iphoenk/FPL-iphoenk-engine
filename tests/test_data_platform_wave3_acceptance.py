from __future__ import annotations

from src.runtime_v6.wave3_acceptance import (
    WAVE3_CHAOS_SCENARIOS,
    build_slot_lifecycle,
    evaluate_natural_core_slot,
    run_controlled_chaos_acceptance,
)


ACCEPTANCE_EPOCH = "2026-09-14T09:15:25+00:00"


def _runtime_control(**overrides):
    payload = {
        "schema_version": 6,
        "health": "GREEN",
        "event_name": "issues",
        "schedule_kind": "chatgpt_scheduler",
        "run_id": "34828374430",
        "chatgpt_scheduler": True,
        "manual_recovery": False,
        "report_prefetch": False,
        "counts_as_completed_operational_slot": True,
        "expected_cycle_at": "2026-09-14T09:00:00+00:00",
        "cycle_observed_at": "2026-09-14T09:31:12.102704+00:00",
        "missed_cycle": False,
        "duplicate_scheduled_cycle": False,
        "out_of_order_scheduled_cycle": False,
    }
    payload.update(overrides)
    return payload


def _manifest(**overrides):
    payload = {
        "generated_at": "2026-09-14T09:31:11.770025+00:00",
        "overall": "GREEN",
        "critical_failures": [],
    }
    payload.update(overrides)
    return payload


def _integrity(**overrides):
    payload = {
        "status": "PASS",
        "candidate_frozen": True,
        "freeze_verified": True,
        "frozen_at": "2026-09-14T09:31:12.795144+00:00",
        "run_id": "34828374430",
        "candidate_generation_id": "34828374430:1:f32a184ba4ad0b82",
        "registry_fingerprint": "7567b0f9a92f2762e94c719b436b79b0bf47826fb8f4a706f6fb64d1b83270aa",
    }
    payload.update(overrides)
    return payload


def _publication(**overrides):
    payload = {
        "runtime_branch": "runtime-data-v6",
        "commit_sha": "4e25ddef0420ac30242b64895b5033ede9a0792c",
        "committed_at": "2026-09-14T09:31:32+00:00",
        "commit_message": "data(v6): atomic hourly snapshot 34828374430 [chatgpt_scheduler] [dedicated_v6_github_app]",
    }
    payload.update(overrides)
    return payload


def test_first_post_wave2_natural_slot_is_countable():
    result = evaluate_natural_core_slot(
        acceptance_epoch=ACCEPTANCE_EPOCH,
        runtime_control=_runtime_control(),
        manifest=_manifest(),
        publish_integrity=_integrity(),
        publication=_publication(),
    )
    assert result["status"] == "PASS", result
    assert result["countable_natural_slot"] is True
    assert result["logical_slot"] == "2026-09-14T09:00:00+00:00"
    assert result["run_id"] == "34828374430"


def test_manual_recovery_never_counts_as_natural_slot():
    result = evaluate_natural_core_slot(
        acceptance_epoch=ACCEPTANCE_EPOCH,
        runtime_control=_runtime_control(
            event_name="workflow_dispatch",
            schedule_kind="manual_recovery",
            chatgpt_scheduler=False,
            manual_recovery=True,
        ),
        manifest=_manifest(),
        publish_integrity=_integrity(),
        publication=_publication(commit_message="data(v6): manual recovery snapshot 34828374430"),
    )
    assert result["countable_natural_slot"] is False


def test_report_prefetch_never_counts_as_natural_slot():
    result = evaluate_natural_core_slot(
        acceptance_epoch=ACCEPTANCE_EPOCH,
        runtime_control=_runtime_control(
            event_name="issue_comment",
            schedule_kind="report_prefetch",
            chatgpt_scheduler=False,
            report_prefetch=True,
            counts_as_completed_operational_slot=False,
        ),
        manifest=_manifest(),
        publish_integrity=_integrity(),
        publication=_publication(commit_message="data(v6): report prefetch snapshot 34828374430"),
    )
    assert result["countable_natural_slot"] is False


def test_duplicate_or_failed_integrity_never_counts():
    duplicate = evaluate_natural_core_slot(
        acceptance_epoch=ACCEPTANCE_EPOCH,
        runtime_control=_runtime_control(duplicate_scheduled_cycle=True),
        manifest=_manifest(),
        publish_integrity=_integrity(),
        publication=_publication(),
    )
    assert duplicate["countable_natural_slot"] is False

    corrupt = evaluate_natural_core_slot(
        acceptance_epoch=ACCEPTANCE_EPOCH,
        runtime_control=_runtime_control(),
        manifest=_manifest(),
        publish_integrity=_integrity(status="FAIL", freeze_verified=False),
        publication=_publication(),
    )
    assert corrupt["countable_natural_slot"] is False


def test_pre_epoch_slot_never_counts_even_if_green():
    result = evaluate_natural_core_slot(
        acceptance_epoch=ACCEPTANCE_EPOCH,
        runtime_control=_runtime_control(cycle_observed_at="2026-09-14T09:14:59+00:00"),
        manifest=_manifest(),
        publish_integrity=_integrity(),
        publication=_publication(),
    )
    assert result["countable_natural_slot"] is False
    assert "after_acceptance_epoch" in result["failures"]


def test_slot_lifecycle_persists_factual_provenance_without_fake_validation_time():
    record = build_slot_lifecycle(
        trigger_observed_at="2026-09-14T16:29:59+07:00",
        runtime_control=_runtime_control(),
        manifest=_manifest(),
        publish_integrity=_integrity(),
        publication=_publication(),
    )
    assert record["logical_slot"] == "2026-09-14T09:00:00+00:00"
    assert record["run_id"] == "34828374430"
    assert record["runtime_branch"] == "runtime-data-v6"
    assert record["stages"]["TRIGGERED"]["status"] == "PASS"
    assert record["stages"]["FROZEN"]["status"] == "PASS"
    assert record["stages"]["INTEGRITY_PASS"]["status"] == "PASS"
    assert record["stages"]["VALIDATED"]["status"] == "PASS"
    assert record["stages"]["VALIDATED"]["at"] is None
    assert record["stages"]["PROMOTED"]["status"] == "PASS"
    assert record["stages"]["PREFETCHED"]["status"] == "N/A"
    assert record["stages"]["DELIVERED"]["status"] == "N/A"


def test_mandatory_wave3_controlled_chaos_matrix_passes():
    result = run_controlled_chaos_acceptance()
    assert result["status"] == "PASS", result
    assert result["scenario_count"] == len(WAVE3_CHAOS_SCENARIOS)
    assert result["required_scenario_count"] == len(WAVE3_CHAOS_SCENARIOS)
    assert result["missing"] == []
    assert result["failed"] == []
    assert set(result["scenarios"]) == set(WAVE3_CHAOS_SCENARIOS)


def test_chaos_matrix_keeps_report_continuity_and_fail_closed_integrity_contracts():
    result = run_controlled_chaos_acceptance()
    assert result["scenarios"]["provider_timeout"]["evidence"] == "PENDING | DIRECT FRESH | REPORT CONTRACT NOT PROVEN"
    assert result["scenarios"]["publisher_rejection"]["evidence"]["last_good_mutated"] is False
    assert result["scenarios"]["malformed_or_corrupt_candidate"]["evidence"]["last_good_mutated"] is False
    assert result["scenarios"]["duplicate_report_prefetch"]["evidence"]["action"] == "RECOVER"
    assert result["scenarios"]["duplicate_report_prefetch"]["evidence"]["report_slot_fulfilled"] is False
    assert result["scenarios"]["auth_not_requested"]["evidence"] == "NOT REQUESTED"
    assert result["governance"]["chaos_does_not_increment_natural_counter"] is True
