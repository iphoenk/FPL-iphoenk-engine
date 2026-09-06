from __future__ import annotations

"""Compatibility entrypoint for V6 historical backfill.

The production implementation lives in :mod:`src.runtime_v6.historical_facts` and
publishes factual/normalized artifacts only. This module intentionally contains
no ownership, EO, transition, overlap, concentration, reconstructed-rank, or
behavioral analytics. Existing workflow/module callers may keep using
``python -m src.runtime_v6.historical_backfill`` without retaining the retired
analytical implementation.
"""

from .historical_facts import (
    COHORT_SEMANTICS,
    HISTORICAL_SCHEMA_VERSION,
    LIVE_CURRENT,
    LIVE_HISTORICAL,
    MEMBERSHIP_EVIDENCE,
    MEMBERSHIP_STATUS,
    REUSED_CURRENT,
    REUSED_HISTORICAL,
    HistoricalBackfillError,
    HistoricalBackfillService,
    acquire_entry_histories,
    acquire_historical_picks,
    main,
    validate_gw_range,
)

__all__ = [
    "COHORT_SEMANTICS",
    "HISTORICAL_SCHEMA_VERSION",
    "LIVE_CURRENT",
    "LIVE_HISTORICAL",
    "MEMBERSHIP_EVIDENCE",
    "MEMBERSHIP_STATUS",
    "REUSED_CURRENT",
    "REUSED_HISTORICAL",
    "HistoricalBackfillError",
    "HistoricalBackfillService",
    "acquire_entry_histories",
    "acquire_historical_picks",
    "validate_gw_range",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
