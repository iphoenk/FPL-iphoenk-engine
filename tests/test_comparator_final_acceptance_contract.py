from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_activation_requires_merge_ci_runtime_and_artifact_verification():
    docs = (ROOT / "docs" / "REC43_OWNED_CHALLENGER_COMPARATOR.md").read_text()
    for phrase in ("canonical production line", "full V3 CI passes", "fresh runtime publication", "report payloads expose", "production artifact is inspected"):
        assert phrase in docs
