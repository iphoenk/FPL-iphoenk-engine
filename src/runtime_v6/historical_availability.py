from __future__ import annotations

from typing import Any

OFFICIAL_GW_RECORD_NOT_AVAILABLE = "OFFICIAL_GW_RECORD_NOT_AVAILABLE"
BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW = "BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW"


def history_rows(result: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not isinstance(result, dict) or result.get("status") != "LIVE":
        return {}
    payload = result.get("payload") or {}
    return {
        int(row["event"]): dict(row)
        for row in (payload.get("current") or [])
        if isinstance(row, dict) and row.get("event") is not None
    }


def classify_completed_gw_official_absence(
    *,
    pick_record: dict[str, Any] | None,
    history_result: dict[str, Any] | None,
    gw: int,
    completed: bool,
) -> dict[str, Any] | None:
    """Classify a strict Official-FPL absence without inferring league membership.

    A current-cohort entry is explicitly excludable for a completed GW only when:
    - Official submitted-picks returned HTTP 404 for that GW;
    - Official entry-history is live;
    - the requested GW has no history row; and
    - the same Official entry-history starts at a later GW.

    This means only that Official FPL exposes no GW record before the entry's first
    Official history row. It does not assert historical mini-league membership.
    """
    if not completed or not isinstance(pick_record, dict):
        return None
    if pick_record.get("status") == "AVAILABLE":
        return None
    if int(pick_record.get("http_status") or 0) != 404:
        return None

    rows = history_rows(history_result)
    if not rows or int(gw) in rows:
        return None
    first_history_gw = min(rows)
    if first_history_gw <= int(gw):
        return None

    return {
        "official_availability_status": OFFICIAL_GW_RECORD_NOT_AVAILABLE,
        "official_exclusion": True,
        "official_exclusion_reason": BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW,
        "requested_gw": int(gw),
        "first_official_entry_history_gw": int(first_history_gw),
        "submitted_picks_http_status": 404,
        "authority": "OFFICIAL_FPL_SUBMITTED_PICKS_PLUS_ENTRY_HISTORY",
        "historical_league_membership_inferred": False,
    }


def captain_multiplier_consistent(picks: list[dict[str, Any]]) -> bool | None:
    """Validate only the factual multiplier domain for the designated captain.

    Official submitted picks may show the designated captain at multiplier 0 when
    the player did not play. Therefore multiplier >=2 is not a valid integrity
    requirement. A designated captain value of 0, 2 or 3 is mechanically valid.
    """
    captains = [pick for pick in picks if pick.get("captain")]
    if len(captains) != 1:
        return None
    value = captains[0].get("multiplier")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value in {0, 2, 3}
