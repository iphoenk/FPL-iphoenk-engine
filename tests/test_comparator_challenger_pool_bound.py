from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_emerging_challenger_pool_is_bounded():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert 1 <= cfg["emerging_screen"]["max_candidates"] <= 20
