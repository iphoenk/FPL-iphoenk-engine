from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_external_model_consensus_is_advisory_and_not_majority_vote():
    policy = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert policy["governance"]["no_majority_vote_across_external_models"] is True
    assert policy["evidence"]["external_consensus_requires_report_time_refresh"] is True
