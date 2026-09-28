import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from zoneinfo import ZoneInfo

from src.engines.v12_precompute_control import (
    PrecomputeControlError,
    evaluate_precompute_request,
)
from src.engines.v12_delivery_schedule import price_checkpoint_for_london_date
from src.runtime_v6.domains.control_plane.workflow_control import (
    WorkflowControlError,
    authorize_dispatch,
    load_policy,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v12-precompute-control.yml"
CONFIG = ROOT / "config" / "delivery" / "v12_precompute_control.json"
WIB = ZoneInfo("Asia/Jakarta")


def test_d_p2_fixed_deep_waits_until_t15_and_preserves_occurrence():
    target = datetime(2026, 9, 27, 12, 30, tzinfo=WIB)
    plan = evaluate_precompute_request(
        "/v12-precompute report_kind=full_master logical_slot=2026-09-27T12:30+07:00 reason=scheduled_deep",
        now=datetime(2026, 9, 27, 11, 30, tzinfo=WIB),
    )
    assert plan.logical_slot == target.isoformat()
    assert plan.release_at == datetime(2026, 9, 27, 12, 15, tzinfo=WIB).isoformat()
    assert plan.freeze_target_at == datetime(2026, 9, 27, 12, 20, tzinfo=WIB).isoformat()
    assert plan.wait_seconds == 45 * 60
    assert plan.counts_as_core_slot is False
    assert plan.advances_scheduler_proof is False
    assert plan.warm_worker_workflow == "v12-p6-warm-worker.yml"
    assert len(plan.occurrence_id) == 64


def test_d_p2_inside_t15_t10_window_dispatches_immediately():
    plan = evaluate_precompute_request(
        "/v12-precompute report_kind=full_master logical_slot=2026-09-27T12:30+07:00 reason=scheduled_deep",
        now=datetime(2026, 9, 27, 12, 16, tzinfo=WIB),
    )
    assert plan.wait_seconds == 0


def test_d_p2_fails_closed_after_freeze_target_or_for_wrong_slot():
    with pytest.raises(PrecomputeControlError):
        evaluate_precompute_request(
            "/v12-precompute report_kind=full_master logical_slot=2026-09-27T12:30+07:00 reason=late",
            now=datetime(2026, 9, 27, 12, 21, tzinfo=WIB),
        )
    with pytest.raises(PrecomputeControlError):
        evaluate_precompute_request(
            "/v12-precompute report_kind=full_master logical_slot=2026-09-27T12:00+07:00 reason=wrong_slot",
            now=datetime(2026, 9, 27, 11, 30, tzinfo=WIB),
        )


def test_d_p2_price_targets_follow_london_dst():
    bst_target = price_checkpoint_for_london_date(datetime(2026, 10, 24).date())
    assert (bst_target.hour, bst_target.minute) == (5, 30)
    bst = evaluate_precompute_request(
        f"/v12-precompute report_kind=05:30_price logical_slot={bst_target.isoformat()} reason=price",
        now=bst_target - timedelta(minutes=60),
    )
    assert bst.logical_slot == bst_target.isoformat()

    gmt_target = price_checkpoint_for_london_date(datetime(2026, 10, 25).date())
    assert (gmt_target.hour, gmt_target.minute) == (6, 30)
    gmt = evaluate_precompute_request(
        f"/v12-precompute report_kind=05:30_price logical_slot={gmt_target.isoformat()} reason=price",
        now=gmt_target - timedelta(minutes=60),
    )
    assert gmt.logical_slot == gmt_target.isoformat()


def test_d_p2_exact_deadline_checkpoint_requires_official_deadline():
    deadline = datetime(2026, 10, 17, 17, 30, tzinfo=WIB)
    target = deadline - timedelta(minutes=15)
    plan = evaluate_precompute_request(
        (
            f"/v12-precompute report_kind=deadline_review logical_slot={target.isoformat()} "
            f"official_deadline={deadline.isoformat()} reason=deadline_checkpoint"
        ),
        now=target - timedelta(minutes=45),
    )
    assert plan.logical_slot == target.isoformat()

    with pytest.raises(PrecomputeControlError):
        evaluate_precompute_request(
            f"/v12-precompute report_kind=deadline_review logical_slot={target.isoformat()} reason=deadline_checkpoint",
            now=target - timedelta(minutes=45),
        )


def test_d_p2_rejects_backfill_and_unbounded_future():
    target = datetime(2026, 9, 27, 12, 30, tzinfo=WIB)
    with pytest.raises(PrecomputeControlError):
        evaluate_precompute_request(
            f"/v12-precompute report_kind=full_master logical_slot={target.isoformat()} reason=past",
            now=target + timedelta(seconds=1),
        )
    with pytest.raises(PrecomputeControlError):
        evaluate_precompute_request(
            f"/v12-precompute report_kind=full_master logical_slot={target.isoformat()} reason=far",
            now=target - timedelta(minutes=66),
        )


def test_d_p2_workflow_is_non_recurring_non_authoritative_and_reuses_v6():
    text = WORKFLOW.read_text(encoding="utf-8")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert "schedule:" not in text
    assert "cron:" not in text
    assert "workflow_run:" not in text
    assert "issue_comment:" in text
    assert "github.actor == github.repository_owner" in text
    assert "cancel-in-progress: false" in text
    assert "actions: write" in text
    assert "contents: write" not in text
    assert "issues: write" not in text
    assert "FPL_MASTER_SLOT" not in text
    assert "src.runtime_v6.domains.acquisition.collector" not in text
    assert "inputs[mode]=report_prefetch" in text
    assert "v6-natural-data-ingestion.yml" not in text  # workflow name comes from governed config/output
    assert config["normal_scheduler_authority"] == "CHATGPT_FPL_MASTER_MONITOR"
    assert config["may_complete_core_operational_slot"] is False
    assert config["may_advance_scheduler_proof"] is False
    assert config["may_acquire_facts_directly"] is False
    assert config["may_publish_runtime_directly"] is False
    assert config["warm_worker_downstream_only"] is True
    assert config["warm_worker_may_advance_scheduler_proof"] is False
    assert config["warm_worker_may_edit_core_issue_title"] is False
    assert "uses: ./.github/workflows/v12-p6-warm-worker.yml" in text


def test_d_p2_bot_dispatch_is_narrowly_authorized_for_report_prefetch_only():
    policy = load_policy()
    assert authorize_dispatch(
        policy,
        actor="github-actions[bot]",
        repository_owner="iphoenk",
        mode="report_prefetch",
        reason="V12_D_P2_PRECOMPUTE",
    ) == "report_prefetch"

    with pytest.raises(WorkflowControlError):
        authorize_dispatch(
            policy,
            actor="github-actions[bot]",
            repository_owner="iphoenk",
            mode="report_prefetch",
            reason="anything_else",
        )
    with pytest.raises(WorkflowControlError):
        authorize_dispatch(
            policy,
            actor="github-actions[bot]",
            repository_owner="iphoenk",
            mode="master_orchestrated",
            reason="V12_D_P2_PRECOMPUTE",
        )
    with pytest.raises(WorkflowControlError):
        authorize_dispatch(
            policy,
            actor="github-actions[bot]",
            repository_owner="iphoenk",
            mode="manual_recovery",
            reason="V12_D_P2_PRECOMPUTE",
            manual_confirm="RECOVER_V6",
        )
