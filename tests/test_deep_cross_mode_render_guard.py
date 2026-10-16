"""Regression: cross-mode sections must not leak into DEEP rendering."""

import pytest

from src.engines.v12_report_orchestration import (
    ReportOrchestrationError,
    render_deep_text,
)


def test_deep_rejects_match_sections_instead_of_rendering_them():
    report = {
        "report_mode": "DEEP",
        "sections": [
            {"section_id": "S01", "label": "Decision", "state": "COMPLETE", "content": {}},
            {"section_id": "MATCH1", "label": "Live fixtures", "state": "COMPLETE", "content": {}},
        ],
    }
    with pytest.raises(ReportOrchestrationError, match="DEEP_RENDER_CROSS_MODE_SECTIONS=MATCH1"):
        render_deep_text(report)


def test_deep_rejects_price_sections():
    with pytest.raises(ReportOrchestrationError, match="DEEP_RENDER_CROSS_MODE_SECTIONS=PRICE1"):
        render_deep_text({"report_mode": "DEEP", "sections": [
            {"section_id": "PRICE1", "label": "Price", "state": "COMPLETE", "content": {}}
        ]})
