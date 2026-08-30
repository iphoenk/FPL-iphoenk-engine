"""Production scheduler and runtime-recovery governance tests."""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WATCHDOG_PATH = ROOT / ".github" / "scripts" / "v4_runtime_watchdog.py"
PRODUCTION_WORKFLOWS = (
    "v4-prediction.yml",
    "fpl-engine-recovery.yml",
    "v4-timing-probe.yml",
)

spec = importlib.util.spec_from_file_location("v4_runtime_watchdog", WATCHDOG_PATH)
assert spec and spec.loader
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)


def _evaluate(age_minutes: float) -> dict:
    now = datetime(2026, 8, 30, 12, 25, tzinfo=timezone.utc)
    published = now.timestamp() - age_minutes * 60
    stamp = datetime.fromtimestamp(published, tz=timezone.utc).isoformat()
    return watchdog.evaluate(
        {"runtime_publish_at": stamp},
        now=now,
        canonical_ref="v4-prediction-engine",
        canonical_sha="a" * 40,
        runtime_branch="runtime-data-v4",
    )


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_01_scheduler_is_the_only_default_branch_master_cron_owner() -> None:
    owners: list[str] = []
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if 'cron: "30 * * * *"' in text and "fpl-engine-core.yml@v4-prediction-engine" in text:
            owners.append(path.name)
    assert owners == ["v4-prediction.yml"]


def test_02_no_duplicate_v4_master_cron_in_recovery_or_timing_probe() -> None:
    assert 'cron: "30 * * * *"' not in _workflow("fpl-engine-recovery.yml")
    assert 'cron: "30 * * * *"' not in _workflow("v4-timing-probe.yml")


def test_03_scheduler_targets_current_canonical_v4_sha() -> None:
    scheduler = _workflow("v4-prediction.yml")
    assert "git ls-remote origin refs/heads/v4-prediction-engine" in scheduler
    assert "ref: ${{ needs.resolve-canonical.outputs.canonical_sha }}" in scheduler
    assert "CANONICAL_V4_SHA=" in scheduler


def test_04_scheduler_production_evaluation_publishes() -> None:
    scheduler = _workflow("v4-prediction.yml")
    assert re.search(r"\bpublish:\s+true\b", scheduler)
    assert "SCHEDULE_TARGET=:30 WIB" in scheduler
    assert "EXECUTION_OBSERVED=" in scheduler


def test_05_recovery_detects_runtime_strictly_older_than_90_minutes() -> None:
    result = _evaluate(90.01)
    assert result["freshness_state"] == "STALE"
    assert result["recovery_required"] is True


def test_06_recovery_does_not_fire_at_or_below_90_minutes() -> None:
    assert _evaluate(60)["freshness_state"] == "FRESH"
    assert _evaluate(60)["recovery_required"] is False
    assert _evaluate(60.01)["freshness_state"] == "DEGRADED"
    assert _evaluate(90)["freshness_state"] == "DEGRADED"
    assert _evaluate(90)["recovery_required"] is False


def test_07_in_progress_production_is_serialized_before_recovery_recheck() -> None:
    recovery = _workflow("fpl-engine-recovery.yml")
    assert "group: fpl-iphoenk-v4-gate" in recovery
    assert "cancel-in-progress: false" in recovery
    assert "Hydrate authoritative runtime publication metadata" in recovery
    assert "needs.freshness.outputs.recovery_required == 'true'" in recovery


def test_08_recovery_preserves_internal_visibility_semantics() -> None:
    recovery = _workflow("fpl-engine-recovery.yml")
    for forbidden in (
        "USER_REPORT",
        "visible_output_authorized",
        "full_visible_report_required",
        "operating_mode",
    ):
        assert forbidden not in recovery
    result = _evaluate(91)
    assert result["visibility_policy_unchanged"] is True
    assert result["recovery_is_evaluation_only"] is True


