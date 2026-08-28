from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_transfer_thresholds_are_configured_not_scattered_literals():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    decision = cfg["decision"]
    assert decision["review_gain_5gw"] < decision["lean_gain_5gw"] < decision["strong_gain_5gw"]
