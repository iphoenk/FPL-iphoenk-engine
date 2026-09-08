from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.runtime_control import (
    CHATGPT_GREEN_STREAK,
    CHATGPT_SCHEDULER_AUTHORITY,
    CHATGPT_SCHEDULER_EPOCH,
    build_operational_slots,
    build_runtime_control,
)
from src.runtime_v6.schedule_policy import SCHEDULE_POLICY, load_schedule_policy, scheduler_proof_telemetry


def test_runtime_scheduler_constants_are_derived_from_single_policy() -> None:
    payload = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    authority = payload["scheduler_authority"]
    assert CHATGPT_SCHEDULER_AUTHORITY == authority["runtime_authority_id"]
    assert CHATGPT_SCHEDULER_EPOCH == authority["health_epoch"]
    assert CHATGPT_GREEN_STREAK == authority["green_after_consecutive_slots"]
    assert SCHEDULE_POLICY.cadence_minutes == authority["cadence_minutes"]
    assert SCHEDULE_POLICY.proof_fresh_after_minutes == authority["proof_fresh_after_minutes"]
    assert SCHEDULE_POLICY.proof_stale_after_minutes == authority["proof_stale_after_minutes"]


def test_policy_loader_fails_closed_if_github_scheduler_is_reenabled(tmp_path: Path) -> None:
    payload = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    payload["github_natural_schedule"]["enabled"] = True
    path = tmp_path / "schedule_policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        load_schedule_policy(path)
    except ValueError as exc:
        assert "must_be_disabled" in str(exc)
    else:
        raise AssertionError("policy loader accepted GitHub scheduler authority")


def test_scheduler_proof_age_thresholds_are_policy_driven() -> None:
    proof = "2026-09-08T10:31:00+00:00"
    fresh = scheduler_proof_telemetry(
        proof,
        now=datetime(2026, 9, 8, 11, 40, tzinfo=timezone.utc),
    )
    late = scheduler_proof_telemetry(
        proof,
        now=datetime(2026, 9, 8, 12, 20, tzinfo=timezone.utc),
    )
    stale = scheduler_proof_telemetry(
        proof,
        now=datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc),
    )
    assert fresh["scheduler_proof_freshness"] == "FRESH"
    assert fresh["scheduler_proof_health"] == "GREEN"
    assert late["scheduler_proof_freshness"] == "LATE"
    assert late["scheduler_proof_health"] == "AMBER"
    assert stale["scheduler_proof_freshness"] == "STALE"
    assert stale["scheduler_proof_health"] == "RED"


def test_ledger_exposes_proof_age_without_fabricating_missing_slot() -> None:
    first = build_runtime_control(
        {},
        now=datetime(2026, 9, 8, 10, 31, tzinfo=timezone.utc),
        event_name="issue_comment",
        run_id="scheduler-proof",
        schedule_kind="chatgpt_scheduler",
        logical_slot="2026-09-08T17:00:00+07:00",
    )
    ledger = build_operational_slots({}, first)
    assert len(ledger["slots"]) == 1
    assert ledger["summary"]["last_chatgpt_scheduler_proof_at"] == first["cycle_observed_at"]

    observer = {
        "cycle_observed_at": "2026-09-08T12:50:00+00:00",
        "scheduler_interval_minutes": SCHEDULE_POLICY.cadence_minutes,
        "counts_as_completed_operational_slot": False,
        "expected_cycle_at": None,
    }
    observed = build_operational_slots(ledger, observer)
    assert len(observed["slots"]) == 1
    assert observed["summary"]["scheduler_proof_freshness"] == "STALE"
    assert observed["summary"]["scheduler_proof_health"] == "RED"
    assert observed["summary"]["missing_operational_slots"] == 0
    assert observed["governance"]["scheduler_proof_age_does_not_fabricate_slots"] is True
