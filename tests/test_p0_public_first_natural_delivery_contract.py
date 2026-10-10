"""P0 public-first natural delivery regression contracts.

These static/semantic guards complement runtime V6 public-prefetch acceptance
and exact-occurrence terminality tests. They do not claim natural delivery.
"""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / ".github/workflows/fpl-master-occurrence-orchestrator.yml"
RUNNER = ROOT / "src/engines/v12_integrated_report_runner.py"
RENDER = ROOT / "src/engines/v12_report_orchestration.py"
QA = ROOT / "src/engines/v12_deep_delivery.py"


def test_match_is_a_governed_occurrence_not_a_price_alias():
    workflow = ORCHESTRATOR.read_text(encoding="utf-8")
    assert '"MATCH": "match_mode"' in workflow
    assert '"MATCH": "match.json"' in workflow
    assert '"DEEP", "PRICE", "MATCH"' in workflow
    assert "latest/${SERVING_FILE}?ref=main" in workflow
    assert '"latest-mode.json"' in workflow
    assert 'latest_mode.get("report_mode") == mode' in workflow
    assert 'latest_mode.get("report_slot") == slot' in workflow
    assert 'latest_mode.get("occurrence_id") == occurrence_id' in workflow
    assert 'mode in {"PRICE", "MATCH"}' in workflow
    assert "generated_at >= report_slot" in workflow
    assert "report_slot exceeds bounded scheduler skew" in workflow


def test_owner_audit_reason_is_accepted_but_cannot_bypass_slot_gate():
    workflow = ORCHESTRATOR.read_text(encoding="utf-8")
    assert '"official_deadline", "force", "reason"' in workflow
    assert 'reason must be bounded audit metadata' in workflow
    assert "DEEP occurrence is not an exact governed deadline checkpoint" in workflow
    assert "PRICE occurrence must bind to 23:30 Europe/London" in workflow


def test_top10_selection_respects_official_ties():
    source = RUNNER.read_text(encoding="utf-8")
    ast.parse(source)
    assert "enumerate(ordered[:top10_count], start=1)" in source
    assert '"standing_position": standing_position' in source
    assert '"rank": rank' in source
    assert 'if rank <= min(' not in source
    qa = QA.read_text(encoding="utf-8")
    ast.parse(qa)
    assert "top10_positions != expected_top10" in qa
    assert "top10_ranks != sorted(top10_ranks)" in qa
    assert "len(set(top10_ids)) != len(top10_ids)" in qa
    render = RENDER.read_text(encoding="utf-8")
    assert 'r.get("standing_position") == 10' in render


def test_private_auth_failure_is_not_public_report_failure():
    from src.runtime_v6.domains.report_plane.report_prefetch import (
        public_report_continuation_eligible,
    )

    def job(name: str, conclusion: str, failed_step: str = "") -> dict:
        return {
            "name": name,
            "conclusion": conclusion,
            "steps": ([{"name": failed_step, "conclusion": "failure"}]
                      if failed_step else []),
        }

    public = [
        job("collect", "success"),
        job("publish", "success"),
        job("orchestration-fulfillment", "success"),
        job("route-visible-report", "skipped"),
    ]
    auth_failed = job(
        "private_personal_publish", "failure",
        "Refresh authenticated current-team state in isolated private plane",
    )
    assert public_report_continuation_eligible([*public, auth_failed])
    assert not public_report_continuation_eligible([
        *[j if j["name"] != "publish" else job("publish", "failure")
          for j in public], auth_failed,
    ])
