from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rec43_is_not_done_prod_before_runtime_proof():
    rec = json.loads((ROOT / "config" / "rec_registry.json").read_text())
    row = next(item for item in rec["records"] if item["id"] == "REC-43")
    assert row["status"] == "CANDIDATE"
