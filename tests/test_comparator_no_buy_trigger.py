from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_performance_trigger_is_not_automatic_buy():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert cfg["governance"]["one_match_haul_is_trigger_not_buy"] is True
