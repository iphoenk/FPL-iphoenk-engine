from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ScheduledReportSlot:
    observed_at: datetime
    intended_report_slot: datetime | None
    delta_seconds: float
    within_tolerance: bool


def resolve_scheduled_report_slot(
    observed_at: datetime,
    *,
    timezone_name: str,
    physical_minute: int,
    tolerance_seconds: int,
) -> ScheduledReportSlot:
    """Resolve the nearest intended hourly scheduled occurrence.

    The physical observation timestamp is preserved exactly. Only the logical
    scheduled occurrence is normalized, and only when the dispatch is within
    the configured bounded tolerance.
    """
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    if not 0 <= physical_minute <= 59:
        raise ValueError("physical_minute must be between 0 and 59")
    if tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be non-negative")

    timezone = ZoneInfo(timezone_name)
    local_observed = observed_at.astimezone(timezone)
    same_hour = local_observed.replace(
        minute=physical_minute,
        second=0,
        microsecond=0,
    )
    candidates = (
        same_hour - timedelta(hours=1),
        same_hour,
        same_hour + timedelta(hours=1),
    )
    intended = min(
        candidates,
        key=lambda candidate: abs((local_observed - candidate).total_seconds()),
    )
    delta_seconds = (local_observed - intended).total_seconds()
    within_tolerance = abs(delta_seconds) <= tolerance_seconds

    return ScheduledReportSlot(
        observed_at=observed_at,
        intended_report_slot=intended if within_tolerance else None,
        delta_seconds=delta_seconds,
        within_tolerance=within_tolerance,
    )
