from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rec43_delivery_docs_and_modules_exist():
    for path in (
        "docs/REC43_OWNED_CHALLENGER_COMPARATOR.md",
        "docs/REC43_DELIVERY_CHECKLIST.md",
        "src/engines/owned_challenger_comparator.py",
        "src/engines/owned_challenger_transfer_context.py",
        "src/engines/report_comparator_overlay.py",
        "config/intelligence/owned_challenger_comparator.json",
    ):
        assert (ROOT / path).exists(), path