def test_09_recovery_has_one_engine_path_and_cannot_add_a_second_report_path() -> None:
    recovery = _workflow("fpl-engine-recovery.yml")
    assert recovery.count("fpl-engine-core.yml@v4-prediction-engine") == 1
    assert "src.services.orchestrator" not in recovery
    assert "fantasy.premierleague.com" not in recovery
    assert "USER_REPORT" not in recovery


def test_10_runtime_branch_target_remains_runtime_data_v4() -> None:
    recovery = _workflow("fpl-engine-recovery.yml")
    assert "RUNTIME_BRANCH: runtime-data-v4" in recovery
    result = _evaluate(91)
    assert result["runtime_branch"] == "runtime-data-v4"


def test_11_all_production_capable_dispatchers_share_deterministic_lock() -> None:
    for name in PRODUCTION_WORKFLOWS:
        workflow = _workflow(name)
        assert "group: fpl-iphoenk-v4-gate" in workflow
        assert "cancel-in-progress: false" in workflow


def test_12_workflow_yaml_has_required_github_actions_shape() -> None:
    for name in PRODUCTION_WORKFLOWS:
        workflow = _workflow(name)
        assert workflow.startswith("name:")
        assert re.search(r"^on:\s*$", workflow, re.MULTILINE)
        assert re.search(r"^permissions:\s*$", workflow, re.MULTILINE)
        assert re.search(r"^concurrency:\s*$", workflow, re.MULTILINE)
        assert re.search(r"^jobs:\s*$", workflow, re.MULTILINE)


def test_13_recovery_watchdog_is_off_checkpoint_and_stale_only() -> None:
    recovery = _workflow("fpl-engine-recovery.yml")
    assert 'cron: "7,22,37,52 * * * *"' in recovery
    assert 'cron: "25,55 * * * *"' not in recovery
    assert 'cron: "30 * * * *"' not in recovery
    assert "needs.freshness.outputs.recovery_required == 'true'" in recovery
    assert "ref: ${{ needs.freshness.outputs.canonical_sha }}" in recovery
    assert re.search(r"\bpublish:\s+true\b", recovery)


def test_missing_or_invalid_publish_stamp_requires_recovery() -> None:
    now = datetime(2026, 8, 30, 12, 25, tzinfo=timezone.utc)
    for latest in ({}, {"generated_at": now.isoformat()}, {"runtime_publish_at": "invalid"}):
        result = watchdog.evaluate(
            latest,
            now=now,
            canonical_ref="v4-prediction-engine",
            canonical_sha="b" * 40,
            runtime_branch="runtime-data-v4",
        )
        assert result["freshness_state"] == "STALE"
        assert result["recovery_required"] is True


def test_watchdog_observes_missed_wib_checkpoints() -> None:
    now = datetime(2026, 8, 30, 11, 24, tzinfo=timezone.utc)  # 18:24 WIB
    result = watchdog.evaluate(
        {"runtime_publish_at": "2026-08-30T08:30:38+00:00"},
        now=now,
        canonical_ref="v4-prediction-engine",
        canonical_sha="c" * 40,
        runtime_branch="runtime-data-v4",
    )
    assert result["schedule_target"] == "2026-08-30T17:30:00+07:00"
    assert result["missed_checkpoint_targets"] == [
        "2026-08-30T16:30:00+07:00",
        "2026-08-30T17:30:00+07:00",
    ]
    assert result["recovery_required"] is True


def test_future_runtime_timestamp_fails_safe_as_stale() -> None:
    now = datetime(2026, 8, 30, 12, 25, tzinfo=timezone.utc)
    result = watchdog.evaluate(
        {"runtime_publish_at": "2026-08-30T13:25:00+00:00"},
        now=now,
        canonical_ref="v4-prediction-engine",
        canonical_sha="d" * 40,
        runtime_branch="runtime-data-v4",
    )
    assert result["freshness_state"] == "STALE"
    assert result["recovery_required"] is True
    assert result["reason"] == "RUNTIME_PUBLISH_TIMESTAMP_IN_FUTURE"
