from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_initial_comparator_does_not_claim_strong_transfer_authority():
    policy = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    source = (ROOT / "src" / "engines" / "owned_challenger_comparator.py").read_text()
    assert policy["capability_status"] == "ADVISORY_ONLY"
    assert '"LEAN_TRANSFER"  # report-time congestion/team-news evidence still required before STRONG in ADVISORY_ONLY mode' in source
    assert policy["governance"]["may_not_overwrite_canonical_transfer_recommendation"] is True
