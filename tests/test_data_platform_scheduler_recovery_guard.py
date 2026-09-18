import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.runtime_v6.scheduler_recovery import decide_safe_recovery
from src.runtime_v6.wave3_proof import NATURAL_EVENT_NAME, NATURAL_SCHEDULE_KIND
from src.runtime_v6.domains.control_plane.workflow_control import (
    WorkflowControlError,
    authorize_dispatch,
    load_policy,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v6-core-recovery-guard.yml"
CONFIG = ROOT / "config" / "v6" / "scheduler_recovery.json"
SCHEDULE_POLICY = ROOT / "config" / "v6" / "schedule_policy.json"

NOW = datetime(2026, 9, 14, 14, 55, tzinfo=timezone.utc)


def _critical() -> dict:
    return {
        "state": "CRITICAL",
        "reason_code": "SCHEDULER_PROOF_CRITICAL_AGE",
        "proof_age_minutes": 175.0,
        "proof_is_authoritative": True,
    }


def test_recovery_noops_when_watchdog_is_not_critical():
    result = decide_safe_recovery({"state": "WARNING", "reason_code": "SCHEDULER_PROOF_WARNING_AGE"}, [], now=NOW)
    assert result["should_recover"] is False
    assert result["reason_code"] == "WATCHDOG_NOT_CRITICAL"


def test_recovery_dispatches_only_after_critical_with_no_blocker():
    result = decide_safe_recovery(_critical(), [], now=NOW)
    assert result["should_recover"] is True
    assert result["decision"] == "DISPATCH_MANUAL_RECOVERY"
    assert result["recovery_mode"] == "manual_recovery"
    assert result["recovery_is_scheduler_proof"] is False
    assert result["recovery_counts_as_natural_wave3_slot"] is False


def test_active_ingestion_blocks_recovery():
    result = decide_safe_recovery(
        _critical(),
        [{"id": 123, "status": "in_progress", "event": "issues", "created_at": "2026-09-14T14:50:00Z"}],
        now=NOW,
    )
    assert result["should_recover"] is False
    assert result["reason_code"] == "INGESTION_ALREADY_ACTIVE"


def test_recent_manual_dispatch_is_a_cooldown_blocker():
    result = decide_safe_recovery(
        _critical(),
        [{"id": 124, "status": "completed", "event": "workflow_dispatch", "created_at": "2026-09-14T14:20:00Z"}],
        now=NOW,
    )
    assert result["should_recover"] is False
    assert result["reason_code"] == "RECOVERY_COOLDOWN_ACTIVE"


def test_recent_governed_core_event_gets_settle_window_before_recovery():
    result = decide_safe_recovery(
        _critical(),
        [{"id": 125, "status": "completed", "event": "issues", "created_at": "2026-09-14T14:45:00Z"}],
        now=NOW,
    )
    assert result["should_recover"] is False
    assert result["reason_code"] == "RECENT_GOVERNED_CORE_EVENT_SETTLING"


def test_recovery_workflow_is_dispatch_only_not_a_second_natural_scheduler():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cron: '55 * * * *'" in text
    assert "contents: read" in text
    assert "actions: write" in text
    assert "contents: write" not in text
    assert "issues: write" not in text
    assert "v6-runtime-publisher" not in text
    assert "FPL_MASTER_SLOT" not in text
    assert "inputs[mode]=manual_recovery" in text
    assert "inputs[reason]=WAVE2_SAFE_RECOVERY_CRITICAL" in text
    assert "inputs[confirm]=RECOVER_V6" in text
    assert "actions/workflows/${RECOVERY_WORKFLOW}/dispatches" in text


def test_recovery_policy_cannot_claim_scheduler_or_wave3_proof():
    recovery = json.loads(CONFIG.read_text(encoding="utf-8"))
    schedule = json.loads(SCHEDULE_POLICY.read_text(encoding="utf-8"))
    assert recovery["role"] == "SAFE_RECOVERY_ONLY"
    assert recovery["normal_scheduler_authority"] == "CHATGPT_FPL_MASTER_MONITOR"
    assert recovery["recovery_mode"] == "manual_recovery"
    assert recovery["recovery_counts_as_scheduler_proof"] is False
    assert recovery["recovery_counts_as_natural_wave3_slot"] is False
    assert recovery["may_edit_fpl_master_slot_title"] is False
    assert schedule["github_natural_schedule"]["enabled"] is False
    assert schedule["manual_recovery"]["counts_as_completed_operational_slot"] is False
    assert schedule["manual_recovery"]["counts_as_completed_scheduled_slot"] is False
    assert NATURAL_EVENT_NAME == "issues"
    assert NATURAL_SCHEDULE_KIND == "chatgpt_scheduler"

def test_recovery_guard_bot_can_dispatch_only_exact_governed_manual_recovery():
    policy = load_policy()

    assert authorize_dispatch(
        policy,
        actor="github-actions[bot]",
        repository_owner="iphoenk",
        mode="manual_recovery",
        reason="WAVE2_SAFE_RECOVERY_CRITICAL",
        manual_confirm="RECOVER_V6",
    ) == "manual_recovery"

    with pytest.raises(WorkflowControlError):
        authorize_dispatch(
            policy,
            actor="github-actions[bot]",
            repository_owner="iphoenk",
            mode="manual_recovery",
            reason="UNSCOPED_RECOVERY",
            manual_confirm="RECOVER_V6",
        )

    with pytest.raises(WorkflowControlError):
        authorize_dispatch(
            policy,
            actor="github-actions[bot]",
            repository_owner="iphoenk",
            mode="master_orchestrated",
            reason="WAVE2_SAFE_RECOVERY_CRITICAL",
            manual_confirm="RECOVER_V6",
        )


def test_recovery_guard_dispatch_identity_is_config_owned_and_workflow_contract_is_exact():
    recovery = json.loads(CONFIG.read_text(encoding="utf-8"))
    text = WORKFLOW.read_text(encoding="utf-8")

    assert recovery["recovery_dispatch_actor"] == "github-actions[bot]"
    assert recovery["recovery_reason"] == "WAVE2_SAFE_RECOVERY_CRITICAL"
    assert recovery["recovery_confirmation"] == "RECOVER_V6"
    assert "inputs[mode]=manual_recovery" in text
    assert "inputs[reason]=WAVE2_SAFE_RECOVERY_CRITICAL" in text
    assert "inputs[confirm]=RECOVER_V6" in text
