from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_missing_critical_evidence_is_configured_to_cap_actionability():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert cfg["decision"]["missing_structural_or_critical_evidence_caps_at"] == "REVIEW"
    assert cfg["governance"]["missing_evidence_is_explicit"] is True
