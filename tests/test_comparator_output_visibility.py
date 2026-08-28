from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_output_is_both_artifact_and_report_section():
    source = (ROOT / "src" / "engines" / "owned_challenger_comparator.py").read_text()
    overlay = (ROOT / "src" / "engines" / "report_comparator_overlay.py").read_text()
    assert 'owned_challenger_comparator.json' in source
    assert 'owned_vs_challenger' in overlay
