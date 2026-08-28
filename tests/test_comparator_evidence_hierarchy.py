from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rec43_is_official_first_with_external_enrichment_only():
    coverage = json.loads((ROOT / "config" / "sources" / "official_first_coverage.json").read_text())
    row = coverage["recommendations"]["REC-43"]
    assert row["applicability"] == "PUBLIC_FIRST_WITH_ENRICHMENT"
    assert set(row["endpoints"]) >= {"bootstrap", "fixtures", "element_summary", "entry"}
