from __future__ import annotations

from src.engines import owned_challenger_comparator as comparator


def test_missing_fixture_and_tactical_evidence_remain_explicit():
    proj = {"xpts_by_gw": [], "tactical_matchup": {}}
    assert comparator._fixture_context(proj, 0, {})["status"] == "UNVERIFIED"
    tactical = comparator._tactical_for_gw(proj, 1)
    assert tactical["evidence_state"] == "UNVERIFIED"
    assert tactical["decision_usage"] == "ADVISORY_ONLY"
