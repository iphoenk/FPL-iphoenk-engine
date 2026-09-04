from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .http_client import utc_now
from .runtime_control import scheduler_slot_start

WIB = ZoneInfo("Asia/Jakarta")
_VERIFIED = {"VERIFIED"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)


def deadline_window_active(
    previous_sources: dict[str, dict[str, Any]],
    *,
    hours: int = 48,
    now: datetime | None = None,
) -> bool:
    current = _now(now).astimezone(timezone.utc)
    horizon = current + timedelta(hours=max(1, int(hours)))
    official = previous_sources.get("official_fpl") or {}
    bootstrap = ((((official.get("data") or {}).get("bootstrap") or {}).get("json")) or {})
    for event in bootstrap.get("events") or []:
        deadline = _parse_dt(event.get("deadline_time"))
        if deadline is None:
            continue
        deadline = deadline.astimezone(timezone.utc)
        if current <= deadline <= horizon:
            return True
    return False


def effective_poll_interval_minutes(source: dict[str, Any], *, deadline_window: bool) -> int | None:
    if deadline_window and source.get("poll_interval_minutes_deadline_window") is not None:
        return max(1, int(source["poll_interval_minutes_deadline_window"]))
    if source.get("poll_interval_minutes") is not None:
        return max(1, int(source["poll_interval_minutes"]))
    return None


def _budget_state(
    source: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    now: datetime,
    max_attempts_per_request: int,
) -> dict[str, Any]:
    daily_budget = source.get("daily_request_budget")
    day_wib = now.astimezone(WIB).date().isoformat()
    previous_budget = dict((previous or {}).get("budget") or {})
    previous_day = str(previous_budget.get("date_wib") or "")
    used = int(previous_budget.get("requests_used") or 0) if previous_day == day_wib else 0
    configured_requests = len(source.get("requests") or [])
    attempts = max(1, int(max_attempts_per_request))
    reserved_requests = configured_requests * attempts
    if daily_budget is None:
        return {
            "date_wib": day_wib,
            "limit": None,
            "requests_used": used,
            "configured_requests_next_poll": configured_requests,
            "max_attempts_per_request": attempts,
            "reserved_requests_next_poll": reserved_requests,
            "remaining": None,
        }
    limit = max(1, int(daily_budget))
    return {
        "date_wib": day_wib,
        "limit": limit,
        "requests_used": used,
        "configured_requests_next_poll": configured_requests,
        "max_attempts_per_request": attempts,
        "reserved_requests_next_poll": reserved_requests,
        "remaining": max(0, limit - used),
    }


def _decision_payload(
    *,
    due: bool,
    reason: str,
    current: datetime,
    interval: int | None,
    scheduler_interval: int,
    deadline_window: bool,
    source: dict[str, Any],
    budget: dict[str, Any],
) -> dict[str, Any]:
    return {
        "due": due,
        "reason": reason,
        "evaluated_at": current.astimezone(timezone.utc).isoformat(),
        "poll_interval_minutes": interval,
        "scheduler_interval_minutes": scheduler_interval,
        "scheduler_slot": scheduler_slot_start(current, scheduler_interval).isoformat(),
        "deadline_window": deadline_window,
        "verification_status": source.get("verification_status"),
        "budget": budget,
    }


