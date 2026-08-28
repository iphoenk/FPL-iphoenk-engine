from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_does_not_implement_fixture_probability_or_xpts_components():
    source = (ROOT / "src" / "engines" / "owned_challenger_comparator.py").read_text()
    for forbidden in ("clean_sheet_probability", "team_expected_goals", "attack_multiplier", "defensive_contribution"):
        assert forbidden not in source
