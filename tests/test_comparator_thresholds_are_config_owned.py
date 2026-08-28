from __future__ import annotations

import inspect

from src.engines import owned_challenger_comparator as comparator


def test_decision_and_emerging_thresholds_are_loaded_from_config():
    text = inspect.getsource(comparator)
    assert 'load_policy().get("emerging_screen")' in text
    assert 'load_policy().get("decision")' in text
    assert 'load_policy().get("owned_targeting")' in text
