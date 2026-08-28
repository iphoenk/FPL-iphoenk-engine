from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_report_overlay_only_adds_owned_vs_challenger_section():
    source = (ROOT / "src" / "engines" / "report_comparator_overlay.py").read_text()
    assert 'user["owned_vs_challenger"]' in source
    assert 'brief["owned_vs_challenger"]' in source
    assert 'deep["owned_vs_challenger"]' in source
