from __future__ import annotations

from src.engines import owned_challenger_comparator as comparator


def test_comparator_build_function_declares_advisory_governance_fields():
    payload_governance = comparator.load_policy()["governance"]
    assert payload_governance["may_not_overwrite_canonical_transfer_recommendation"] is True
    assert payload_governance["may_not_overwrite_starting_xi"] is True
    assert payload_governance["may_not_overwrite_captain_or_vice"] is True
    assert payload_governance["may_not_overwrite_watchlist"] is True
    assert payload_governance["may_not_overwrite_chip_decision"] is True
