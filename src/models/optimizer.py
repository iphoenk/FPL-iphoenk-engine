from __future__ import annotations

"""Compatibility-only optimizer facade.

Authoritative V4 optimization lives in ``src.engines.v4_wc_optimizer_fast`` and
``src.engines.v4_wc_package_audit_fast``.  This legacy module may expose domain
legality for old callers, but it must never implement a second scoring or package
selection algorithm.
"""

from src.engines.fpl_legality import squad_shape_is_legal


def legal_counts(players):
    return squad_shape_is_legal(players)


def score_squad(*_args, **_kwargs):
    raise RuntimeError(
        "legacy score_squad is non-authoritative; use the canonical V4 optimizer/decision pipeline"
    )


def evaluate_package(*_args, **_kwargs):
    raise RuntimeError(
        "legacy evaluate_package is non-authoritative; use src.engines.v4_wc_package_audit_fast"
    )