def poll_decision(
    source: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    deadline_window: bool = False,
    now: datetime | None = None,
    max_attempts_per_request: int = 1,
    scheduler_interval_minutes: int = 60,
) -> dict[str, Any]:
    current = _now(now)
    interval = effective_poll_interval_minutes(source, deadline_window=deadline_window)
    scheduler_interval = max(1, int(scheduler_interval_minutes))
    budget = _budget_state(
        source,
        previous,
        now=current,
        max_attempts_per_request=max_attempts_per_request,
    )

    if source.get("verification_required") is True:
        status = str(source.get("verification_status") or "PENDING").upper()
        if status not in _VERIFIED:
            return _decision_payload(
                due=False,
                reason="VERIFICATION_REQUIRED",
                current=current,
                interval=interval,
                scheduler_interval=scheduler_interval,
                deadline_window=deadline_window,
                source=source,
                budget=budget,
            )

    if budget["limit"] is not None:
        required = int(budget["reserved_requests_next_poll"] or 0)
        if required > int(budget["remaining"] or 0):
            return _decision_payload(
                due=False,
                reason="BUDGET_EXHAUSTED",
                current=current,
                interval=interval,
                scheduler_interval=scheduler_interval,
                deadline_window=deadline_window,
                source=source,
                budget=budget,
            )

    last_polled_at = _parse_dt(
        (((previous or {}).get("polling") or {}).get("last_polled_at"))
        or (previous or {}).get("last_polled_at")
        or (previous or {}).get("checked_at")
    )

    if previous is None or last_polled_at is None:
        due = True
        reason = "DUE"
    elif interval is None or interval <= scheduler_interval:
        current_slot = scheduler_slot_start(current, scheduler_interval)
        previous_slot = scheduler_slot_start(last_polled_at, scheduler_interval)
        due = current_slot != previous_slot
        reason = "DUE" if due else "ALREADY_POLLED_THIS_SLOT"
    else:
        due = (
            current.astimezone(timezone.utc) - last_polled_at.astimezone(timezone.utc)
        ).total_seconds() >= interval * 60
        reason = "DUE" if due else "NOT_DUE"

    return _decision_payload(
        due=due,
        reason=reason,
        current=current,
        interval=interval,
        scheduler_interval=scheduler_interval,
        deadline_window=deadline_window,
        source=source,
        budget=budget,
    )


def carry_forward_skipped(
    source: dict[str, Any],
    previous: dict[str, Any] | None,
    decision: dict[str, Any],
) -> dict[str, Any]:
    prior = dict(previous or {})
    reason = str(decision["reason"])
    has_data = bool(prior.get("data"))
    health = str(prior.get("health") or ("RED" if source.get("critical") and not has_data else "AMBER"))
    availability = prior.get("availability") or ("PARTIAL" if has_data else "UNAVAILABLE")
    effective_state = "SCHEDULED_CACHE"
    if reason == "VERIFICATION_REQUIRED":
        health = "AMBER"
        effective_state = "VERIFICATION_REQUIRED"
    elif reason == "BUDGET_EXHAUSTED":
        health = "AMBER"
        effective_state = "BUDGET_EXHAUSTED"

    payload = {
        **prior,
        "schema_version": 3,
        "source_id": source["id"],
        "source_name": source["name"],
        "category": source["category"],
        "adapter": source["adapter"],
        "critical": bool(source.get("critical")),
        "independence_group": source.get("independence_group"),
        "health": health,
        "availability": availability,
        "effective_state": effective_state,
        "changed": False,
        "duration_ms": 0.0,
        "polling": {
            **dict(prior.get("polling") or {}),
            **{key: value for key, value in decision.items() if key != "budget"},
            "skipped": True,
            "last_polled_at": ((prior.get("polling") or {}).get("last_polled_at")) or prior.get("checked_at"),
        },
        "budget": decision["budget"],
    }
    governance = dict(payload.get("governance") or {})
    governance.update(
        {
            "adaptive_polling": True,
            "scheduled_skip_is_not_transport_failure": True,
            "single_logical_acquisition_per_scheduler_slot": True,
            "budget_guard": decision["budget"].get("limit") is not None,
            "verification_gate": source.get("verification_required") is True,
        }
    )
    payload["governance"] = governance
    return payload


def attach_poll_result(
    source: dict[str, Any],
    payload: dict[str, Any],
    previous: dict[str, Any] | None,
    decision: dict[str, Any],
) -> dict[str, Any]:
    out = dict(payload)
    attempts = list(out.get("attempts") or [])
    provider_calls = sum(max(0, int(row.get("attempt_count") or 0)) for row in attempts)
    budget = dict(decision["budget"])
    if budget.get("limit") is not None:
        budget["requests_used"] = int(budget.get("requests_used") or 0) + provider_calls
        budget["remaining"] = max(0, int(budget["limit"]) - int(budget["requests_used"]))
    out["budget"] = budget
    out["polling"] = {
        **{key: value for key, value in decision.items() if key != "budget"},
        "skipped": False,
        "last_polled_at": out.get("checked_at") or utc_now(),
        "provider_calls_this_poll": provider_calls,
    }
    governance = dict(out.get("governance") or {})
    governance.update(
        {
            "adaptive_polling": True,
            "single_logical_acquisition_per_scheduler_slot": True,
            "budget_guard": budget.get("limit") is not None,
            "verification_gate": source.get("verification_required") is True,
        }
    )
    out["governance"] = governance
    return out
