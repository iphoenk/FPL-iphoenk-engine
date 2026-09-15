from __future__ import annotations

from pathlib import Path

from src.runtime_v6.workflow_control import resolve_data_slot_decision


WORKFLOW = Path(".github/workflows/v6-natural-data-ingestion.yml")


def test_already_published_v6_does_not_skip_due_report():
    decision = resolve_data_slot_decision(already_published=True)

    assert decision["data_slot_status"] == "ALREADY_PUBLISHED"
    assert decision["skip_new_acquisition"] is True
    assert decision["reuse_last_valid_publication"] is True
    assert decision["continue_report_pipeline"] is True


def test_new_v6_slot_still_allows_report_pipeline():
    decision = resolve_data_slot_decision(already_published=False)

    assert decision["data_slot_status"] == "NEW"
    assert decision["skip_new_acquisition"] is False
    assert decision["reuse_last_valid_publication"] is False
    assert decision["continue_report_pipeline"] is True


def test_workflow_exposes_data_slot_decision_separately_from_report_continuation():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "data_slot_status: ${{ steps.slot_guard.outputs.data_slot_status }}" in text
    assert "skip_new_acquisition: ${{ steps.slot_guard.outputs.skip_new_acquisition }}" in text
    assert "reuse_last_valid_publication: ${{ steps.slot_guard.outputs.reuse_last_valid_publication }}" in text
    assert "continue_report_pipeline: ${{ steps.slot_guard.outputs.continue_report_pipeline }}" in text


def test_already_published_fulfillment_is_not_terminal_workflow_noop():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "CONTINUE_REPORT_PIPELINE: ${{ needs.collect.outputs.continue_report_pipeline }}" in text
    assert 'state="DATA_SLOT_ALREADY_PUBLISHED_REPORT_CONTINUES"' in text
    assert "continue_report_pipeline=$CONTINUE_REPORT_PIPELINE" in text
    assert "IDEMPOTENT_NOOP_ALREADY_PUBLISHED" not in text
