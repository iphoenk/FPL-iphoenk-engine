from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .http_client import utc_now


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _minutes_since(value: str | None) -> float | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60.0)


def _effective_data_checked_at(row: dict[str, Any]) -> str | None:
    if row.get("data_origin") == "REVALIDATED_CACHE":
        return row.get("revalidated_at") or row.get("latest_attempt_checked_at") or row.get("checked_at")
    return row.get("checked_at")


def _max_data_age_minutes(payload: dict[str, Any]) -> float | None:
    ages = [
        _minutes_since(_effective_data_checked_at(row))
        for row in (payload.get("data") or {}).values()
        if isinstance(row, dict)
    ]
    concrete = [age for age in ages if age is not None]
    return max(concrete) if concrete else None


def _last_success_at(payload: dict[str, Any]) -> str | None:
    values = [
        row.get("checked_at")
        for row in (payload.get("attempts") or [])
        if row.get("status") in {"AVAILABLE", "NOT_MODIFIED"} and row.get("checked_at")
    ]
    return max(values) if values else None


def build_source_health(config: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sources = []
    counts = {"GREEN": 0, "AMBER": 0, "RED": 0}

    for source in config.get("sources") or []:
        payload = results[source["id"]]
        health = str(payload.get("health") or "AMBER")
        counts[health] = counts.get(health, 0) + 1

        checked_at = payload.get("checked_at")
        check_age = _minutes_since(checked_at)
        max_data_age = _max_data_age_minutes(payload)
        coverage = payload.get("coverage") or {}
        polling = payload.get("polling") or {}

        sources.append(
            {
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
                "critical": bool(source.get("critical")),
                "health": health,
                "availability": payload.get("availability"),
                "effective_state": payload.get("effective_state"),
                "changed": payload.get("changed"),
                "checked_at": checked_at,
                "last_success_at": _last_success_at(payload),
                "check_age_minutes": round(check_age, 3) if check_age is not None else None,
                "max_effective_data_age_minutes": round(max_data_age, 3) if max_data_age is not None else None,
                "check_freshness_target_minutes": source.get("check_freshness_minutes"),
                "duration_ms": payload.get("duration_ms"),
                "coverage": coverage,
                "polling": {
                    "acquisition_kind": source.get("acquisition_kind"),
                    "poll_interval_minutes": polling.get("poll_interval_minutes"),
                    "deadline_window": polling.get("deadline_window"),
                    "skipped": polling.get("skipped", False),
                    "reason": polling.get("reason"),
                    "last_polled_at": polling.get("last_polled_at"),
                },
                "budget": payload.get("budget"),
            }
        )

    overall = "RED" if counts.get("RED", 0) else ("AMBER" if counts.get("AMBER", 0) else "GREEN")
    return {
        "schema_version": 3,
        "generated_at": utc_now(),
        "overall": overall,
        "counts": counts,
        "source_count": len(sources),
        "sources": sources,
        "semantics": {
            "GREEN": "Latest required acquisition/revalidation succeeded, or the source is intentionally not due yet under its registry polling contract. Unchanged upstream data is not degraded.",
            "AMBER": "Usable but partial/cached, credential or verification required, budget exhausted, truncated, or otherwise degraded.",
            "RED": "Critical source has no usable current or cached data.",
        },
    }
