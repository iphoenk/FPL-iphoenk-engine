from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_initial_status_is_advisory_only():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert cfg["capability_status"] == "ADVISORY_ONLY"
