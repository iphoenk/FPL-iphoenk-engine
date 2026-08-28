from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_source_does_not_write_lineup_package_or_chip_decisions():
    source = (ROOT / "src" / "engines" / "owned_challenger_comparator.py").read_text()
    for forbidden in ('lineup_decision.json', 'package_decision.json', 'chips.json'):
        assert f'atomic_json(DATA / "{forbidden}"' not in source
