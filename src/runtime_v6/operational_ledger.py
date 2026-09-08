from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .schedule_policy import SCHEDULE_POLICY, scheduler_proof_telemetry

CHATGPT_SCHEDULER_AUTHORITY = SCHEDULE_POLICY.runtime_authority_id
CHATGPT_SCHEDULER_EPOCH = SCHEDULE_POLICY.health_epoch
CHATGPT_GREEN_STREAK = SCHEDULE_POLICY.green_after_consecutive_slots


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _legacy_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tracked_slots": len(rows),
        "primary": sum(row.get("fulfilled_by") == "PRIMARY" for row in rows),
        "recovery": sum(row.get("fulfilled_by") == "RECOVERY" for row in rows),
        "master": sum(row.get("fulfilled_by") == "MASTER" for row in rows),
        "missing": sum(row.get("fulfilled_by") == "MISSING" for row in rows),
        "health_authority": "HISTORICAL_ONLY",
    }


def _densify_chatgpt_rows(
    rows: list[dict[str, Any]],
    interval_minutes: int,
    window_size: int,
) -> list[dict[str, Any]]:
    existing = {
        str(row.get("slot")): dict(row)
        for row in rows
        if isinstance(row, dict) and _parse_dt(str(row.get("slot") or "")) is not None
    }
    ordered = sorted((_parse_dt(slot), slot) for slot in existing)
    if ordered:
        cursor = ordered[0][0]
        end = ordered[-1][0]
        assert cursor is not None and end is not None
        step = timedelta(minutes=max(1, int(interval_minutes)))
        while cursor <= end:
            key = cursor.isoformat()
            if key not in existing:
                existing[key] = {
                    "slot": key,
                    "fulfilled_by": "MISSING",
                    "fulfilled": False,
                    "chatgpt_scheduler_fulfillment": False,
                    "run_id": None,
                    "observed_at": None,
                    "schedule_kind": "chatgpt_scheduler",
                    "schedule_lag_seconds": None,
                    "missing_reason": "NO_CHATGPT_MASTER_SCHEDULER_PROOF_BEFORE_LATER_SLOT",
                    "missing_classification_is_retrospective": True,
                }
            cursor += step
    return [existing[key] for key in sorted(existing)][-max(1, int(window_size)):]


