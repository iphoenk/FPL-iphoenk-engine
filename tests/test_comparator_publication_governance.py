from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rec43_remains_candidate_until_runtime_artifact_is_verified():
    rec = json.loads((ROOT / "config" / "rec_registry.json").read_text())
    row = next(item for item in rec["records"] if item["id"] == "REC-43")
    assert row["status"] == "CANDIDATE"
    docs = (ROOT / "docs" / "REC43_DELIVERY_CHECKLIST.md").read_text()
    assert "fresh `runtime-data` snapshot" in docs
    assert "ADVISORY_ONLY" in docs
