from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import ROOT


@dataclass(frozen=True)
class SchedulerPolicy:
    runtime_authority_id: str
    kind: str
    name: str
    timezone: str
    cadence_minutes: int
    physical_minute: int
    logical_slot_minute: int
    health_epoch: str
    green_after_consecutive_slots: int
    proof_fresh_after_minutes: int
    proof_stale_after_minutes: int


def _positive_int(value: Any, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"schedule_policy:{field}:must_be_integer") from exc
    if parsed <= 0:
        raise ValueError(f"schedule_policy:{field}:must_be_positive")
    return parsed


def load_schedule_policy(path: Path | None = None) -> SchedulerPolicy:
    config_path = path or (ROOT / "config" / "v6" / "schedule_policy.json")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"V6 schedule policy unavailable: {config_path}") from exc

    authority = dict(payload.get("scheduler_authority") or {})
    github = dict(payload.get("github_natural_schedule") or {})
    if authority.get("kind") != "CHATGPT_TASK":
        raise ValueError("schedule_policy:scheduler_authority.kind:must_be_CHATGPT_TASK")
    if github.get("enabled") is not False or github.get("authority") != "NONE":
        raise ValueError("schedule_policy:github_natural_schedule:must_be_disabled")

    cadence = _positive_int(authority.get("cadence_minutes"), "cadence_minutes")
    green_streak = _positive_int(
        authority.get("green_after_consecutive_slots"),
        "green_after_consecutive_slots",
    )
    proof_fresh = _positive_int(
        authority.get("proof_fresh_after_minutes"),
        "proof_fresh_after_minutes",
    )
    proof_stale = _positive_int(
        authority.get("proof_stale_after_minutes"),
        "proof_stale_after_minutes",
    )
    if proof_fresh < cadence:
        raise ValueError("schedule_policy:proof_fresh_after_minutes:must_cover_one_cadence")
    if proof_stale <= proof_fresh:
        raise ValueError("schedule_policy:proof_stale_after_minutes:must_exceed_fresh_threshold")

    runtime_authority_id = str(authority.get("runtime_authority_id") or "").strip()
    health_epoch = str(authority.get("health_epoch") or "").strip()
    name = str(authority.get("name") or "").strip()
    timezone_name = str(authority.get("timezone") or "").strip()
    if not runtime_authority_id or not health_epoch or not name or not timezone_name:
        raise ValueError("schedule_policy:scheduler_authority:required_identity_field_missing")

    physical_minute = int(authority.get("physical_minute"))
    logical_slot_minute = int(authority.get("logical_slot_minute"))
    if not 0 <= physical_minute <= 59 or not 0 <= logical_slot_minute <= 59:
        raise ValueError("schedule_policy:scheduler_authority:minute_out_of_range")

    return SchedulerPolicy(
        runtime_authority_id=runtime_authority_id,
        kind=str(authority["kind"]),
        name=name,
        timezone=timezone_name,
        cadence_minutes=cadence,
        physical_minute=physical_minute,
        logical_slot_minute=logical_slot_minute,
        health_epoch=health_epoch,
        green_after_consecutive_slots=green_streak,
        proof_fresh_after_minutes=proof_fresh,
        proof_stale_after_minutes=proof_stale,
    )


SCHEDULE_POLICY = load_schedule_policy()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def scheduler_proof_telemetry(
    last_proof_at: str | None,
    *,
    now: datetime | str | None = None,
    policy: SchedulerPolicy = SCHEDULE_POLICY,
) -> dict[str, Any]:
    proof = _parse_dt(last_proof_at)
    if isinstance(now, str):
        current = _parse_dt(now)
    elif isinstance(now, datetime):
        current = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    else:
        current = datetime.now(timezone.utc)

    if proof is None or current is None:
        return {
            "last_chatgpt_scheduler_proof_at": last_proof_at,
            "scheduler_proof_age_seconds": None,
            "scheduler_proof_freshness": "UNKNOWN",
            "scheduler_proof_health": "AMBER",
        }

    age_seconds = max(0.0, (current - proof).total_seconds())
    age_minutes = age_seconds / 60.0
    if age_minutes <= policy.proof_fresh_after_minutes:
        freshness, health = "FRESH", "GREEN"
    elif age_minutes <= policy.proof_stale_after_minutes:
        freshness, health = "LATE", "AMBER"
    else:
        freshness, health = "STALE", "RED"
    return {
        "last_chatgpt_scheduler_proof_at": proof.isoformat(),
        "scheduler_proof_age_seconds": round(age_seconds, 3),
        "scheduler_proof_freshness": freshness,
        "scheduler_proof_health": health,
    }
