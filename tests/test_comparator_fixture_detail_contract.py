from __future__ import annotations

import inspect

from src.engines import owned_challenger_comparator as comparator


def test_fixture_context_carries_opponent_home_away_xpts_and_uncertainty():
    text = inspect.getsource(comparator._fixture_context)
    for field in ("opponent_team_id", "opponent", "home_away", "kickoff_time", "xpts", "std"):
        assert field in text
