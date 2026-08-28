from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_is_published_and_report_overlay_is_required_in_serving_pipeline():
    services = json.loads((ROOT / "config" / "v3_service_registry.json").read_text())
    publish = json.loads((ROOT / "config" / "runtime" / "runtime_publish_registry.json").read_text())
    contracts = json.loads((ROOT / "config" / "runtime" / "artifact_contracts.json").read_text())

    watchlist = services["services"]["watchlist"]
    report = services["services"]["report_materializer"]
    assert "owned_challenger_comparator.json" in watchlist["artifacts"]
    assert "owned_challenger_comparator.json" in report["inputs"]
    assert [row["module"] for row in report["commands"]].index("src.engines.report_comparator_overlay") > [row["module"] for row in report["commands"]].index("src.engines.report_materializer")
    assert "owned_challenger_comparator.json" in publish["publish_paths"]
    assert contracts["contracts"]["owned_challenger_comparator.json"]["equals"]["contract"] == "OWNED_CHALLENGER_COMPARATOR_V1"
