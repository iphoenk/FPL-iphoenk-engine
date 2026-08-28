from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_source_does_not_write_dss_watchlist_artifact():
    source = (ROOT / "src" / "engines" / "owned_challenger_comparator.py").read_text()
    assert 'atomic_json(DATA / "dss_watchlist.json"' not in source
