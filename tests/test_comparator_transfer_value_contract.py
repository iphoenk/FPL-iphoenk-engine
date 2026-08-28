from __future__ import annotations

import inspect

from src.engines import owned_challenger_comparator as comparator


def test_net_transfer_value_is_sourced_from_canonical_package_context():
    text = inspect.getsource(comparator._comparison)
    assert '"net_transfer_value": package.get("robust_gain_vs_hold") if package else None' in text
    assert '"canonical_package": package' in text
