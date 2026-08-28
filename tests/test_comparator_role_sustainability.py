from __future__ import annotations

import inspect

from src.engines import owned_challenger_comparator as comparator


def test_role_sustainability_reuses_xmins_rates_and_role_context():
    text = inspect.getsource(comparator._role_sustainability)
    for field in ("starts", "minutes", "expected_minutes", "start_probability", "dnp_probability", "xg90", "xa90", "tactical_role", "set_piece_penalty"):
        assert field in text
