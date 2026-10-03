from __future__ import annotations

from typing import Any


def resolve_competitive_window(our_rank: Any, league_size: Any) -> dict[str, Any]:
    """Resolve the rank-relative competitive cohort without inventing managers.

    Rank < 10 uses the Top-10 milestone excluding us.
    Rank >= 10 uses nine immediately above plus up to five immediately below.
    League boundaries truncate naturally.
    """
    try:
        rank = int(our_rank)
        size = int(league_size)
    except (TypeError, ValueError):
        rank = 0
        size = 0

    if size <= 0 or rank <= 0 or rank > size:
        return {
            "our_rank": rank or None,
            "league_size": size or None,
            "window_mode": "UNAVAILABLE",
            "above_count": 0,
            "below_count": 0,
            "rival_count": 0,
            "ranks": [],
        }

    if rank < 10:
        ranks = [value for value in range(1, min(10, size) + 1) if value != rank]
        mode = "TOP10"
    else:
        ranks = list(range(max(1, rank - 9), rank))
        ranks.extend(range(rank + 1, min(size, rank + 5) + 1))
        mode = "NINE_ABOVE_FIVE_BELOW"

    above_count = sum(1 for value in ranks if value < rank)
    below_count = sum(1 for value in ranks if value > rank)
    return {
        "our_rank": rank,
        "league_size": size,
        "window_mode": mode,
        "above_count": above_count,
        "below_count": below_count,
        "rival_count": len(ranks),
        "ranks": ranks,
    }
