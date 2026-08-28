from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_generic_comparator_contract_declares_required_horizons_and_challenger_types():
    policy = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert policy["contract"] == "OWNED_CHALLENGER_COMPARATOR_V1"
    assert policy["horizons"] == [1, 2, 3, 5]
    assert set(policy["challenger_types"]) == {"GOVERNED_WATCHLIST", "EMERGING_CHALLENGER"}
    assert policy["capability_status"] == "ADVISORY_ONLY"
    assert policy["evidence"]["future_non_pl_competition_requires_report_time_verification"] is True
    assert policy["evidence"]["coach_and_true_tactical_style_require_verified_evidence"] is True
