from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_has_exactly_governed_watchlist_and_emerging_lanes():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert set(cfg["challenger_types"]) == {"GOVERNED_WATCHLIST", "EMERGING_CHALLENGER"}
