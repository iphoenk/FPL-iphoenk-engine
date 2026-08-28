from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_cannot_overwrite_xi_captain_watchlist_or_chip():
    policy = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())["governance"]
    assert policy["may_not_overwrite_starting_xi"] is True
    assert policy["may_not_overwrite_captain_or_vice"] is True
    assert policy["may_not_overwrite_watchlist"] is True
    assert policy["may_not_overwrite_chip_decision"] is True
