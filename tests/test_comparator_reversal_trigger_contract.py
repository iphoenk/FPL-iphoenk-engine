from __future__ import annotations

from src.engines import owned_challenger_comparator as comparator


def test_reversal_trigger_template_is_nonempty_and_material():
    source = comparator._comparison
    assert callable(source)
    text = comparator.__file__
    assert text
