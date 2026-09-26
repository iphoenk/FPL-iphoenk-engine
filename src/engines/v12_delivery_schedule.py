from __future__ import annotations

"""Revision-6 V12 visible-delivery schedule resolver.

This module is downstream of V6. It owns no factual acquisition and does not
schedule GitHub jobs. It deterministically resolves visible V12 report timing
from timezone-aware inputs so ChatGPT orchestration, workers and tests share one
policy instead of duplicating clock rules.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "delivery" / "v12_delivery_schedule.json"
WIB = ZoneInfo("Asia/Jakarta")
LONDON = ZoneInfo("Europe/London")


@dataclass(frozen=True)
class DeadlineCheckpoint:
    key: str
    at: datetime
    contract: str


@dataclass(frozen=True)
class DeliveryDecision:
    visible: bool
    primary_mode: str | None
    obligations: tuple[str, ...]
    deadline_checkpoint: str | None
    quiet_window: bool
    quiet_suppressed: bool
    single_visible_report: bool


def load_delivery_schedule(path: Path = _POLICY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("authority") != "FPL_V12_DELIVERY_SCHEDULE_REV6":
        raise ValueError("unsupported V12 delivery schedule authority")
    if payload.get("timezone") != "Asia/Jakarta":
        raise ValueError("delivery timezone must be Asia/Jakarta")
    if payload.get("price_timezone") != "Europe/London":
        raise ValueError("PRICE timezone must be Europe/London")
    if payload.get("governance", {}).get("v6_core_schedule_unchanged") is not True:
        raise ValueError("V6 core schedule must remain unchanged")
    return payload


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def _hm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


def _same_clock(value: datetime, hhmm: str) -> bool:
    hour, minute = _hm(hhmm)
    return value.hour == hour and value.minute == minute


def _in_quiet_window(local: datetime, policy: Mapping[str, Any]) -> bool:
    quiet = policy["quiet_window"]
    start_h, start_m = _hm(str(quiet["start"]))
    end_h, end_m = _hm(str(quiet["end"]))
    minute_of_day = local.hour * 60 + local.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    # Boundary checkpoints themselves remain visible; quiet is strictly between.
    return minute_of_day > start or minute_of_day < end


def price_checkpoint_for_london_date(local_date, *, policy: Mapping[str, Any] | None = None) -> datetime:
    p = dict(policy or load_delivery_schedule())
    hour, minute = _hm(str(p["price_local_time"]))
    london = datetime(local_date.year, local_date.month, local_date.day, hour, minute, tzinfo=LONDON)
    return london.astimezone(WIB)


def is_price_checkpoint(value: datetime, *, policy: Mapping[str, Any] | None = None) -> bool:
    p = dict(policy or load_delivery_schedule())
    observed = _aware(value).astimezone(LONDON)
    return _same_clock(observed, str(p["price_local_time"]))


def deadline_checkpoints(
    official_deadline: datetime,
    *,
    policy: Mapping[str, Any] | None = None,
) -> tuple[DeadlineCheckpoint, ...]:
    p = dict(policy or load_delivery_schedule())
    deadline = _aware(official_deadline)
    rows = []
    for raw in p["deadline_checkpoints"]:
        rows.append(
            DeadlineCheckpoint(
                key=str(raw["key"]),
                at=deadline - timedelta(minutes=int(raw["minutes_before"])),
                contract=str(raw["contract"]),
            )
        )
    return tuple(rows)


def _matched_deadline_checkpoint(
    observed_at: datetime,
    official_deadline: datetime | None,
    *,
    policy: Mapping[str, Any],
    tolerance_seconds: int,
) -> DeadlineCheckpoint | None:
    if official_deadline is None:
        return None
    observed = _aware(observed_at)
    matches = [
        row
        for row in deadline_checkpoints(official_deadline, policy=policy)
        if abs((observed - row.at).total_seconds()) <= tolerance_seconds
    ]
    if len(matches) > 1:
        raise ValueError("ambiguous deadline checkpoint")
    return matches[0] if matches else None


def precompute_window(
    visible_at: datetime,
    *,
    policy: Mapping[str, Any] | None = None,
) -> tuple[datetime, datetime]:
    p = dict(policy or load_delivery_schedule())
    at = _aware(visible_at)
    cfg = p["precompute"]
    return (
        at - timedelta(minutes=int(cfg["start_minutes_before"])),
        at - timedelta(minutes=int(cfg["freeze_target_minutes_before"])),
    )


def resolve_delivery_decision(
    observed_at: datetime,
    *,
    official_deadline: datetime | None = None,
    match_live: bool = False,
    post_all_match: bool = False,
    owner_adhoc: bool = False,
    tolerance_seconds: int = 60,
    policy: Mapping[str, Any] | None = None,
) -> DeliveryDecision:
    """Resolve one visible report decision.

    Multiple obligations are retained for rendering, but the resolver always
    returns at most one visible report. Deadline checkpoints are matched by
    absolute instant and therefore remain DST-safe.
    """
    p = dict(policy or load_delivery_schedule())
    observed = _aware(observed_at)
    local = observed.astimezone(WIB)
    obligations: list[str] = []

    if any(_same_clock(local, value) for value in p["fixed_deep_local_times"]):
        obligations.append("DEEP")
    if is_price_checkpoint(observed, policy=p):
        obligations.append("PRICE")
    if match_live:
        obligations.append("MATCH")
    if post_all_match:
        obligations.append("POST_ALL_MATCH")
    if owner_adhoc:
        obligations.append("ADHOC")

    checkpoint = _matched_deadline_checkpoint(
        observed,
        official_deadline,
        policy=p,
        tolerance_seconds=tolerance_seconds,
    )
    if checkpoint is not None:
        obligations.append(f"DEADLINE:{checkpoint.contract}")

    quiet = _in_quiet_window(local, p)
    deadline_override = False
    if official_deadline is not None:
        delta = _aware(official_deadline) - observed
        deadline_override = timedelta(0) <= delta <= timedelta(
            hours=float(p["quiet_window"]["deadline_override_from_hours"])
        )

    # Explicit owner requests and deadline T-3..lock bypass quiet suppression.
    quiet_suppressed = bool(
        quiet
        and not owner_adhoc
        and not deadline_override
        and not checkpoint
        and not any(item in {"DEEP", "PRICE"} for item in obligations)
    )
    visible = bool(obligations) and not quiet_suppressed

    priority = (
        "ADHOC",
        "DEADLINE:FINAL_CONFIRMATION",
        "DEADLINE:GO_NO_GO",
        "DEADLINE:FINAL_REVIEW",
        "DEADLINE:DELTA_EXECUTION",
        "DEADLINE:DELTA",
        "DEADLINE:DEEP",
        "POST_ALL_MATCH",
        "DEEP",
        "PRICE",
        "MATCH",
    )
    primary = next((name for name in priority if name in obligations), None)

    return DeliveryDecision(
        visible=visible,
        primary_mode=primary,
        obligations=tuple(dict.fromkeys(obligations)),
        deadline_checkpoint=checkpoint.key if checkpoint else None,
        quiet_window=quiet,
        quiet_suppressed=quiet_suppressed,
        single_visible_report=True,
    )
