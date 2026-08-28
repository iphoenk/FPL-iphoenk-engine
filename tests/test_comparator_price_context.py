from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_reuses_price_state_without_price_prediction_formula():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert cfg["governance"]["reuse_canonical_price_state"] is True
    source = (ROOT / "src" / "engines" / "owned_challenger_comparator.py").read_text()
    assert "def predict_price" not in source
    assert "official_progress_pct" not in source
