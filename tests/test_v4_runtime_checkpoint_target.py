from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.services.runtime_checkpoint_target import (
    LATE_PRECOMPUTE_ROLE,
    PRECOMPUTE_ROLE,
    PRIMARY_FALLBACK_ROLE,
    UNSCOPED_ROLE,
    _event_schedule,
    resolve_runtime_checkpoint_metadata,
)


def test_v4_precompute_at_15_targets_upcoming_logical_30() -> None:
    generated = datetime(2026, 9, 1, 2, 15, 8, tzinfo=timezone.utc)
    meta = resolve_runtime_checkpoint_metadata(generated, event_name="schedule", schedule_expr="15 * * * *")
    assert meta["snapshot_role"] == PRECOMPUTE_ROLE
    assert meta["target_checkpoint"] == "2026-09-01T02:30:00+00:00"
    assert meta["target_checkpoint_local"] == "2026-09-01T09:30:00+07:00"
    assert meta["precomputed"] is True
    assert meta["generated_before_or_at_target"] is True
    assert meta["materialization_complete"] is True
    assert meta["publication_proof"] == "PRESENCE_ON_RUNTIME_BRANCH"


def test_v4_delayed_15_run_keeps_same_target_but_is_not_valid_precompute() -> None:
    generated = datetime(2026, 9, 1, 2, 35, 0, tzinfo=timezone.utc)
    meta = resolve_runtime_checkpoint_metadata(generated, event_name="schedule", schedule_expr="15 * * * *")
    assert meta["snapshot_role"] == LATE_PRECOMPUTE_ROLE
    assert meta["target_checkpoint"] == "2026-09-01T02:30:00+00:00"
    assert meta["precomputed"] is False
    assert meta["generated_before_or_at_target"] is False


def test_v4_primary_30_is_fallback_targeting_current_checkpoint() -> None:
    generated = datetime(2026, 9, 1, 2, 31, 5, tzinfo=timezone.utc)
    meta = resolve_runtime_checkpoint_metadata(generated, event_name="schedule", schedule_expr="30 * * * *")
    assert meta["snapshot_role"] == PRIMARY_FALLBACK_ROLE
    assert meta["target_checkpoint"] == "2026-09-01T02:30:00+00:00"
    assert meta["precomputed"] is False


def test_v4_manual_or_push_runtime_is_unscoped_refresh() -> None:
    generated = datetime(2026, 9, 1, 2, 20, tzinfo=timezone.utc)
    meta = resolve_runtime_checkpoint_metadata(generated, event_name="push", schedule_expr="")
    assert meta["snapshot_role"] == UNSCOPED_ROLE
    assert meta["target_checkpoint"] is None
    assert meta["precomputed"] is False


def test_v4_event_schedule_reads_caller_schedule_from_github_event_path(tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"schedule": "15 * * * *"}), encoding="utf-8")
    assert _event_schedule({"GITHUB_EVENT_PATH": str(event)}) == "15 * * * *"


def test_v4_target_visible_mode_is_resolved_in_wib() -> None:
    # 21:15 UTC = 04:15 WIB next day; target is the governed 04:30 Deep Review.
    generated = datetime(2026, 9, 1, 21, 15, 0, tzinfo=timezone.utc)
    meta = resolve_runtime_checkpoint_metadata(generated, event_name="schedule", schedule_expr="15 * * * *")
    assert meta["target_checkpoint_local"].startswith("2026-09-02T04:30:00")
    assert meta["target_visible_mode"] == "NORMAL_DEEP_REVIEW"
