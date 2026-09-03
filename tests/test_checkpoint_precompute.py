from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v3 import precompute_checkpoint as pc
from src.runtime_v3.publish_snapshot import _checkpoint_metadata

ROOT = Path(__file__).resolve().parents[1]
ADAPTIVE_SCHEDULE = "2,7,12,17,22,27,32,37,42,47,52,57 * * * *"


def test_policy_and_workflow_keep_logical_30_precompute_15_and_recovery_only_wakeups() -> None:
    policy = pc._policy()
    schedules = policy["schedules"]
    assert schedules["primary"] == "30 * * * *"
    assert schedules["precompute"] == "15 * * * *"
    assert schedules["adaptive"] == ADAPTIVE_SCHEDULE
    assert policy["precompute"]["lead_minutes"] == 15
    assert policy["precompute"]["target_minute"] == 30
    assert policy["precompute"]["internal_only_silent"] is True
    assert policy["checkpoint_recovery"]["enabled"] is True
    assert policy["checkpoint_recovery"]["wake_interval_minutes"] == 5
    assert policy["checkpoint_recovery"]["never_create_second_checkpoint_authority"] is True

    workflow = (ROOT / ".github" / "workflows" / "v3-runtime.yml").read_text(encoding="utf-8")
    assert 'cron: "30 * * * *"' in workflow
    assert 'cron: "15 * * * *"' in workflow
    assert f'cron: "{ADAPTIVE_SCHEDULE}"' in workflow
    assert 'cron: "0,45 * * * *"' not in workflow
    assert "probe/recovery only" in workflow
    assert "never become a second authority" in workflow
    assert "python -m src.runtime_v3.precompute_checkpoint" in workflow
    assert "runtime_manifest.json" in workflow
    assert '--snapshot-role "${{ steps.cadence.outputs.snapshot_role }}"' in workflow
    assert '--target-checkpoint "${{ steps.cadence.outputs.target_checkpoint_utc }}"' in workflow


def test_precompute_targets_same_hour_30_when_started_before_45_wib() -> None:
    now = datetime(2026, 8, 30, 21, 15, tzinfo=timezone.utc)
    target = pc.target_checkpoint_for_precompute(now)
    assert target == datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)
    delayed = datetime(2026, 8, 30, 21, 35, tzinfo=timezone.utc)
    assert pc.target_checkpoint_for_precompute(delayed) == target


def test_precompute_delayed_to_45_or_later_targets_next_checkpoint() -> None:
    now = datetime(2026, 8, 30, 21, 45, tzinfo=timezone.utc)
    assert pc.target_checkpoint_for_precompute(now) == datetime(2026, 8, 30, 22, 30, tzinfo=timezone.utc)


def test_primary_heartbeat_resolves_most_recent_logical_30() -> None:
    assert pc.current_logical_checkpoint(datetime(2026, 8, 30, 21, 31, tzinfo=timezone.utc)) == datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)
    assert pc.current_logical_checkpoint(datetime(2026, 8, 30, 22, 5, tzinfo=timezone.utc)) == datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)


def test_adaptive_recovery_targets_missing_precompute_before_logical_30() -> None:
    kind, target = pc._adaptive_recovery_target(datetime(2026, 8, 30, 21, 17, tzinfo=timezone.utc))
    assert kind == "PRECOMPUTE"
    assert target == datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)
    kind, target = pc._adaptive_recovery_target(datetime(2026, 8, 30, 21, 27, tzinfo=timezone.utc))
    assert kind == "PRECOMPUTE"
    assert target == datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)


def test_adaptive_recovery_targets_most_recent_missing_primary_after_30() -> None:
    kind, target = pc._adaptive_recovery_target(datetime(2026, 8, 30, 21, 32, tzinfo=timezone.utc))
    assert kind == "CURRENT"
    assert target == datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)
    kind, target = pc._adaptive_recovery_target(datetime(2026, 8, 30, 22, 7, tzinfo=timezone.utc))
    assert kind == "CURRENT"
    assert target == datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)


