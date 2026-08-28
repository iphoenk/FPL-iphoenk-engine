from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_has_required_1_2_3_5_gw_horizons():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert cfg["horizons"] == [1, 2, 3, 5]
