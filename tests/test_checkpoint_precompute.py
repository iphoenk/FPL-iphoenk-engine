from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v3 import precompute_checkpoint as pc
from src.runtime_v3.publish_snapshot import _checkpoint_metadata

ROOT = Path(__file__).resolve().parents[1]


def test_policy_and_workflow_keep_logical_30_but_precompute_at_15() -> None:
    policy = pc._policy()
    schedules = policy["schedules"]
    assert schedules["primary"] == "30 * * * *"
    assert schedules["precompute"] == "15 * * * *"
    assert schedules["adaptive"] == "0,45 * * * *"
    assert policy["precompute"]["lead_minutes"] == 15
    assert policy["precompute"]["target_minute"] == 30
    assert policy["precompute"]["internal_only_silent"] is True

    workflow = (ROOT / ".github" / "workflows" / "v3-runtime.yml").read_text(encoding="utf-8")
    assert 'cron: "30 * * * *"' in workflow
    assert 'cron: "15 * * * *"' in workflow
    assert 'cron: "0,45 * * * *"' in workflow
    assert 'cron: "0,15,45 * * * *"' not in workflow
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


def test_primary_skips_only_exact_on_time_same_commit_precompute() -> None:
    target = datetime(2026, 8, 30, 21, 30, tzinfo=timezone.utc)
    manifest = {
        "source_commit": "a" * 40,
        "generated_at": "2026-08-30T21:18:00+00:00",
        "checkpoint": {
            "snapshot_role": pc.PRECOMPUTE_ROLE,
            "target_checkpoint": target.isoformat(),
            "materialization_complete": True,
        },
    }
    assert pc._manifest_precompute_valid(manifest, target_utc=target, source_commit="a" * 40) is True
    assert pc._manifest_precompute_valid(manifest, target_utc=target, source_commit="b" * 40) is False
    late = {**manifest, "generated_at": "2026-08-30T21:31:00+00:00"}
    assert pc._manifest_precompute_valid(late, target_utc=target, source_commit="a" * 40) is False
    wrong_target = {**manifest, "checkpoint": {**manifest["checkpoint"], "target_checkpoint": "2026-08-30T22:30:00+00:00"}}
    assert pc._manifest_precompute_valid(wrong_target, target_utc=target, source_commit="a" * 40) is False


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
