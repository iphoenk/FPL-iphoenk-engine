"""Compatibility import only.

Canonical Official FPL price predictor parsing and threshold semantics live in
``src.engines.price_radar`` and are shared with the V3 contract. V4-specific
price-squeeze simulation lives in ``src.engines.v4_price_context``.

This module intentionally contains no endpoint parser, schema mapping, threshold
logic, or network access.
"""

from src.engines.v4_price_context import squeeze_for_pairs

__all__ = ["squeeze_for_pairs"]
