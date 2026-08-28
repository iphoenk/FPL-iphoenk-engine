from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_config_is_generic_not_player_named():
    text = (ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text(encoding="utf-8")
    assert "Rogers" not in text
    assert "Cherki" not in text
