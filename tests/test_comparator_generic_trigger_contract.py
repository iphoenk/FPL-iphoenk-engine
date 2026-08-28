from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_emerging_trigger_contract_has_no_buy_or_transfer_state():
    policy = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert set(policy["challenger_types"]) == {"GOVERNED_WATCHLIST", "EMERGING_CHALLENGER"}
    assert policy["governance"]["one_match_haul_is_trigger_not_buy"] is True
