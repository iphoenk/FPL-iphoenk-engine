from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.runtime_v6.adapters import collect_price_predictor
from src.runtime_v6.consumer import _control_failures
from src.runtime_v6.registry import load_registry
from src.runtime_v6.runtime_control import build_runtime_control, scheduled_slot_already_completed
from src.runtime_v6.workflow_control import (
    WorkflowControlError,
    authorize_dispatch,
    authorize_issue,
    classify_invocation,
    load_policy,
    resolve_prefetch,
)

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "config" / "v6" / "source_overrides.json"
ACTIVATION = ROOT / "config" / "v6" / "source_activation.json"
WORKFLOW = ROOT / ".github" / "workflows" / "v6-natural-data-ingestion.yml"


def _price_source() -> dict:
    return {
        "id": "official_price_predictor",
        "name": "Official FPL Price Predictor",
        "category": "official_model_signal",
        "adapter": "official_price_predictor",
        "critical": True,
        "independence_group": "official_fpl",
        "entity_scopes": ["PLAYER", "TEAM"],
        "depends_on": ["official_fpl"],
        "fields": ["id", "price_change_percent", "price_change_projections"],
        "derived_from": "official_fpl.bootstrap",
    }


def test_price_predictor_current_cycle_is_reported_as_derived_not_reused() -> None:
    upstream = {
        "health": "GREEN",
        "effective_state": "LIVE_UNCHANGED",
        "official": {
            "bootstrap": {
                "elements": [
                    {
                        "id": 1,
                        "price_change_percent": 83.4,
                        "price_change_projections": {"direction": "RISE"},
                    }
                ]
            }
        },
    }
    payload = collect_price_predictor(_price_source(), upstream)
    assert payload["health"] == "GREEN"
    assert payload["effective_state"] == "LIVE_DERIVED"
    assert payload["current_run_action"] == "DERIVED"
    assert payload["governance"]["current_run_action_is_truthful"] is True


def test_price_predictor_last_good_fallback_is_reported_as_cache() -> None:
    previous = {
        "data": {"players": [{"id": 1, "price_change_percent": 10, "price_change_projections": {}}]},
        "coverage": {"covered_player_count": 1},
    }
    payload = collect_price_predictor(
        _price_source(),
        {"health": "AMBER", "effective_state": "MISSING", "official": {"bootstrap": {}}},
        previous,
    )
    assert payload["current_run_action"] == "LAST_GOOD_CACHE"
    assert payload["effective_state"] == "STALE_CACHE"


def test_report_prefetch_is_authoritative_but_never_completes_core_operational_slot() -> None:
    previous = {
        "runtime_control": {
            "last_operational_cycle_at": "2026-09-07T09:00:00+00:00",
            "last_authoritative_cycle_at": "2026-09-07T09:00:00+00:00",
            "last_authoritative_snapshot_at": "2026-09-07T09:00:00+00:00",
        }
    }
    control = build_runtime_control(
        previous,
        now=datetime(2026, 9, 7, 10, 30, tzinfo=timezone.utc),
        event_name="issue_comment",
        run_id="123",
        schedule_kind="report_prefetch",
    )
    assert control["health"] == "GREEN"
    assert control["authoritative_runtime_snapshot"] is True
    assert control["report_prefetch"] is True
    assert control["counts_as_completed_report_slot"] is True
    assert control["counts_as_completed_operational_slot"] is False
    assert control["last_operational_cycle_at"] == "2026-09-07T09:00:00+00:00"
    assert control["last_authoritative_snapshot_at"] == "2026-09-07T10:30:00+00:00"
    assert _control_failures(control) == []

    assert scheduled_slot_already_completed(
        {"runtime_control": control},
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 7, 10, 53, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="recovery",
        schedule_expression="53 * * * *",
    ) is False


def test_report_prefetch_policy_has_separate_snapshot_and_operational_authority() -> None:
    policy = load_policy()
    prefetch = policy["report_prefetch"]
    assert prefetch["authoritative_runtime_snapshot"] is True
    assert prefetch["counts_as_completed_operational_slot"] is False
    assert prefetch["counts_as_completed_report_slot"] is True
    assert "issue_comment:report_prefetch" in policy["governance"]["authoritative_runtime_triggers"]
    assert "issue_comment:report_prefetch" not in policy["governance"]["operational_slot_completing_triggers"]


def test_workflow_control_authorizes_and_classifies_governed_triggers() -> None:
    policy = load_policy()
    assert authorize_dispatch(
        policy,
        actor="owner",
        repository_owner="owner",
        mode="report_prefetch",
        reason="deadline report",
    ) == "report_prefetch"
    assert authorize_issue(
        policy,
        actor="owner",
        repository_owner="owner",
        issue_number=431,
        comment_body="/v6-report-prefetch report_kind=full_master logical_slot=2026-09-07T12:30:00+07:00 reason=test",
    ) == "report_prefetch"
    assert classify_invocation(
        policy,
        event_name="issue_comment",
        event={"comment": {"body": "/v6-report-prefetch report_kind=full_master"}},
    ) == "report_prefetch"


def test_workflow_control_prefetch_validation_is_fail_closed() -> None:
    policy = load_policy()
    env, summary = resolve_prefetch(
        policy,
        event_name="workflow_dispatch",
        dispatch_values={
            "report_kind": "full_master",
            "logical_slot": "2026-09-07T12:30:00+07:00",
            "scope": "",
            "gw_from": "",
            "gw_to": "",
            "force": "false",
        },
    )
    assert summary["report_kind"] == "full_master"
    assert env["V6_PREFETCH_FORCE"] == "false"

    with pytest.raises(WorkflowControlError):
        resolve_prefetch(
            policy,
            event_name="workflow_dispatch",
            dispatch_values={
                "report_kind": "ad_hoc",
                "logical_slot": "2026-09-07T12:30:00+07:00",
                "scope": "",
                "force": "false",
            },
        )


def test_override_layer_is_temporary_active_only_and_bounded() -> None:
    overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    activation = json.loads(ACTIVATION.read_text(encoding="utf-8"))
    override_ids = set(overrides["sources"])
    inactive = set(activation["disabled_sources"]) | set(activation["reference_only_sources"])
    assert overrides["schema_version"] == 3
    assert overrides["policy"]["role"] == "TEMPORARY_REPAIR_ONLY"
    assert len(override_ids) <= int(overrides["policy"]["max_active_overrides"])
    assert not override_ids.intersection(inactive)
    assert set(overrides["lifecycle"]) == override_ids
    assert all(row["temporary"] is True for row in overrides["lifecycle"].values())
    assert all(row["reason"] for row in overrides["lifecycle"].values())
    assert all(row["review_by"] for row in overrides["lifecycle"].values())

    registry = load_registry()
    lifecycle = registry["override_lifecycle"]
    assert lifecycle["role"] == "TEMPORARY_REPAIR_ONLY"
    assert lifecycle["active_override_count"] == len(override_ids)
    assert lifecycle["inactive_source_overrides"] == []


def test_production_workflow_delegates_control_plane_to_tested_module() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m src.runtime_v6.workflow_control authorize-dispatch" in text
    assert "python -m src.runtime_v6.workflow_control authorize-issue" in text
    assert "python -m src.runtime_v6.workflow_control classify" in text
    assert "python -m src.runtime_v6.workflow_control resolve-prefetch" in text
    assert "Apply V6 report-prefetch runtime control" in text
    assert "steps.scheduler.outputs.kind == 'report_prefetch'" in text
