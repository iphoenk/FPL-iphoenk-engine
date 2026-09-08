from __future__ import annotations

import json
import re
from pathlib import Path

from src.runtime_v6.workflow_control import load_policy, resolve_prefetch


def test_historical_backfill_reuses_issue_431_report_prefetch_control_plane():
    policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    prefetch = policy["report_prefetch"]
    assert prefetch["control_issue_number"] == 431
    assert prefetch["issue_comment_command"] == "/v6-report-prefetch"
    assert "historical_backfill" in prefetch["supported_report_kinds"]
    assert prefetch["historical_backfill"] == {
        "scope": "mini_league",
        "completed_gws_allowed": True,
        "current_post_deadline_gw_allowed": True,
        "future_gws_allowed": False,
        "requires_gw_range": True,
        "cohort_semantics": "CURRENT_COHORT_HISTORY",
    }
    assert prefetch["independent_cron"] is False
    assert policy["governance"]["historical_backfill_reuses_report_prefetch_control_plane"] is True


def test_workflow_accepts_governed_range_and_routes_only_historical_mode():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    policy = load_policy()
    env, summary = resolve_prefetch(
        policy,
        event_name="workflow_dispatch",
        dispatch_values={
            "report_kind": "historical_backfill",
            "logical_slot": "",
            "scope": "mini_league",
            "gw_from": "1",
            "gw_to": "3",
            "force": "false",
        },
    )

    assert summary["report_kind"] == "historical_backfill"
    assert summary["scope"] == ["mini_league"]
    assert env["V6_PREFETCH_GW_FROM"] == "1"
    assert env["V6_PREFETCH_GW_TO"] == "3"
    assert 'python -m src.runtime_v6.workflow_control resolve-prefetch' in workflow
    assert 'python -m src.runtime_v6.historical_backfill' in workflow
    assert '--gw-from "$V6_PREFETCH_GW_FROM"' in workflow
    assert '--gw-to "$V6_PREFETCH_GW_TO"' in workflow
    assert 'startsWith(github.event.comment.body, \'/v6-report-prefetch\')' in workflow
    assert 'RUNTIME_BRANCH: runtime-data-v6' in workflow
    assert 'runtime-data-v3' not in workflow
    assert 'runtime-data-v4' not in workflow
    assert 'runtime-data-v5' not in workflow


def test_historical_backfill_adds_no_scheduler_or_second_publisher():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    policy = load_policy()
    workflow_crons = re.findall(r'^\s+- cron: "([^"]+)"$', workflow, flags=re.MULTILINE)
    assert policy["scheduled_crons_utc"] == []
    assert policy["github_natural_schedule"]["enabled"] is False
    assert workflow_crons == policy["github_natural_schedule"]["former_crons_utc"]
    assert policy["report_prefetch"]["independent_cron"] is False
    assert workflow.count('\n  publish:\n') == 1
    assert workflow.count('Publish atomic V6 runtime snapshot') == 1
    assert workflow.count('"historical_backfill.json"') == 1


def test_historical_command_documented_as_factual_only():
    doc = Path("docs/V6_HISTORICAL_MINI_LEAGUE_BACKFILL.md").read_text(encoding="utf-8")
    assert "/v6-report-prefetch report_kind=historical_backfill gw_from=1 gw_to=3 scope=mini_league reason=icon_plus_history_backfill" in doc
    assert "CURRENT_COHORT_HISTORY" in doc
    assert "event_points.json" in doc
    assert "entry_history.json" in doc
    assert "manager_history.json" in doc
    assert "runtime-data-v6" in doc
    assert "ownership/EO" in doc
    assert "reconstructed cohort rank" in doc
    assert "V6 does not" in doc


def test_production_entrypoint_is_compatibility_shim_to_factual_runtime():
    shim = Path("src/runtime_v6/historical_backfill.py").read_text(encoding="utf-8")
    facts = Path("src/runtime_v6/historical_facts.py").read_text(encoding="utf-8")
    assert "from .historical_facts import" in shim
    assert "HistoricalBackfillService" in facts
    assert "LEGACY_ANALYTICAL_FILENAMES" in facts
    assert "statistics" not in facts
