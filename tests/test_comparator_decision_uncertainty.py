from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_transfer_thresholds_require_signal_to_noise_not_raw_gain_only():
    policy = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())["decision"]
    assert policy["lean_minimum_signal_to_noise"] > 0
    assert policy["strong_minimum_signal_to_noise"] > policy["lean_minimum_signal_to_noise"]
