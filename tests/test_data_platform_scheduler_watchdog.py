import json
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.scheduler_watchdog import classify_scheduler_watchdog

ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / ".github" / "workflows" / "v6-scheduler-watchdog.yml"
WATCHDOG_CONFIG = ROOT / "config" / "v6" / "scheduler_watchdog.json"
SCHEDULE_POLICY = ROOT / "config" / "v6" / "schedule_policy.json"


def _control(slot: str = "2026-09-14T11:00:00Z") -> dict:
    return {
        "schedule_kind": "chatgpt_scheduler",
        "chatgpt_scheduler_proof": True,
        "authoritative_runtime_snapshot": True,
        "expected_cycle_at": slot,
    }


def test_watchdog_healthy_inside_warning_threshold():
    result = classify_scheduler_watchdog(
        _control(),
        now=datetime(2026, 9, 14, 12, 20, tzinfo=timezone.utc),
    )
    assert result["state"] == "HEALTHY"
    assert result["reason_code"] == "SCHEDULER_PROOF_FRESH"
    assert result["may_trigger_acquisition"] is False
    assert result["may_publish_runtime"] is False


def test_watchdog_warns_after_90_minutes():
    result = classify_scheduler_watchdog(
        _control(),
        now=datetime(2026, 9, 14, 12, 31, tzinfo=timezone.utc),
    )
    assert result["state"] == "WARNING"
    assert result["reason_code"] == "SCHEDULER_PROOF_WARNING_AGE"


def test_watchdog_is_critical_after_135_minutes():
    result = classify_scheduler_watchdog(
        _control(),
        now=datetime(2026, 9, 14, 13, 16, tzinfo=timezone.utc),
    )
    assert result["state"] == "CRITICAL"
    assert result["reason_code"] == "SCHEDULER_PROOF_CRITICAL_AGE"


def test_prefetch_or_manual_recovery_never_counts_as_core_proof():
    payload = _control()
    payload["schedule_kind"] = "report_prefetch"
    result = classify_scheduler_watchdog(
        payload,
        now=datetime(2026, 9, 14, 11, 5, tzinfo=timezone.utc),
    )
    assert result["state"] == "CRITICAL"
    assert result["reason_code"] == "AUTHORITATIVE_CHATGPT_PROOF_MISSING"


def test_watchdog_workflow_is_monitor_only_and_has_no_runtime_write_authority():
    text = WATCHDOG.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "cron: '50 * * * *'" in text
    assert "contents: read" in text
    assert "actions: read" in text
    assert "issues: write" in text
    assert "contents: write" not in text
    assert "v6-runtime-publisher" not in text
    assert "RECOVER_V6" not in text
    assert "/v6-master-acquire" not in text
    assert "workflow_dispatch" in text
    assert "dispatches_url" not in text
    assert "actions/workflows/v6-natural-data-ingestion.yml/dispatches" not in text


def test_watchdog_config_preserves_chatgpt_as_only_acquisition_scheduler():
    watchdog = json.loads(WATCHDOG_CONFIG.read_text(encoding="utf-8"))
    policy = json.loads(SCHEDULE_POLICY.read_text(encoding="utf-8"))
    assert watchdog["role"] == "MONITORING_ONLY"
    assert watchdog["authority"]["core_scheduler"] == "CHATGPT_FPL_MASTER_MONITOR"
    assert watchdog["authority"]["watchdog_is_scheduler_authority"] is False
    assert watchdog["authority"]["watchdog_may_trigger_acquisition"] is False
    assert watchdog["authority"]["watchdog_may_dispatch_ingestion"] is False
    assert watchdog["authority"]["watchdog_may_publish_runtime"] is False
    assert policy["github_natural_schedule"]["enabled"] is False
    assert policy["governance"]["chatgpt_scheduler_is_only_hourly_authority"] is True
