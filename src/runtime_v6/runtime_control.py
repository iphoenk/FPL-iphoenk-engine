from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .store import HEALTH, MANIFEST, write_json


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


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


def _event_schedule_expression(explicit: str | None = None) -> str | None:
    if explicit is not None:
        value = str(explicit).strip()
        return value or None
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    event = _read_json(Path(event_path))
    value = str(event.get("schedule") or "").strip()
    return value or None


def _simple_hourly_cron_minute(expression: str | None) -> int | None:
    if not expression:
        return None
    parts = str(expression).split()
    if len(parts) != 5 or parts[1:] != ["*", "*", "*", "*"]:
        return None
    try:
        minute = int(parts[0])
    except ValueError:
        return None
    return minute if 0 <= minute <= 59 else None


def nominal_schedule_time(value: datetime, schedule_expression: str | None) -> datetime | None:
    minute = _simple_hourly_cron_minute(schedule_expression)
    if minute is None:
        return None
    current = _now(value)
    nominal = current.replace(minute=minute, second=0, microsecond=0)
    if nominal > current:
        nominal -= timedelta(hours=1)
    return nominal


def scheduled_invocation_slot(
    value: datetime,
    scheduler_interval_minutes: int,
    schedule_expression: str | None,
) -> datetime:
    nominal = nominal_schedule_time(value, schedule_expression)
    anchor = nominal if nominal is not None else _now(value)
    return scheduler_slot_start(anchor, scheduler_interval_minutes)


def _is_master(event: str, kind: str) -> bool:
    return event in {"workflow_dispatch", "issue_comment"} and kind == "master_orchestrated"


def _is_report_prefetch(event: str, kind: str) -> bool:
    return event in {"workflow_dispatch", "issue_comment"} and kind == "report_prefetch"


def scheduled_slot_already_completed(
    previous_manifest: dict[str, Any] | None,
    *,
    scheduler_interval_minutes: int = 60,
    now: datetime | None = None,
    event_name: str | None = None,
    schedule_kind: str | None = None,
    schedule_expression: str | None = None,
) -> bool:
    """Return True only for acquisition invocations whose core operational slot is done.

    Report-prefetch snapshots are authoritative publications but intentionally never
    complete or suppress the hourly core acquisition slot.
    """
    event = str(event_name or os.getenv("GITHUB_EVENT_NAME") or "local")
    kind = str(schedule_kind or os.getenv("V6_SCHEDULE_KIND") or "")
    operational_invocation = event == "schedule" or _is_master(event, kind)
    if not operational_invocation:
        return False

    previous = dict(previous_manifest or {})
    previous_control = dict(previous.get("runtime_control") or {})
    last_operational = _parse_dt(previous_control.get("last_operational_cycle_at"))
    if last_operational is None:
        last_operational = _parse_dt(previous_control.get("last_authoritative_cycle_at"))
    if last_operational is None and event == "schedule":
        last_operational = _parse_dt(previous_control.get("last_scheduled_cycle_at"))
    if last_operational is None and previous_control.get("counts_as_completed_operational_slot") is True:
        last_operational = _parse_dt(previous_control.get("cycle_observed_at"))
    if last_operational is None:
        return False

    interval = max(1, int(scheduler_interval_minutes))
    current = _now(now)
    if event == "schedule":
        expression = _event_schedule_expression(schedule_expression)
        current_slot = scheduled_invocation_slot(current, interval, expression)
    else:
        current_slot = scheduler_slot_start(current, interval)
    previous_slot = scheduler_slot_start(last_operational, interval)
    return previous_slot >= current_slot


