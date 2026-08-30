from __future__ import annotations

from typing import Any


def _league_row(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    rank = row.get("entry_rank")
    last_rank = row.get("entry_last_rank")
    try:
        rank_delta = int(last_rank) - int(rank) if rank is not None and last_rank is not None else None
    except (TypeError, ValueError):
        rank_delta = None
    return {
        "kind": kind,
        "league_id": row.get("id"),
        "league_name": row.get("name"),
        "rank": rank,
        "last_rank": last_rank,
        "rank_delta": rank_delta,
        "entry_can_leave": row.get("entry_can_leave") is True,
        "entry_can_admin": row.get("entry_can_admin") is True,
        "entry_can_invite": row.get("entry_can_invite") is True,
    }


def public_mini_league_memberships(entry: dict[str, Any] | None, *, fallback_entry_id: int | None = None) -> dict[str, Any]:
    """Project user-created/public mini-league memberships from Official entry data.

    System classic leagues are excluded because they do not represent user-created league
    membership. H2H memberships are retained because Official FPL does not expose the same
    management flags consistently for them. This is presentation truth only and cannot
    mutate prediction or decision state.
    """
    entry = entry if isinstance(entry, dict) else {}
    leagues = entry.get("leagues") if isinstance(entry.get("leagues"), dict) else {}
    classic_rows = [row for row in leagues.get("classic") or [] if isinstance(row, dict)]
    h2h_rows = [row for row in leagues.get("h2h") or [] if isinstance(row, dict)]

    classic_private = [
        _league_row("classic", row)
        for row in classic_rows
        if any(row.get(key) is True for key in ("entry_can_leave", "entry_can_admin", "entry_can_invite"))
    ]
    h2h = [_league_row("h2h", row) for row in h2h_rows]
    memberships = classic_private + h2h
    memberships.sort(
        key=lambda row: (
            0 if row.get("kind") == "classic" else 1,
            str(row.get("league_name") or "").lower(),
            int(row.get("league_id") or 0),
        )
    )
    entry_id = entry.get("id") if entry.get("id") is not None else fallback_entry_id
    return {
        "authority": "PUBLIC_OFFICIAL_ENTRY",
        "entry_id": entry_id,
        "classic_private_count": len(classic_private),
        "h2h_count": len(h2h),
        "membership_count": len(memberships),
        "system_classic_excluded_count": max(0, len(classic_rows) - len(classic_private)),
        "memberships": memberships,
        "governance": {
            "official_public_entry_only": True,
            "authentication_not_required": True,
            "prediction_mutation": False,
            "decision_mutation": False,
        },
    }
