from __future__ import annotations

import inspect

from src.engines import owned_challenger_comparator as comparator


def test_structural_cost_exposes_affordability_club_legality_and_package_context():
    text = inspect.getsource(comparator._comparison)
    for field in ("club_limit_legal", "direct_swap_affordable", "owned_sell_cost", "challenger_purchase_price", "current_itb", "canonical_package"):
        assert field in text
