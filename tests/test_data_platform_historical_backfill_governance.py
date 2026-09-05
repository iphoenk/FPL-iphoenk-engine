from __future__ import annotations

import json
from pathlib import Path


def test_historical_backfill_reuses_issue_431_report_prefetch_control_plane():
    policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    prefetch = policy["report_prefetch"]
    assert prefetch["control_issue_number"] == 431
    assert prefetch["issue_comment_command"] == "/v6-report-prefetch"
    assert "historical_backfill" in prefetch["supported_report_kinds"]
    assert prefetch["historical_backfill"] == {
        "scope": "mini_league",
        "finished_gws_only": True,
        "requires_gw_range": True,
        "cohort_semantics": "CURRENT_COHORT_HISTORY",
    }
    assert prefetch["independent_cron"] is False
    assert policy["governance"]["historical_backfill_reuses_report_prefetch_control_plane"] is True


def test_workflow_accepts_governed_range_and_routes_only_historical_mode():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    assert '"gw_from", "gw_to"' in workflow
    assert 'historical_backfill requires scope=mini_league' in workflow
    assert 'python -m src.runtime_v6.historical_backfill' in workflow
    assert '--gw-from "$V6_PREFETCH_GW_FROM"' in workflow
    assert '--gw-to "$V6_PREFETCH_GW_TO"' in workflow
    assert 'startsWith(github.event.comment.body, \'/v6-report-prefetch\')' in workflow
    assert 'RUNTIME_BRANCH: runtime-data-v6' in workflow
    assert 'runtime-data-v3' not in workflow
    assert 'runtime-data-v4' not in workflow
    assert 'runtime-data-v5' not in workflow


def test_historical_backfill_adds_no_cron_or_second_publisher():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    assert workflow.count('cron: "23 * * * *"') == 1
    assert workflow.count('cron: "53 * * * *"') == 1
    assert workflow.count('\n  publish:\n') == 1
    assert workflow.count('Publish atomic V6 runtime snapshot') == 1
    assert workflow.count('data/v6/health/historical_backfill.json') == 1


def test_historical_command_documented_exactly():
    doc = Path("docs/V6_HISTORICAL_MINI_LEAGUE_BACKFILL.md").read_text(encoding="utf-8")
    assert "/v6-report-prefetch report_kind=historical_backfill gw_from=1 gw_to=3 scope=mini_league reason=icon_plus_history_backfill" in doc
    assert "CURRENT_COHORT_HISTORY" in doc
    assert "reconstructed_current_cohort_rank" in doc
    assert "runtime-data-v6" in doc
