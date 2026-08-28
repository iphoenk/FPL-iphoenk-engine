from __future__ import annotations

"""Compatibility facade for validation metrics.

Metric calculation is owned by :mod:`src.models.v4_metrics`.  This module keeps
legacy import names only; it must not implement a second metric formula.
"""

from src.models.v4_metrics import (
    brier_values as brier,
    mae_values as mae,
    spearman_values as spearman_rank,
)

__all__ = ["mae", "brier", "spearman_rank"]