def build_runtime_control(
    previous_manifest: dict[str, Any] | None,
    *,
    scheduler_interval_minutes: int = 60,
    now: datetime | None = None,
    event_name: str | None = None,
    run_id: str | None = None,
    schedule_kind: str | None = None,
    schedule_expression: str | None = None,
) -> dict[str, Any]:
    current = _now(now)
    scheduler_interval = max(1, int(scheduler_interval_minutes))
    event = str(event_name or os.getenv("GITHUB_EVENT_NAME") or "local")
    scheduled_cycle = event == "schedule"
    kind = str(schedule_kind or os.getenv("V6_SCHEDULE_KIND") or ("scheduled" if scheduled_cycle else "manual"))
    expression = _event_schedule_expression(schedule_expression) if scheduled_cycle else None
    nominal = nominal_schedule_time(current, expression) if scheduled_cycle else None
    slot = (
        scheduled_invocation_slot(current, scheduler_interval, expression)
        if scheduled_cycle
        else scheduler_slot_start(current, scheduler_interval)
    )

    master_orchestrated = _is_master(event, kind)
    report_prefetch = _is_report_prefetch(event, kind)
    manual_recovery = event == "workflow_dispatch" and kind == "manual_recovery"
    natural_authority = scheduled_cycle and kind in {"primary", "recovery"}
    authoritative_runtime_snapshot = natural_authority or master_orchestrated or report_prefetch
    completes_operational_slot = natural_authority or master_orchestrated

    previous = dict(previous_manifest or {})
    previous_control = dict(previous.get("runtime_control") or {})

    previous_scheduled = _parse_dt(previous_control.get("last_scheduled_cycle_at"))
    baseline_inferred = False
    if previous_scheduled is None:
        generated = _parse_dt(previous.get("generated_at"))
        if generated is not None:
            previous_scheduled = scheduler_slot_start(generated, scheduler_interval)
            baseline_inferred = True

    missed_cycle_count = 0
    duplicate_scheduled_cycle = False
    out_of_order_scheduled_cycle = False
    previous_scheduled_slot = (
        scheduler_slot_start(previous_scheduled, scheduler_interval)
        if previous_scheduled is not None
        else None
    )
    if scheduled_cycle and previous_scheduled_slot is not None:
        slot_gap = int((slot - previous_scheduled_slot).total_seconds() // (scheduler_interval * 60))
        duplicate_scheduled_cycle = slot_gap == 0
        out_of_order_scheduled_cycle = slot_gap < 0
        missed_cycle_count = max(0, slot_gap - 1)

    if scheduled_cycle:
        last_scheduled_cycle = (
            previous_scheduled_slot
            if previous_scheduled_slot is not None and previous_scheduled_slot > slot
            else slot
        )
    else:
        last_scheduled_cycle = previous_scheduled

    previous_operational = _parse_dt(previous_control.get("last_operational_cycle_at"))
    if previous_operational is None:
        previous_operational = _parse_dt(previous_control.get("last_authoritative_cycle_at"))
    if previous_operational is None and previous_control.get("counts_as_completed_operational_slot") is True:
        previous_operational = _parse_dt(previous_control.get("cycle_observed_at"))
    previous_operational_slot = (
        scheduler_slot_start(previous_operational, scheduler_interval)
        if previous_operational is not None
        else None
    )
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

    if scheduled_cycle:
        health = (
            "RED"
            if missed_cycle_count
            else ("AMBER" if duplicate_scheduled_cycle or out_of_order_scheduled_cycle else "GREEN")
        )
    elif master_orchestrated or report_prefetch:
        health = "GREEN"
    else:
        health = "AMBER"

    expected = slot if completes_operational_slot else None
    lag_anchor = nominal if nominal is not None else slot
    schedule_lag_seconds = max(0.0, (current - lag_anchor).total_seconds()) if scheduled_cycle else None

    return {
        "schema_version": 5,
        "health": health,
        "event_name": event,
        "schedule_kind": kind,
        "run_id": str(run_id or os.getenv("GITHUB_RUN_ID") or "") or None,
        "scheduled_cycle": scheduled_cycle,
        "master_orchestrated": master_orchestrated,
        "report_prefetch": report_prefetch,
        "manual_recovery": manual_recovery,
        "authoritative_runtime_snapshot": authoritative_runtime_snapshot,
        "counts_as_completed_scheduled_slot": scheduled_cycle,
        "counts_as_completed_operational_slot": completes_operational_slot,
        "counts_as_completed_report_slot": report_prefetch,
        "scheduler_interval_minutes": scheduler_interval,
        "schedule_expression": expression,
        "nominal_schedule_at": nominal.isoformat() if nominal else None,
        "nominal_schedule_resolved": nominal is not None if scheduled_cycle else None,
        "expected_cycle_at": expected.isoformat() if expected else None,
        "cycle_observed_at": current.isoformat(),
        "schedule_lag_seconds": round(schedule_lag_seconds, 3) if schedule_lag_seconds is not None else None,
        "previous_scheduled_cycle_at": previous_scheduled.isoformat() if previous_scheduled else None,
        "last_scheduled_cycle_at": last_scheduled_cycle.isoformat() if last_scheduled_cycle else None,
        "last_authoritative_cycle_at": last_operational_cycle.isoformat() if last_operational_cycle else None,
        "last_operational_cycle_at": last_operational_cycle.isoformat() if last_operational_cycle else None,
        "last_authoritative_snapshot_at": last_authoritative_snapshot.isoformat() if last_authoritative_snapshot else None,
        "missed_cycle": missed_cycle_count > 0,
        "missed_cycle_count": missed_cycle_count,
        "duplicate_scheduled_cycle": duplicate_scheduled_cycle,
        "out_of_order_scheduled_cycle": out_of_order_scheduled_cycle,
        "baseline_inferred_from_legacy_manifest": baseline_inferred,
        "single_logical_acquisition_per_scheduler_slot": True,
        "report_prefetch_cannot_complete_core_operational_slot": True,
        "scheduled_slot_uses_nominal_cron": scheduled_cycle and nominal is not None,
    }



def build_operational_slots(
    previous_ledger: dict[str, Any] | None,
    control: dict[str, Any],
    *,
    window_size: int = 48,
) -> dict[str, Any]:
    """Build factual rolling fulfillment telemetry without guessing skipped cron arrivals."""
    limit = max(1, int(window_size))
    previous = dict(previous_ledger or {})
    rows = [
        dict(row)
        for row in previous.get("slots") or []
        if isinstance(row, dict) and row.get("slot")
    ]

    if control.get("counts_as_completed_operational_slot") is True and control.get("expected_cycle_at"):
        kind = str(control.get("schedule_kind") or "")
        fulfilled_by = (
            "PRIMARY"
            if control.get("scheduled_cycle") is True and kind == "primary"
            else "RECOVERY"
            if control.get("scheduled_cycle") is True and kind == "recovery"
            else "MASTER"
            if control.get("master_orchestrated") is True
            else "OTHER"
        )
        slot = str(control["expected_cycle_at"])
        rows = [row for row in rows if str(row.get("slot")) != slot]
        rows.append(
            {
                "slot": slot,
                "fulfilled_by": fulfilled_by,
                "natural_scheduler_fulfillment": fulfilled_by in {"PRIMARY", "RECOVERY"},
                "master_orchestrated_fulfillment": fulfilled_by == "MASTER",
                "run_id": control.get("run_id"),
                "observed_at": control.get("cycle_observed_at"),
                "schedule_kind": control.get("schedule_kind"),
                "schedule_lag_seconds": control.get("schedule_lag_seconds"),
            }
        )

    rows.sort(key=lambda row: str(row.get("slot")))
    rows = rows[-limit:]
    tracked = len(rows)
    primary = sum(row.get("fulfilled_by") == "PRIMARY" for row in rows)
    recovery = sum(row.get("fulfilled_by") == "RECOVERY" for row in rows)
    master = sum(row.get("fulfilled_by") == "MASTER" for row in rows)
    natural = primary + recovery
    natural_ratio = round(natural / tracked, 4) if tracked else None
    master_ratio = round(master / tracked, 4) if tracked else None

    if tracked < 6:
        reliability_health = "AMBER"
        maturity = "WARMING_UP"
    elif natural_ratio is not None and natural_ratio >= 0.90:
        reliability_health = "GREEN"
        maturity = "ESTABLISHED"
    elif natural_ratio is not None and natural_ratio >= 0.75:
        reliability_health = "AMBER"
        maturity = "ESTABLISHED"
    else:
        reliability_health = "RED"
        maturity = "ESTABLISHED"

    return {
        "schema_version": 1,
        "generated_at": control.get("cycle_observed_at"),
        "window_size": limit,
        "slots": rows,
        "summary": {
            "health": reliability_health,
            "maturity": maturity,
            "tracked_operational_slots": tracked,
            "fulfilled_by_primary": primary,
            "fulfilled_by_recovery": recovery,
            "fulfilled_by_master": master,
            "natural_fulfilled_slots": natural,
            "natural_fulfillment_ratio": natural_ratio,
            "master_reliance_ratio": master_ratio,
            "reliability_basis": "FULFILLED_OPERATIONAL_SLOTS_ONLY",
            "post_fulfillment_skipped_cron_arrivals_observable": False,
            "data_availability_health_is_separate": True,
        },
        "governance": {
            "data_only": True,
            "scheduler_observability_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "natural_scheduler_presence_is_not_inferred": True,
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
    )

    control_failures: list[str] = []
    if control["missed_cycle"]:
        control_failures.append("MISSED_SCHEDULED_CYCLE")
    if control["duplicate_scheduled_cycle"]:
        control_failures.append("DUPLICATE_SCHEDULED_CYCLE")
    if control["out_of_order_scheduled_cycle"]:
        control_failures.append("OUT_OF_ORDER_SCHEDULED_CYCLE")
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
            "production_ingestion_schedule_only": control["scheduled_cycle"],
            "production_authoritative_snapshots_require_schedule": False,
            "production_authoritative_snapshots_require_governed_trigger": True,
            "authoritative_trigger_kinds": ["primary", "recovery", "master_orchestrated", "report_prefetch"],
            "operational_slot_completing_trigger_kinds": ["primary", "recovery", "master_orchestrated"],
            "master_orchestrated_is_authoritative": True,
            "report_prefetch_is_authoritative": True,
            "report_prefetch_completes_core_operational_slot": False,
            "governed_manual_recovery_enabled": True,
            "manual_recovery_is_authoritative": False,
            "single_logical_acquisition_per_scheduler_slot": True,
            "runtime_schedule_health_is_manifested": True,
            "scheduled_recovery_is_idempotent": True,
            "scheduled_slot_uses_nominal_cron": True,
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
        "natural_scheduler_presence_is_not_inferred": True,
        "scheduler_reliability_is_separate_from_data_availability": True,
    }
    write_json(MANIFEST, updated)
    write_json(HEALTH / "runtime_control.json", control)
    write_json(HEALTH / "operational_slots.json", ledger)
    print(json.dumps({"runtime_control": control, "operational_reliability": ledger["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
