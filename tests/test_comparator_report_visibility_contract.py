from __future__ import annotations

import inspect

from src.engines import report_comparator_overlay


def test_report_overlay_exposes_owned_vs_challenger_section():
    text = inspect.getsource(report_comparator_overlay.run)
    assert '"owned_vs_challenger"' in text
