from __future__ import annotations

"""Canonical temporal primitives for the V6 runtime and report plane.

This module is deliberately business-light. It owns timestamp parsing,
normalization, canonical serialization, interval slot math, bounded scheduled
occurrence resolution, freshness classification, incident classification, and
basic temporal-window comparison. Callers may keep compatibility wrappers for
legacy exception types, but must not reimplement ISO parsing or timezone math.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_RUNTIME_TIMEZONE = "Asia/Jakarta"


class TemporalError(ValueError):
    pass


@dataclass(frozen=True)
class ScheduledReportSlot:
    observed_at: datetime
    intended_report_slot: datetime | None
    delta_seconds: float
    within_tolerance: bool


@dataclass(frozen=True)
class FreshnessClassification:
    freshness: str
    health: str


@dataclass(frozen=True)
class IncidentClassification:
    state: str


@dataclass(frozen=True)
class TemporalWindow:
    logical_at: datetime
    observed_at: datetime
    deadline: datetime | None
    observed_before_logical: bool
    window_open: bool | None


def _coerce_timezone(value: str | tzinfo | None) -> tzinfo | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return ZoneInfo(value)
        except Exception as exc:  # ZoneInfoNotFoundError is platform-dependent.
            raise TemporalError(f"unknown timezone: {value}") from exc
    return value


def parse_timestamp(
    value: str | datetime,
    *,
    label: str = "timestamp",
    require_aware: bool = True,
    naive_timezone: str | tzinfo | None = None,
    target_timezone: str | tzinfo | None = None,
) -> datetime:
    """Parse an ISO-8601 timestamp with explicit awareness semantics."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise TemporalError(f"{label} must be ISO-8601") from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        fallback = _coerce_timezone(naive_timezone)
        if fallback is not None:
            parsed = parsed.replace(tzinfo=fallback)
        elif require_aware:
            raise TemporalError(f"{label} must be timezone-aware")

    target = _coerce_timezone(target_timezone)
    if target is not None:
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise TemporalError(f"{label} must be timezone-aware before normalization")
        parsed = parsed.astimezone(target)
    return parsed


def try_parse_timestamp(
    value: Any,
    *,
    label: str = "timestamp",
    require_aware: bool = True,
    naive_timezone: str | tzinfo | None = None,
    target_timezone: str | tzinfo | None = None,
) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        return parse_timestamp(
            value,
            label=label,
            require_aware=require_aware,
            naive_timezone=naive_timezone,
            target_timezone=target_timezone,
        )
    except (TemporalError, TypeError, ValueError):
        return None


def canonical_timestamp(
    value: str | datetime,
    *,
    timezone_name: str | tzinfo | None = None,
    timespec: str = "auto",
) -> str:
    parsed = parse_timestamp(
        value,
        target_timezone=timezone_name,
    )
    if timespec == "auto":
        resolved_timespec = "microseconds" if parsed.microsecond else "seconds"
    else:
        resolved_timespec = timespec
    return parsed.isoformat(timespec=resolved_timespec)


def floor_interval_slot(value: str | datetime, *, cadence_minutes: int) -> datetime:
    if isinstance(cadence_minutes, bool) or not isinstance(cadence_minutes, int):
        raise TemporalError("cadence_minutes must be an integer")
    if cadence_minutes <= 0:
        raise TemporalError("cadence_minutes must be positive")
    current = parse_timestamp(value, target_timezone=timezone.utc)
    interval_seconds = cadence_minutes * 60
    epoch = int(current.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % interval_seconds), tz=timezone.utc)


def age_seconds(*, now: str | datetime, earlier: str | datetime) -> float:
    current = parse_timestamp(now, target_timezone=timezone.utc)
    previous = parse_timestamp(earlier, target_timezone=timezone.utc)
    return max(0.0, (current - previous).total_seconds())


def resolve_scheduled_report_slot(
    observed_at: datetime,
    *,
    timezone_name: str,
    physical_minute: int,
    tolerance_seconds: int,
) -> ScheduledReportSlot:
    """Resolve nearest intended hourly occurrence without rewriting observed_at."""
    observed = parse_timestamp(observed_at, label="observed_at")
    if not 0 <= physical_minute <= 59:
        raise TemporalError("physical_minute must be between 0 and 59")
    if tolerance_seconds < 0:
        raise TemporalError("tolerance_seconds must be non-negative")

    local_observed = observed.astimezone(_coerce_timezone(timezone_name))
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


def classify_freshness(
    *,
    age_minutes: float,
    fresh_after_minutes: float,
    stale_after_minutes: float,
) -> FreshnessClassification:
    if fresh_after_minutes < 0 or stale_after_minutes <= fresh_after_minutes:
        raise TemporalError("invalid freshness thresholds")
    age = max(0.0, float(age_minutes))
    if age <= fresh_after_minutes:
        return FreshnessClassification("FRESH", "GREEN")
    if age <= stale_after_minutes:
        return FreshnessClassification("LATE", "AMBER")
    return FreshnessClassification("STALE", "RED")


def classify_incident(
    *,
    age_minutes: float,
    warning_after_minutes: float,
    critical_after_minutes: float,
) -> IncidentClassification:
    if warning_after_minutes < 0 or critical_after_minutes <= warning_after_minutes:
        raise TemporalError("invalid incident thresholds")
    age = max(0.0, float(age_minutes))
    if age <= warning_after_minutes:
        return IncidentClassification("BELOW_WARNING")
    if age <= critical_after_minutes:
        return IncidentClassification("WARNING")
    return IncidentClassification("CRITICAL")


def compare_temporal_window(
    *,
    logical_at: str | datetime,
    observed_at: str | datetime,
    deadline: str | datetime | None = None,
) -> TemporalWindow:
    logical = parse_timestamp(logical_at, label="logical_at")
    observed = parse_timestamp(observed_at, label="observed_at")
    resolved_deadline = (
        parse_timestamp(deadline, label="deadline") if deadline is not None else None
    )
    return TemporalWindow(
        logical_at=logical,
        observed_at=observed,
        deadline=resolved_deadline,
        observed_before_logical=observed < logical,
        window_open=None if resolved_deadline is None else observed <= resolved_deadline,
    )