def test_adaptive_recovery_never_steals_exact_precompute_or_primary_minutes() -> None:
    assert pc._adaptive_recovery_target(datetime(2026, 8, 30, 21, 15, tzinfo=timezone.utc)) == (None, None)
    assert pc._adaptive_recovery_target(datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)) == (None, None)


def _manifest(*, generated: str, source: str = "a" * 40, role: str = pc.PRECOMPUTE_ROLE, target: str | None = "2026-08-30T21:30:00+00:00", complete: bool = True) -> dict:
    return {
        "source_commit": source,
        "generated_at": generated,
        "checkpoint": {
            "snapshot_role": role,
            "target_checkpoint": target,
            "materialization_complete": complete,
        },
    }


def test_primary_skips_only_exact_on_time_same_commit_precompute() -> None:
    target = datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)
    manifest = _manifest(generated="2026-08-30T21:18:00+00:00")
    assert pc._manifest_precompute_valid(manifest, target_utc=target, source_commit="a" * 40) is True
    assert pc._manifest_precompute_valid(manifest, target_utc=target, source_commit="b" * 40) is False
    late = _manifest(generated="2026-08-30T21:31:00+00:00")
    assert pc._manifest_precompute_valid(late, target_utc=target, source_commit="a" * 40) is False
    wrong_target = _manifest(generated="2026-08-30T21:18:00+00:00", target="2026-08-30T22:30:00+00:00")
    assert pc._manifest_precompute_valid(wrong_target, target_utc=target, source_commit="a" * 40) is False
    incomplete = _manifest(generated="2026-08-30T21:18:00+00:00", complete=False)
    assert pc._manifest_precompute_valid(incomplete, target_utc=target, source_commit="a" * 40) is False


def test_checkpoint_satisfaction_accepts_targeted_precompute_or_post_target_same_source_snapshot() -> None:
    target = datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)
    precompute = _manifest(generated="2026-08-30T21:18:00+00:00")
    assert pc._manifest_satisfies_checkpoint(precompute, target_utc=target, source_commit="a" * 40) is True

    workflow_refresh = _manifest(
        generated="2026-08-30T21:34:00+00:00",
        role="ADAPTIVE_OR_MANUAL_REFRESH",
        target=None,
    )
    assert pc._manifest_satisfies_checkpoint(workflow_refresh, target_utc=target, source_commit="a" * 40) is True


def test_checkpoint_satisfaction_rejects_old_wrong_source_or_incomplete_snapshot() -> None:
    target = datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)
    old = _manifest(generated="2026-08-30T21:29:59+00:00", role="ADAPTIVE_OR_MANUAL_REFRESH", target=None)
    assert pc._manifest_satisfies_checkpoint(old, target_utc=target, source_commit="a" * 40) is False
    wrong_source = _manifest(generated="2026-08-30T21:34:00+00:00", source="b" * 40, role="ADAPTIVE_OR_MANUAL_REFRESH", target=None)
    assert pc._manifest_satisfies_checkpoint(wrong_source, target_utc=target, source_commit="a" * 40) is False
    incomplete = _manifest(generated="2026-08-30T21:34:00+00:00", role="ADAPTIVE_OR_MANUAL_REFRESH", target=None, complete=False)
    assert pc._manifest_satisfies_checkpoint(incomplete, target_utc=target, source_commit="a" * 40) is False


def test_runtime_manifest_exposes_checkpoint_target_without_claiming_fact_freshness() -> None:
    generated = datetime(2026, 8, 30, 21, 18, tzinfo=timezone.utc)
    checkpoint = _checkpoint_metadata(
        generated,
        snapshot_role=pc.PRECOMPUTE_ROLE,
        target_checkpoint="2026-08-30T21:30:00+00:00",
        target_visible_mode="NORMAL_DEEP_REVIEW",
    )
    assert checkpoint["snapshot_role"] == pc.PRECOMPUTE_ROLE
    assert checkpoint["precomputed"] is True
    assert checkpoint["generated_before_or_at_target"] is True
    assert checkpoint["materialization_complete"] is True
    assert checkpoint["target_visible_mode"] == "NORMAL_DEEP_REVIEW"
    assert checkpoint["target_checkpoint"] == "2026-08-30T21:30:00+00:00"
