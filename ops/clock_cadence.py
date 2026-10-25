"""Audit-only clock cadence diagnosis for the existing GitHub clock (P0-B).

GitHub schedule events are best-effort. This module explains WHY an occurrence
is MISSING by comparing observed clock ticks with the resolver window. It never
dispatches, reruns or schedules anything and never changes an occurrence state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from ops.render_external_clock import RESOLVER_WINDOW_MINUTES

NO_TICK_IN_WINDOW = "CLOCK_NO_TICK_IN_RESOLVER_WINDOW"
TICK_NO_DISPATCH = "CLOCK_TICK_IN_WINDOW_NO_DISPATCH"
TICK_EVIDENCE_UNAVAILABLE = "CLOCK_TICK_EVIDENCE_UNAVAILABLE"
EXPECTED_TICKS_PER_HOUR = 1  # cron "35 * * * *"


def parse_ticks(created_at: Iterable[str]) -> list[datetime]:
    out: list[datetime] = []
    for raw in created_at:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            continue
        out.append(dt.astimezone(timezone.utc))
    return sorted(out)


def cadence_summary(now: datetime, ticks: Sequence[datetime], lookback_hours: int) -> dict[str, Any]:
    since = now - timedelta(hours=lookback_hours)
    window = [t for t in ticks if since <= t <= now]
    expected = lookback_hours * EXPECTED_TICKS_PER_HOUR
    points = [since, *window, now]
    max_gap = max(((b - a).total_seconds() / 60 for a, b in zip(points, points[1:])), default=None)
    return {
        "lookback_hours": lookback_hours,
        "ticks_observed": len(window),
        "ticks_expected": expected,
        "delivery_ratio": round(len(window) / expected, 3) if expected else None,
        "max_gap_minutes": round(max_gap, 1) if max_gap is not None else None,
        "last_tick_utc": window[-1].strftime("%Y-%m-%dT%H:%M:%SZ") if window else None,
        "minutes_since_last_tick": round((now - window[-1]).total_seconds() / 60, 1) if window else None,
    }


def diagnose_missing(report_slot: str, ticks: Sequence[datetime] | None) -> str:
    if ticks is None:
        return TICK_EVIDENCE_UNAVAILABLE
    slot = datetime.fromisoformat(report_slot).astimezone(timezone.utc)
    lo = slot + timedelta(minutes=RESOLVER_WINDOW_MINUTES[0])
    hi = slot + timedelta(minutes=RESOLVER_WINDOW_MINUTES[1])
    return TICK_NO_DISPATCH if any(lo <= t <= hi for t in ticks) else NO_TICK_IN_WINDOW


def annotate(
    rows: Sequence[Mapping[str, Any]],
    ticks: Sequence[datetime] | None,
    now: datetime,
    lookback_hours: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Return rows with a `diagnosis` on MISSING entries; states are untouched."""
    out: list[dict[str, Any]] = []
    for row in rows:
        new = dict(row)
        if row.get("state") == "MISSING":
            new["diagnosis"] = diagnose_missing(str(row["report_slot"]), ticks)
        out.append(new)
    summary = cadence_summary(now, ticks, lookback_hours) if ticks is not None else None
    return out, summary
