from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_existing_watchlist_contract_still_excludes_owned_players():
    cfg = json.loads((ROOT / "config" / "intelligence" / "dss_watchlist.json").read_text())
    comparator = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert cfg["screening"]["exclude_owned"] is True
    assert comparator["governance"]["reuse_governed_watchlist"] is True
