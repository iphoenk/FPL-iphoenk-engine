from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.runtime_v6.official_fpl_client import OfficialFPLClient
from src.runtime_v6.prefetch_contract import freshness
from src.runtime_v6.workflow_control import WorkflowControlError, load_policy, resolve_prefetch


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/v6-natural-data-ingestion.yml"
POLICY = ROOT / "config/v6/schedule_policy.json"
CONSUMER = ROOT / "config/v6/consumer_context.json"


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class RetrySession:
    def __init__(self):
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse(503)
        return FakeResponse(200, {"ok": True})


def test_official_fpl_client_retries_transient_failure_then_succeeds():
    session = RetrySession()
    client = OfficialFPLClient(
        retries=2,
        backoff_seconds=0,
        session_factory=lambda: session,
    )
    value = client.bootstrap()
    assert value["status"] == "LIVE"
    assert value["attempts"] == 2
    assert value["payload"] == {"ok": True}
    assert session.calls == 2
    telemetry = client.telemetry()
    assert telemetry["request_count"] == 1
    assert telemetry["failed_requests"] == 0


def test_report_prefetch_reuses_existing_control_plane_without_new_scheduler():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    prefetch = policy["report_prefetch"]
    workflow_crons = re.findall(r'^\s+- cron: "([^"]+)"$', workflow, flags=re.MULTILINE)

    assert policy["scheduler_authority"]["kind"] == "CHATGPT_TASK"
    assert policy["scheduled_crons_utc"] == []
    assert policy["github_natural_schedule"]["enabled"] is False
    assert policy["github_natural_schedule"]["workflow_schedule_triggers_removed"] is True
    assert workflow_crons == []
    assert policy["github_natural_schedule"]["former_crons_are_historical_evidence_only"] is True
    assert prefetch["independent_cron"] is False
    assert prefetch["report_driven"] is True
    assert prefetch["control_issue_number"] == policy["master_orchestrated"]["control_issue_number"] == 431
    assert prefetch["issue_comment_command"] == "/v6-report-prefetch"
    assert "/v6-master-acquire" in workflow
    assert "/v6-report-prefetch" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "Run active V6 acquisition cycle" in workflow
    assert "steps.scheduler.outputs.kind != 'report_prefetch'" in workflow
    assert "Run report-driven V6 personal and mini-league prefetch" in workflow
    assert "python -m src.runtime_v6.workflow_control resolve-prefetch" in workflow


def test_0530_is_explicit_no_personal_no_league_control_contract():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    policy = load_policy()
    env, summary = resolve_prefetch(
        policy,
        event_name="workflow_dispatch",
        dispatch_values={
            "report_kind": "05:30_price",
            "logical_slot": "2026-09-07T05:30:00+07:00",
            "scope": "",
            "gw_from": "",
            "gw_to": "",
            "force": "false",
        },
    )

    assert summary["report_kind"] == "05:30_price"
    assert env["V6_PREFETCH_PERSONAL"] == "false"
    assert env["V6_PREFETCH_MINI_LEAGUE"] == "false"
    assert env["V6_PREFETCH_LIVE"] == "false"
    assert policy["report_prefetch"]["independent_cron"] is False
    assert policy["report_prefetch"]["counts_as_completed_operational_slot"] is False
    validator = (ROOT / "src/runtime_v6/production_validate.py").read_text(encoding="utf-8")
    assert 'if report_kind == "05:30_price":' in validator
    assert 'prefetch["telemetry"]["request_count"] == 0' in validator


def test_priority_league_id_is_not_hardcoded_in_executable_v6_code():
    config = json.loads(CONSUMER.read_text(encoding="utf-8"))
    assert config["priority_leagues"][0]["name"] == "ICON+ League"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/runtime_v6").glob("*.py")
    )
    assert 'league_id": 99' not in source
    assert "league_id = 99" not in source
    assert "ICON+ League" not in source


def test_report_prefetch_auth_secrets_are_scoped_to_prefetch_step_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "FPL_SESSION_B64: ${{ secrets.FPL_SESSION_B64 }}" in workflow
    assert "FPL_ACCESS_TOKEN: ${{ secrets.FPL_ACCESS_TOKEN }}" in workflow
    assert "env:\n  RUNTIME_BRANCH" in workflow
    assert "FPL_SESSION_B64" not in workflow.split("jobs:", 1)[0]
    assert "echo \"$FPL_SESSION_B64\"" not in workflow
    assert "set -x" not in workflow


def test_report_prefetch_force_is_governed_and_not_implicit():
    workflow = WORKFLOW.read_text(encoding="utf-8")
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
            "force": "true",
        },
    )

    assert summary["force"] is True
    assert env["V6_PREFETCH_FORCE"] == "true"
    with pytest.raises(WorkflowControlError, match="force must be boolean"):
        resolve_prefetch(
            policy,
            event_name="workflow_dispatch",
            dispatch_values={
                "report_kind": "full_master",
                "logical_slot": "2026-09-07T12:30:00+07:00",
                "scope": "",
                "gw_from": "",
                "gw_to": "",
                "force": "definitely",
            },
        )
    assert '[[ "$V6_PREFETCH_FORCE" == "true" ]] && args+=(--force)' in workflow


def test_report_prefetch_generated_after_target_slot_is_not_fresh():
    slot = datetime(2026, 9, 5, 5, 30, tzinfo=timezone.utc)
    age, is_fresh = freshness(slot + timedelta(seconds=1), slot, 35)
    assert age < 0
    assert is_fresh is False
