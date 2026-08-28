from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_true_coach_congestion_and_consensus_evidence_are_not_inferred_by_comparator():
    policy = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())["evidence"]
    assert policy["coach_and_true_tactical_style_require_verified_evidence"] is True
    assert policy["future_non_pl_competition_requires_report_time_verification"] is True
    assert policy["external_consensus_requires_report_time_refresh"] is True
    assert policy["social_signal_may_trigger_investigation_but_never_becomes_fact_without_crosscheck"] is True
