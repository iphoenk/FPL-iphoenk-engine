from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_governed_watchlist_is_authoritative_candidate_lane():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert "GOVERNED_WATCHLIST" in cfg["challenger_types"]
    assert cfg["governance"]["reuse_governed_watchlist"] is True
