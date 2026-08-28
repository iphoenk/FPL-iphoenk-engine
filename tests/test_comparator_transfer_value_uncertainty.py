from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_transfer_value_requires_uncertainty_context_not_raw_gain_only():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert cfg["governance"]["positive_projected_edge_is_not_sufficient_alone"] is True
    assert cfg["decision"]["lean_minimum_signal_to_noise"] > 0
