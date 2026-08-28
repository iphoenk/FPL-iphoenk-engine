from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_emits_explicit_data_quality_states():
    source = (ROOT / "src" / "engines" / "owned_challenger_comparator.py").read_text()
    for field in ("canonical_projection", "canonical_xmins", "canonical_tactical_current_gw", "canonical_package", "cross_competition_congestion", "external_consensus"):
        assert field in source