def build_operational_slots(
    previous_ledger: dict[str, Any] | None,
    control: dict[str, Any],
    *,
    window_size: int = 48,
) -> dict[str, Any]:
    """Build factual ChatGPT scheduler epoch plus immutable legacy evidence."""
    limit = max(1, int(window_size))
    previous = dict(previous_ledger or {})
    previous_schema = int(previous.get("schema_version") or 0)

    if previous_schema >= 3:
        legacy_rows = [dict(row) for row in previous.get("legacy_slots") or [] if isinstance(row, dict)]
        active_rows = [dict(row) for row in previous.get("slots") or [] if isinstance(row, dict)]
        auxiliary_rows = [dict(row) for row in previous.get("auxiliary_operational_slots") or [] if isinstance(row, dict)]
        epoch = dict(previous.get("epoch") or {})
    else:
        legacy_rows = [dict(row) for row in previous.get("slots") or [] if isinstance(row, dict)]
        active_rows = []
        auxiliary_rows = []
        epoch = {}

    if control.get("counts_as_completed_operational_slot") is True and control.get("expected_cycle_at"):
        slot = str(control["expected_cycle_at"])
        if control.get("chatgpt_scheduler") is True:
            active_rows = [row for row in active_rows if str(row.get("slot")) != slot]
            active_rows.append(
                {
                    "slot": slot,
                    "fulfilled_by": "CHATGPT",
                    "fulfilled": True,
                    "chatgpt_scheduler_fulfillment": True,
                    "run_id": control.get("run_id"),
                    "observed_at": control.get("cycle_observed_at"),
                    "schedule_kind": "chatgpt_scheduler",
                    "schedule_lag_seconds": control.get("schedule_lag_seconds"),
                    "data_slot_already_fulfilled_before_scheduler_proof": control.get(
                        "data_slot_already_fulfilled_before_scheduler_proof",
                        False,
                    ),
                }
            )
            epoch.setdefault("id", CHATGPT_SCHEDULER_EPOCH)
            epoch.setdefault("authority", CHATGPT_SCHEDULER_AUTHORITY)
            epoch.setdefault("start_at", slot)
            epoch.setdefault("green_after_consecutive_slots", CHATGPT_GREEN_STREAK)
        else:
            auxiliary_rows = [row for row in auxiliary_rows if str(row.get("slot")) != slot]
            auxiliary_rows.append(
                {
                    "slot": slot,
                    "fulfilled_by": "MASTER_AUXILIARY",
                    "fulfilled": True,
                    "run_id": control.get("run_id"),
                    "observed_at": control.get("cycle_observed_at"),
                    "schedule_kind": control.get("schedule_kind"),
                }
            )

    interval = int(control.get("scheduler_interval_minutes") or SCHEDULE_POLICY.cadence_minutes)
    active_rows = _densify_chatgpt_rows(active_rows, interval, limit)
    auxiliary_rows = sorted(auxiliary_rows, key=lambda row: str(row.get("slot")))[-limit:]
    legacy_rows = sorted(legacy_rows, key=lambda row: str(row.get("slot")))[-limit:]

    tracked = len(active_rows)
    fulfilled = sum(
        row.get("fulfilled") is True and row.get("fulfilled_by") == "CHATGPT"
        for row in active_rows
    )
    missing = sum(row.get("fulfilled_by") == "MISSING" for row in active_rows)
    ratio = round(fulfilled / tracked, 4) if tracked else None

    consecutive = 0
    for row in reversed(active_rows):
        if row.get("fulfilled_by") == "CHATGPT" and row.get("fulfilled") is True:
            consecutive += 1
        else:
            break

    if tracked < CHATGPT_GREEN_STREAK:
        health, maturity = "AMBER", "WARMING_UP"
    elif consecutive >= CHATGPT_GREEN_STREAK:
        health, maturity = "GREEN", "ESTABLISHED"
    elif ratio is not None and ratio >= 0.80:
        health, maturity = "AMBER", "ESTABLISHED"
    else:
        health, maturity = "RED", "ESTABLISHED"

    latest_proof_at = None
    for row in reversed(active_rows):
        if row.get("fulfilled_by") == "CHATGPT" and row.get("fulfilled") is True:
            latest_proof_at = row.get("observed_at")
            break

    proof_telemetry = scheduler_proof_telemetry(
        str(latest_proof_at) if latest_proof_at else None,
        now=control.get("cycle_observed_at"),
    )

    return {
        "schema_version": 3,
        "generated_at": control.get("cycle_observed_at"),
        "window_size": limit,
        "epoch": epoch
        or {
            "id": CHATGPT_SCHEDULER_EPOCH,
            "authority": CHATGPT_SCHEDULER_AUTHORITY,
            "start_at": None,
            "green_after_consecutive_slots": CHATGPT_GREEN_STREAK,
        },
        "slots": active_rows,
        "auxiliary_operational_slots": auxiliary_rows,
        "legacy_slots": legacy_rows,
        "legacy_summary": _legacy_summary(legacy_rows),
        "summary": {
            "health": health,
            "maturity": maturity,
            "scheduler_authority": CHATGPT_SCHEDULER_AUTHORITY,
            "scheduler_epoch": CHATGPT_SCHEDULER_EPOCH,
            "tracked_operational_slots": tracked,
            "fulfilled_operational_slots": fulfilled,
            "missing_operational_slots": missing,
            "fulfilled_by_chatgpt": fulfilled,
            "chatgpt_fulfillment_ratio": ratio,
            "scheduler_fulfillment_ratio": ratio,
            "consecutive_successful_slots": consecutive,
            "required_consecutive_successes": CHATGPT_GREEN_STREAK,
            **proof_telemetry,
            "proof_fresh_after_minutes": SCHEDULE_POLICY.proof_fresh_after_minutes,
            "proof_stale_after_minutes": SCHEDULE_POLICY.proof_stale_after_minutes,
            "auxiliary_master_slots": len(auxiliary_rows),
            "reliability_basis": "CHATGPT_MASTER_LOGICAL_HOURLY_SLOTS",
            "legacy_github_scheduler_excluded_from_current_health": True,
            "data_availability_health_is_separate": True,
        },
        "governance": {
            "data_only": True,
            "scheduler_observability_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "chatgpt_scheduler_is_current_health_authority": True,
            "generic_master_is_not_scheduler_health_proof": True,
            "github_scheduler_is_not_current_health_authority": True,
            "legacy_scheduler_evidence_preserved": True,
            "missing_slots_are_retrospective_only": True,
            "scheduler_policy_source": "config/v6/schedule_policy.json",
            "scheduler_proof_age_does_not_fabricate_slots": True,
        },
    }
