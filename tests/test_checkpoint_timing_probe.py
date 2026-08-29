from pathlib import Path

from src.services.checkpoint_timing_probe import evaluate_timing_probe


ROOT = Path(__file__).resolve().parents[1]


def _bootstrap(current_deadline: str, *, next_deadline: str | None = None) -> dict:
    events = [
        {
            "id": 2,
            "is_current": True,
            "is_next": False,
            "finished": False,
            "deadline_time": current_deadline,
        }
    ]
    if next_deadline:
        events.append(
            {
                "id": 3,
                "is_current": False,
                "is_next": True,
                "finished": False,
                "deadline_time": next_deadline,
            }
        )
    return {"events": events}


def test_probe_runs_full_engine_for_1700_final_review_of_1830_deadline():
    result = evaluate_timing_probe(
        _bootstrap("2026-08-29T11:30:00Z"),
        as_of="2026-08-29T17:00:00+07:00",
    )
    assert result["run_full_engine"] is True
    assert result["reason"] == "FINAL_DEADLINE_REVIEW"
    assert result["policy_id"] == "FINAL_DEADLINE_REVIEW"
    assert result["visible_output_authorized"] is True


def test_probe_stays_silent_at_non_final_top_of_hour():
    result = evaluate_timing_probe(
        _bootstrap("2026-08-29T12:30:00Z"),
        as_of="2026-08-29T17:00:00+07:00",
    )
    assert result["run_full_engine"] is False
    assert result["reason"] == "SILENT_TIMING_PROBE"
    assert result["policy_id"] == "INTERNAL_HOURLY_SILENT"
    assert result["visible_output_authorized"] is False


def test_probe_catches_recent_post_deadline_reconciliation_transition():
    result = evaluate_timing_probe(
        _bootstrap(
            "2026-08-29T10:50:00Z",
            next_deadline="2026-09-05T10:00:00Z",
        ),
        as_of="2026-08-29T18:00:00+07:00",
    )
    assert result["run_full_engine"] is True
    assert result["reason"] == "POST_DEADLINE_RECONCILIATION_TRANSITION"
    assert result["policy_id"] == "POST_DEADLINE_RECONCILIATION"
    assert result["recent_reconciliation_transition"] is True
    assert result["reconciliation_age_minutes"] == 10.0


def test_probe_does_not_repeat_reconciliation_after_thirty_minutes():
    result = evaluate_timing_probe(
        _bootstrap(
            "2026-08-29T10:30:00Z",
            next_deadline="2026-09-05T10:00:00Z",
        ),
        as_of="2026-08-29T18:00:00+07:00",
    )
    assert result["policy_id"] == "POST_DEADLINE_RECONCILIATION"
    assert result["run_full_engine"] is False
    assert result["recent_reconciliation_transition"] is False
    assert result["reconciliation_age_minutes"] == 30.0


def test_probe_workflow_is_top_of_hour_and_full_core_is_conditional():
    workflow = (ROOT / ".github/workflows/fpl-engine-timing-probe.yml").read_text()
    assert 'cron: "0 * * * *"' in workflow
    assert "python -m src.services.checkpoint_timing_probe" in workflow
    assert "if: needs.probe.outputs.run_full == 'true'" in workflow
    assert "uses: ./.github/workflows/fpl-engine-core.yml" in workflow
    assert 'cron: "30 * * * *"' not in workflow
