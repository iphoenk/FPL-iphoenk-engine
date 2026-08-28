from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_emerging_lane_is_discovery_not_buy_authority():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert "EMERGING_CHALLENGER" in cfg["challenger_types"]
    assert cfg["governance"]["emerging_performance_signal_never_directly_creates_transfer_recommendation"] if "emerging_performance_signal_never_directly_creates_transfer_recommendation" in cfg["governance"] else cfg["governance"]["one_match_haul_is_trigger_not_buy"]
