from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v12_integrated_report_runner import (
    IntegratedRunnerError,
    _core_slot_binding,
    _rank20_rows,
    _report_prefetch_binding,
    parse_command,
)


def test_integrated_runner_command_parser_accepts_bound_deep_occurrence():
    parsed = parse_command(
        "/v12-report-run report_mode=DEEP "
        "report_slot=2026-09-21T12:30:00+07:00 checkpoint_time=12:30"
    )
    assert parsed == {
        "report_mode": "DEEP",
        "report_slot": "2026-09-21T12:30:00+07:00",
        "checkpoint_time": "12:30",
    }


@pytest.mark.parametrize(
    "command",
    [
        "/v12-report-run report_mode=PRICE report_slot=2026-09-21T12:30:00+07:00 checkpoint_time=12:30",
        "/v12-report-run report_mode=DEEP checkpoint_time=12:30",
        "/v12-report-run report_mode=DEEP report_slot=2026-09-21T12:30:00+07:00",
        "/v12-report-run report_mode=DEEP report_slot=not-a-time checkpoint_time=12:30",
        "/v12-report-run report_mode=DEEP report_slot=2026-09-21T12:30:00+07:00 checkpoint_time=nope",
    ],
)
def test_integrated_runner_command_parser_rejects_invalid_contract(command):
    with pytest.raises(IntegratedRunnerError):
        parse_command(command)


def test_integrated_runner_rank20_adapter_preserves_exact_visible_schema():
    native = {
        "rows": [
            {
                "element_id": 426,
                "player": "Bruno Fernandes",
                "current_price": 12.0,
                "selected_by_percent": 39.2,
                "direction": "FALL",
                "official_or_provider_progress": -98.8,
                "projected_percent": -104.7,
                "cycles_to_expected_change": 1,
                "estimated_change_date_wib": "2026-09-22T06:00:00+07:00",
                "estimated_change_window": "NEXT_OFFICIAL_CYCLE",
                "prediction_strength": -4,
                "confidence": {"predictor_health": "GREEN"},
                "estimate_source": "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
                "evidence_timestamp": "2026-09-21T06:28:00+07:00",
            }
        ]
    }
    rows = _rank20_rows(native, owned_ids={426})
    assert len(rows) == 1
    row = rows[0]
    assert row["rank"] == 1
    assert row["element_id"] == 426
    assert row["ownership_tag"] == "OWNED"
    assert row["direction"] == "FALL"
    assert row["source"] == "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR"
    assert row["predicted_change_cycle"] == 1
    assert row["eta_human"] == "NEXT_OFFICIAL_CYCLE"
    assert len(row["raw_payload_hash"]) == 64


def test_integrated_runner_source_exposes_every_owner_stage_without_silent_skip():
    source = (
        Path("src/engines/v12_integrated_report_runner.py")
        .read_text(encoding="utf-8")
    )
    required = (
        "CORE_SLOT_BINDING",
        "REPORT_PREFETCH_BINDING",
        "V6_FACTUAL_BINDING",
        "P1.1_XMINS",
        "P1.3_P1.3B_PLAYER_EVENTS",
        "P1.2A_PACKAGE_SEARCH",
        "P1.7_LINEUP_OPTIMIZER",
        "P1.2B_PACKAGE_UTILITY",
        "P1.4_MONTE_CARLO",
        "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
        "CANONICAL_RENDER",
        "PRE_RENDER_QA",
        "POST_RENDER_QA",
        "HUMAN_FACING_QA",
    )
    for owner in required:
        assert owner in source
    assert '"no_silent_stage_skip": True' in source
    assert '"monte_carlo_fabricated": False' in source


def test_integrated_runner_workflow_is_executor_only_and_artifact_bound():
    text = (
        Path(".github/workflows/v12-integrated-report-runner.yml")
        .read_text(encoding="utf-8")
    )
    assert "schedule:" not in text
    assert "startsWith(github.event.comment.body, '/v12-report-run')" in text
    assert "github.event.issue.number == 431" in text
    assert "github.actor == github.repository_owner" in text
    assert "runtime-data-v6" in text
    assert "v12-report-DEEP-${{ github.run_id }}" in text
    assert "report_bundle.json" in text
    assert "report_body.md" in text
    assert "execution_proof.json" in text
    assert "issue title" not in text.lower()



def test_integrated_runner_binds_1230_report_to_1200_same_hour_core_slot():
    result = _core_slot_binding(
        report_slot="2026-09-21T12:30:00+07:00",
        publish_integrity={"logical_slot": "2026-09-21T05:00:00+00:00"},
    )
    assert result["status"] == "PASS"
    assert result["expected_core_slot"] == "2026-09-21T12:00:00+07:00"
    assert result["actual_core_slot_utc"] == "2026-09-21T05:00:00+00:00"

    stale = _core_slot_binding(
        report_slot="2026-09-21T12:30:00+07:00",
        publish_integrity={"logical_slot": "2026-09-21T04:00:00+00:00"},
    )
    assert stale["status"] == "PARTIAL"
    assert stale["reason"] == "CORE_SLOT_MISMATCH"


def test_integrated_runner_requires_exact_full_master_prefetch_occurrence():
    snapshot = {
        "report_kind": "full_master",
        "target_logical_report_slot": "2026-09-21T12:30:00+07:00",
        "personal_requested": True,
        "mini_league_requested": True,
        "live_requested": True,
        "public_core_complete": True,
        "fresh_for_target_report": True,
        "report_prefetch_run_id": "prefetch-1230",
        "generated_at": "2026-09-21T12:25:00+07:00",
    }
    passed = _report_prefetch_binding(
        report_slot="2026-09-21T12:30:00+07:00",
        report_prefetch=snapshot,
    )
    assert passed["status"] == "PASS"
    assert all(passed["checks"].values())

    stale = dict(snapshot)
    stale["target_logical_report_slot"] = "2026-09-21T11:30:00+07:00"
    failed = _report_prefetch_binding(
        report_slot="2026-09-21T12:30:00+07:00",
        report_prefetch=stale,
    )
    assert failed["status"] == "PARTIAL"
    assert "target_report_slot_match" in failed["reason"]
