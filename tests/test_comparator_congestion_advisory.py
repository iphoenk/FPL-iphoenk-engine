from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_congestion_evidence_does_not_directly_mutate_points():
    source = (ROOT / "config" / "intelligence" / "recent_competitive_load.json").read_text()
    comparator = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert '"direct_xpts_mutation_forbidden": true' in source
    assert comparator["evidence"]["future_non_pl_competition_requires_report_time_verification"] is True
