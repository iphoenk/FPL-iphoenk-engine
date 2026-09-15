from __future__ import annotations

from src.runtime_v6.workflow_control import resolve_data_slot_decision


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
