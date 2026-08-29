from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.utils import CONFIG, parse_dt, read_json, utcnow

POLICY = CONFIG / "serving_improvement_registry.json"
WIB = ZoneInfo("Asia/Jakarta")


def _policy() -> dict:
    return (read_json(POLICY, {}) or {}).get("freshness") or {}


def _threshold(checkpoint: dict, phase: dict, policy: dict) -> tuple[int, str]:
    policy_id = str(checkpoint.get("policy_id") or "").upper()
    if bool(phase.get("is_live_match")) or "MATCH" in policy_id or str(checkpoint.get("operating_mode") or "").upper() == "MATCH_MODE":
        return int(policy.get("match_mode_max_age_minutes") or 10), "MATCH_MODE"
    if bool(checkpoint.get("deadline_day_active")) or "DEADLINE" in policy_id:
        return int(policy.get("deadline_day_max_age_minutes") or 30), "DEADLINE_DAY"
    return int(policy.get("normal_max_age_minutes") or 90), "NORMAL"


def evaluate_freshness(
    latest: dict,
    now: datetime | str | None = None,
    runtime_publish_at: str | None = None,
) -> dict:
    """Return explicit Official/runtime freshness without pretending non-:30 runs are master checkpoints."""
    policy = _policy()
    current = parse_dt(now) if isinstance(now, str) else now
    current = current or utcnow()
    if current.tzinfo is None:
        raise RuntimeError("freshness evaluation requires timezone-aware now")

    checkpoint = latest.get("checkpoint_context") or {}
    phase = latest.get("phase") or {}
    threshold, mode = _threshold(checkpoint, phase, policy)
    official_at_raw = latest.get("official_snapshot_at") or latest.get("generated_at")
    official_at = parse_dt(official_at_raw)
    generated_at = latest.get("generated_at")
    publish_at = runtime_publish_at or latest.get("runtime_publish_at")

    age = None
    if official_at:
        age = max(0.0, (current - official_at).total_seconds() / 60.0)
    partial_fraction = float(policy.get("partial_fraction") or 0.75)
    if age is None:
        state = "UNKNOWN"
    elif age > threshold:
        state = "STALE"
    elif age > threshold * partial_fraction:
        state = "PARTIAL"
    else:
        state = "FRESH"

    local = current.astimezone(WIB)
    master_minute = int(policy.get("master_minute") or 30)
    is_master_minute = local.minute == master_minute
    checkpoint_slot_state = "AUTHORITATIVE_MASTER_CHECKPOINT" if is_master_minute else "NON_MASTER_EVALUATION"
    authoritative = bool(is_master_minute and checkpoint.get("is_master_hourly_checkpoint"))

    return {
        "generated_at": generated_at,
        "official_snapshot_at": official_at_raw,
        "runtime_publish_at": publish_at,
        "source_age_minutes": round(age, 2) if age is not None else None,
        "freshness_state": state,
        "freshness_mode": mode,
        "max_source_age_minutes": threshold,
        "fresh_enough_for_decision": state in {"FRESH", "PARTIAL"},
        "fresh_enough_for_execution": state == "FRESH",
        "master_timezone": "Asia/Jakarta",
        "master_minute": master_minute,
        "evaluated_local_minute": local.minute,
        "checkpoint_slot_state": checkpoint_slot_state,
        "authoritative_master_checkpoint": authoritative,
        "non_master_evaluation_cannot_masquerade_as_master": True,
        "silent_carry_forward_as_fresh_forbidden": True,
    }
