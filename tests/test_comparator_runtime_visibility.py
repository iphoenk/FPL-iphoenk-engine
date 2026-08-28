from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_is_visible_in_runtime_and_report_serving_paths():
    services = json.loads((ROOT / "config" / "v3_service_registry.json").read_text())
    publish = json.loads((ROOT / "config" / "runtime" / "runtime_publish_registry.json").read_text())
    assert "owned_challenger_comparator.json" in services["services"]["watchlist"]["artifacts"]
    assert "owned_challenger_comparator.json" in services["services"]["report_materializer"]["inputs"]
    assert "owned_challenger_comparator.json" in publish["publish_paths"]
