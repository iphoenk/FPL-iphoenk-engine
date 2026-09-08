from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .legacy_scheduler_compat import event_schedule_expression as _event_schedule_expression
from .legacy_scheduler_compat import nominal_schedule_time, scheduled_invocation_slot
from .schedule_policy import SCHEDULE_POLICY, scheduler_proof_telemetry
from .store import HEALTH, MANIFEST, write_json

# Compatibility exports. Values come exclusively from config/v6/schedule_policy.json.
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


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc) if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)


def scheduler_slot_start(value: datetime, scheduler_interval_minutes: int) -> datetime:
    current = _now(value)
    seconds = max(60, int(scheduler_interval_minutes) * 60)
    epoch = int(current.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _is_chatgpt_scheduler(event: str, kind: str) -> bool:
    return event == "issue_comment" and kind == "chatgpt_scheduler"


def _is_master(event: str, kind: str) -> bool:
    return event in {"workflow_dispatch", "issue_comment"} and kind in {"master_orchestrated", "chatgpt_scheduler"}


def _is_report_prefetch(event: str, kind: str) -> bool:
    return event in {"workflow_dispatch", "issue_comment"} and kind == "report_prefetch"


def _chatgpt_logical_slot(explicit: str | None = None) -> datetime | None:
    value = explicit if explicit is not None else os.getenv("V6_MASTER_LOGICAL_SLOT")
    parsed = _parse_dt(value)
    return parsed


def scheduled_slot_already_completed(
    previous_manifest: dict[str, Any] | None,
    *,
    scheduler_interval_minutes: int | None = None,
    now: datetime | None = None,
    event_name: str | None = None,
    schedule_kind: str | None = None,
    schedule_expression: str | None = None,
    logical_slot: str | None = None,
) -> bool:
    """Guard duplicate work while still allowing the first ChatGPT proof for a slot.

    Dormant GitHub schedule events are always skipped. A ChatGPT scheduler command is
    allowed to publish its scheduler proof when the slot was previously fulfilled by
    another authority, but a second ChatGPT proof for the same logical slot is skipped.
    """
    event = str(event_name or os.getenv("GITHUB_EVENT_NAME") or "local")
    kind = str(schedule_kind or os.getenv("V6_SCHEDULE_KIND") or "")
    if event == "schedule" and kind == "schedule_disabled":
        return True

    chatgpt_scheduler = _is_chatgpt_scheduler(event, kind)
    operational_invocation = chatgpt_scheduler or _is_master(event, kind) or (
        event == "schedule" and kind in {"primary", "recovery"}
    )
    if not operational_invocation:
        return False

    previous = dict(previous_manifest or {})
    previous_control = dict(previous.get("runtime_control") or {})
    interval = max(1, int(scheduler_interval_minutes or SCHEDULE_POLICY.cadence_minutes))
    current = _now(now)

    if chatgpt_scheduler:
        slot_value = _chatgpt_logical_slot(logical_slot)
        if slot_value is None:
            return False
        current_slot = scheduler_slot_start(slot_value, interval)
        previous_chatgpt = _parse_dt(previous_control.get("last_chatgpt_scheduler_cycle_at"))
        if previous_chatgpt is None:
            return False
        return scheduler_slot_start(previous_chatgpt, interval) >= current_slot

    previous_operational = _parse_dt(previous_control.get("last_operational_cycle_at"))
    if previous_operational is None:
        previous_operational = _parse_dt(previous_control.get("last_authoritative_cycle_at"))
    if previous_operational is None and previous_control.get("counts_as_completed_operational_slot") is True:
        previous_operational = _parse_dt(previous_control.get("cycle_observed_at"))
    if previous_operational is None:
        return False

    if event == "schedule":
        expression = _event_schedule_expression(schedule_expression)
        current_slot = scheduled_invocation_slot(current, interval, expression)
    else:
        current_slot = scheduler_slot_start(current, interval)
    return scheduler_slot_start(previous_operational, interval) >= current_slot


def build_runtime_control(
    previous_manifest: dict[str, Any] | None,
    *,
    scheduler_interval_minutes: int | None = None,
    now: datetime | None = None,
    event_name: str | None = None,
    run_id: str | None = None,
    schedule_kind: str | None = None,
    schedule_expression: str | None = None,
    logical_slot: str | None = None,
) -> dict[str, Any]:
    current = _now(now)
    interval = max(1, int(scheduler_interval_minutes or SCHEDULE_POLICY.cadence_minutes))
    event = str(event_name or os.getenv("GITHUB_EVENT_NAME") or "local")
    kind = str(schedule_kind or os.getenv("V6_SCHEDULE_KIND") or "manual")

    github_schedule_event = event == "schedule"
    github_schedule_disabled = github_schedule_event and kind == "schedule_disabled"
    chatgpt_scheduler = _is_chatgpt_scheduler(event, kind)
    master_orchestrated = _is_master(event, kind)
    report_prefetch = _is_report_prefetch(event, kind)
    manual_recovery = event == "workflow_dispatch" and kind == "manual_recovery"

    if chatgpt_scheduler:
        requested_slot = _chatgpt_logical_slot(logical_slot)
        if requested_slot is None:
            raise ValueError("ChatGPT scheduler invocation requires V6_MASTER_LOGICAL_SLOT")
        slot = scheduler_slot_start(requested_slot, interval)
        expression = None
        nominal = None
    elif github_schedule_event:
        expression = _event_schedule_expression(schedule_expression)
        nominal = nominal_schedule_time(current, expression)
        slot = scheduled_invocation_slot(current, interval, expression)
    else:
        expression = None
        nominal = None
        slot = scheduler_slot_start(current, interval)

    authoritative_runtime_snapshot = chatgpt_scheduler or master_orchestrated or report_prefetch
    completes_operational_slot = chatgpt_scheduler or master_orchestrated

    previous = dict(previous_manifest or {})
    previous_control = dict(previous.get("runtime_control") or {})
    previous_chatgpt = _parse_dt(previous_control.get("last_chatgpt_scheduler_cycle_at"))
    previous_chatgpt_slot = scheduler_slot_start(previous_chatgpt, interval) if previous_chatgpt else None

    missed_cycle_count = 0
    duplicate_scheduler_cycle = False
    out_of_order_scheduler_cycle = False
    if chatgpt_scheduler and previous_chatgpt_slot is not None:
        slot_gap = int((slot - previous_chatgpt_slot).total_seconds() // (interval * 60))
        duplicate_scheduler_cycle = slot_gap == 0
        out_of_order_scheduler_cycle = slot_gap < 0
        missed_cycle_count = max(0, slot_gap - 1)

    if chatgpt_scheduler:
        last_chatgpt_scheduler_cycle = (
            previous_chatgpt_slot
            if previous_chatgpt_slot is not None and previous_chatgpt_slot > slot
            else slot
        )
    else:
        last_chatgpt_scheduler_cycle = previous_chatgpt

    previous_operational = _parse_dt(previous_control.get("last_operational_cycle_at"))
    if previous_operational is None:
        previous_operational = _parse_dt(previous_control.get("last_authoritative_cycle_at"))
    if previous_operational is None and previous_control.get("counts_as_completed_operational_slot") is True:
        previous_operational = _parse_dt(previous_control.get("cycle_observed_at"))
    previous_operational_slot = scheduler_slot_start(previous_operational, interval) if previous_operational else None
    if completes_operational_slot:
        last_operational_cycle = (
            previous_operational_slot
            if previous_operational_slot is not None and previous_operational_slot > slot
            else slot
        )
    else:
        last_operational_cycle = previous_operational

    previous_snapshot = _parse_dt(previous_control.get("last_authoritative_snapshot_at"))
    if previous_snapshot is None and previous_control.get("authoritative_runtime_snapshot") is True:
        previous_snapshot = _parse_dt(previous_control.get("cycle_observed_at"))
    last_authoritative_snapshot = current if authoritative_runtime_snapshot else previous_snapshot

    if chatgpt_scheduler:
        health = "RED" if missed_cycle_count else ("AMBER" if duplicate_scheduler_cycle or out_of_order_scheduler_cycle else "GREEN")
    elif master_orchestrated or report_prefetch:
        health = "GREEN"
    elif github_schedule_disabled:
        health = "AMBER"
    elif manual_recovery:
        health = "AMBER"
    else:
        health = "AMBER"

    previous_github_schedule = _parse_dt(previous_control.get("last_github_scheduled_cycle_at"))
    if previous_github_schedule is None:
        previous_github_schedule = _parse_dt(previous_control.get("last_scheduled_cycle_at"))
    if github_schedule_event and not github_schedule_disabled:
        last_github_schedule = slot
    else:
        last_github_schedule = previous_github_schedule

    expected = slot if completes_operational_slot else None
    data_slot_already_fulfilled = previous_operational_slot is not None and previous_operational_slot >= slot

    return {
        "schema_version": 6,
        "health": health,
        "event_name": event,
        "schedule_kind": kind,
        "run_id": str(run_id or os.getenv("GITHUB_RUN_ID") or "") or None,
        "scheduler_authority": CHATGPT_SCHEDULER_AUTHORITY,
        "scheduler_epoch": CHATGPT_SCHEDULER_EPOCH,
        "chatgpt_scheduler": chatgpt_scheduler,
        "chatgpt_scheduler_proof": chatgpt_scheduler,
        "github_schedule_event": github_schedule_event,
        "github_schedule_disabled": github_schedule_disabled,
        "scheduled_cycle": chatgpt_scheduler,
        "master_orchestrated": master_orchestrated,
        "report_prefetch": report_prefetch,
        "manual_recovery": manual_recovery,
        "authoritative_runtime_snapshot": authoritative_runtime_snapshot,
        "counts_as_completed_scheduled_slot": chatgpt_scheduler,
        "counts_as_completed_operational_slot": completes_operational_slot,
        "counts_as_completed_report_slot": report_prefetch,
        "scheduler_interval_minutes": interval,
        "schedule_expression": expression,
        "nominal_schedule_at": nominal.isoformat() if nominal else None,
        "nominal_schedule_resolved": nominal is not None if github_schedule_event else None,
        "logical_slot_source": "CHATGPT_COMMAND" if chatgpt_scheduler else "RUNTIME_CLOCK",
        "expected_cycle_at": expected.isoformat() if expected else None,
        "cycle_observed_at": current.isoformat(),
        "schedule_lag_seconds": round(max(0.0, (current - slot).total_seconds()), 3) if chatgpt_scheduler else None,
        "last_chatgpt_scheduler_cycle_at": last_chatgpt_scheduler_cycle.isoformat() if last_chatgpt_scheduler_cycle else None,
        "last_scheduled_cycle_at": last_chatgpt_scheduler_cycle.isoformat() if last_chatgpt_scheduler_cycle else None,
        "last_github_scheduled_cycle_at": last_github_schedule.isoformat() if last_github_schedule else None,
        "last_authoritative_cycle_at": last_operational_cycle.isoformat() if last_operational_cycle else None,
        "last_operational_cycle_at": last_operational_cycle.isoformat() if last_operational_cycle else None,
        "last_authoritative_snapshot_at": last_authoritative_snapshot.isoformat() if last_authoritative_snapshot else None,
        "missed_cycle": missed_cycle_count > 0,
        "missed_cycle_count": missed_cycle_count,
        "duplicate_scheduled_cycle": duplicate_scheduler_cycle,
        "out_of_order_scheduled_cycle": out_of_order_scheduler_cycle,
        "baseline_inferred_from_legacy_manifest": False,
        "data_slot_already_fulfilled_before_scheduler_proof": data_slot_already_fulfilled if chatgpt_scheduler else False,
        "single_logical_acquisition_per_scheduler_slot": True,
        "report_prefetch_cannot_complete_core_operational_slot": True,
        "scheduled_slot_uses_nominal_cron": False,
    }


def _legacy_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tracked_slots": len(rows),
        "primary": sum(row.get("fulfilled_by") == "PRIMARY" for row in rows),
        "recovery": sum(row.get("fulfilled_by") == "RECOVERY" for row in rows),
        "master": sum(row.get("fulfilled_by") == "MASTER" for row in rows),
        "missing": sum(row.get("fulfilled_by") == "MISSING" for row in rows),
        "health_authority": "HISTORICAL_ONLY",
    }


def _densify_chatgpt_rows(rows: list[dict[str, Any]], interval_minutes: int, window_size: int) -> list[dict[str, Any]]:
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
    """Build current ChatGPT scheduler epoch plus immutable legacy scheduler evidence."""
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
                    "data_slot_already_fulfilled_before_scheduler_proof": control.get("data_slot_already_fulfilled_before_scheduler_proof", False),
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

    active_rows = _densify_chatgpt_rows(active_rows, int(control.get("scheduler_interval_minutes") or 60), limit)
    auxiliary_rows = sorted(auxiliary_rows, key=lambda row: str(row.get("slot")))[-limit:]
    legacy_rows = sorted(legacy_rows, key=lambda row: str(row.get("slot")))[-limit:]

    tracked = len(active_rows)
    fulfilled = sum(row.get("fulfilled") is True and row.get("fulfilled_by") == "CHATGPT" for row in active_rows)
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
        "epoch": epoch or {
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


def apply_runtime_control(
    manifest: dict[str, Any],
    previous_manifest: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    event_name: str | None = None,
    run_id: str | None = None,
    schedule_kind: str | None = None,
    schedule_expression: str | None = None,
    logical_slot: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    out = dict(manifest)
    polling = dict(out.get("polling") or {})
    scheduler_interval = max(1, int(polling.get("scheduler_interval_minutes") or 60))
    control = build_runtime_control(
        previous_manifest,
        scheduler_interval_minutes=scheduler_interval,
        now=now,
        event_name=event_name,
        run_id=run_id,
        schedule_kind=schedule_kind,
        schedule_expression=schedule_expression,
        logical_slot=logical_slot,
    )

    control_failures: list[str] = []
    if control["missed_cycle"]:
        control_failures.append("MISSED_CHATGPT_SCHEDULER_SLOT")
    if control["duplicate_scheduled_cycle"]:
        control_failures.append("DUPLICATE_CHATGPT_SCHEDULER_SLOT")
    if control["out_of_order_scheduled_cycle"]:
        control_failures.append("OUT_OF_ORDER_CHATGPT_SCHEDULER_SLOT")
    if control["manual_recovery"]:
        control_failures.append("NON_AUTHORITATIVE_MANUAL_RECOVERY")

    out["runtime_control"] = control
    out["control_failures"] = control_failures
    paths = dict(out.get("paths") or {})
    paths["runtime_control"] = "data/v6/health/runtime_control.json"
    out["paths"] = paths
    governance = dict(out.get("governance") or {})
    governance.update(
        {
            "production_ingestion_schedule_only": False,
            "production_authoritative_snapshots_require_schedule": False,
            "production_authoritative_snapshots_require_governed_trigger": True,
            "scheduler_authority": CHATGPT_SCHEDULER_AUTHORITY,
            "scheduler_epoch": CHATGPT_SCHEDULER_EPOCH,
            "github_natural_scheduler_is_authority": False,
            "chatgpt_scheduler_is_authority": True,
            "authoritative_trigger_kinds": ["chatgpt_scheduler", "master_orchestrated", "report_prefetch"],
            "operational_slot_completing_trigger_kinds": ["chatgpt_scheduler", "master_orchestrated"],
            "scheduler_health_proof_trigger_kind": "chatgpt_scheduler",
            "master_orchestrated_is_authoritative": True,
            "generic_master_dispatch_does_not_count_as_scheduler_health_proof": True,
            "report_prefetch_is_authoritative": True,
            "report_prefetch_completes_core_operational_slot": False,
            "governed_manual_recovery_enabled": True,
            "manual_recovery_is_authoritative": False,
            "single_logical_acquisition_per_scheduler_slot": True,
            "runtime_schedule_health_is_manifested": True,
            "github_scheduled_recovery_enabled": False,
            "scheduled_recovery_is_idempotent": True,
            "scheduled_slot_uses_nominal_cron": False,
        }
    )
    out["governance"] = governance
    out["data_availability_health"] = str(out.get("overall") or "AMBER")
    out["runtime_control_health"] = control["health"]
    governance["scheduler_reliability_does_not_override_data_availability"] = True
    out["governance"] = governance
    return out, control


def main() -> int:
    previous_path = Path(os.getenv("V6_PREVIOUS_MANIFEST", "/tmp/v6-previous-manifest.json"))
    manifest = _read_json(MANIFEST)
    if not manifest:
        raise SystemExit("V6 manifest missing before runtime-control application")
    previous = _read_json(previous_path)
    previous_ledger = _read_json(HEALTH / "operational_slots.json")
    updated, control = apply_runtime_control(manifest, previous)
    ledger = build_operational_slots(previous_ledger, control, window_size=48)
    updated["operational_reliability"] = ledger["summary"]
    updated["paths"] = {
        **dict(updated.get("paths") or {}),
        "operational_slots": "data/v6/health/operational_slots.json",
    }
    updated["governance"] = {
        **dict(updated.get("governance") or {}),
        "operational_slot_ledger_is_factual_only": True,
        "chatgpt_scheduler_is_current_health_authority": True,
        "legacy_github_scheduler_evidence_is_historical_only": True,
        "scheduler_reliability_is_separate_from_data_availability": True,
    }
    write_json(MANIFEST, updated)
    write_json(HEALTH / "runtime_control.json", control)
    write_json(HEALTH / "operational_slots.json", ledger)
    print(json.dumps({"runtime_control": control, "operational_reliability": ledger["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
