from __future__ import annotations

import json
import os
from datetime import datetime, timezone
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


def scheduled_slot_already_completed(
    previous_manifest: dict[str, Any] | None,
    *,
    scheduler_interval_minutes: int = 60,
    now: datetime | None = None,
    event_name: str | None = None,
    schedule_kind: str | None = None,
) -> bool:
    """Return True when this logical hourly V6 slot already has authoritative data.

    Natural schedule and FPL Master orchestration share one operational slot, while
    natural-scheduler evidence remains tracked separately in runtime_control.
    Emergency manual recovery never completes an authoritative slot.
    """
    event = str(event_name or os.getenv("GITHUB_EVENT_NAME") or "local")
    kind = str(schedule_kind or os.getenv("V6_SCHEDULE_KIND") or "")
    authoritative_invocation = (
        event == "schedule"
        or (event == "workflow_dispatch" and kind == "master_orchestrated")
    )
    if not authoritative_invocation:
        return False
    previous = dict(previous_manifest or {})
    previous_control = dict(previous.get("runtime_control") or {})
    last_authoritative = _parse_dt(previous_control.get("last_authoritative_cycle_at"))
    if last_authoritative is None and event == "schedule":
        last_authoritative = _parse_dt(previous_control.get("last_scheduled_cycle_at"))
    if last_authoritative is None and previous_control.get("authoritative_runtime_snapshot") is True:
        last_authoritative = _parse_dt(previous_control.get("cycle_observed_at"))
    if last_authoritative is None:
        return False
    interval = max(1, int(scheduler_interval_minutes))
    return scheduler_slot_start(last_authoritative, interval) == scheduler_slot_start(_now(now), interval)


def build_runtime_control(
    previous_manifest: dict[str, Any] | None,
    *,
    scheduler_interval_minutes: int = 60,
    now: datetime | None = None,
    event_name: str | None = None,
    run_id: str | None = None,
    schedule_kind: str | None = None,
) -> dict[str, Any]:
    current = _now(now)
    scheduler_interval = max(1, int(scheduler_interval_minutes))
    slot = scheduler_slot_start(current, scheduler_interval)
    event = str(event_name or os.getenv("GITHUB_EVENT_NAME") or "local")
    scheduled_cycle = event == "schedule"
    kind = str(
        schedule_kind
        or os.getenv("V6_SCHEDULE_KIND")
        or ("scheduled" if scheduled_cycle else "manual")
    )
    master_orchestrated = event == "workflow_dispatch" and kind == "master_orchestrated"
    manual_recovery = event == "workflow_dispatch" and kind == "manual_recovery"
    authoritative_runtime_snapshot = (
        (scheduled_cycle and kind in {"primary", "recovery"})
        or master_orchestrated
    )
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
    if scheduled_cycle and previous_scheduled is not None:
        slot_gap = int(
            (
                slot - scheduler_slot_start(previous_scheduled, scheduler_interval)
            ).total_seconds()
            // (scheduler_interval * 60)
        )
        duplicate_scheduled_cycle = slot_gap == 0
        missed_cycle_count = max(0, slot_gap - 1)

    if scheduled_cycle:
        last_scheduled_cycle = slot
    else:
        last_scheduled_cycle = previous_scheduled

    previous_authoritative = _parse_dt(previous_control.get("last_authoritative_cycle_at"))
    if previous_authoritative is None and previous_control.get("authoritative_runtime_snapshot") is True:
        previous_authoritative = _parse_dt(previous_control.get("cycle_observed_at"))
    last_authoritative_cycle = slot if authoritative_runtime_snapshot else previous_authoritative

    if scheduled_cycle:
        health = "RED" if missed_cycle_count else ("AMBER" if duplicate_scheduled_cycle else "GREEN")
    elif master_orchestrated:
        health = "GREEN"
    else:
        health = "AMBER"
    expected = slot if (scheduled_cycle or master_orchestrated) else None
    schedule_lag_seconds = max(0.0, (current - slot).total_seconds()) if scheduled_cycle else None

    return {
        "schema_version": 3,
        "health": health,
        "event_name": event,
        "schedule_kind": kind,
        "run_id": str(run_id or os.getenv("GITHUB_RUN_ID") or "") or None,
        "scheduled_cycle": scheduled_cycle,
        "master_orchestrated": master_orchestrated,
        "manual_recovery": manual_recovery,
        "authoritative_runtime_snapshot": authoritative_runtime_snapshot,
        "counts_as_completed_scheduled_slot": scheduled_cycle,
        "counts_as_completed_operational_slot": authoritative_runtime_snapshot,
        "scheduler_interval_minutes": scheduler_interval,
        "expected_cycle_at": expected.isoformat() if expected else None,
        "cycle_observed_at": current.isoformat(),
        "schedule_lag_seconds": round(schedule_lag_seconds, 3) if schedule_lag_seconds is not None else None,
        "previous_scheduled_cycle_at": previous_scheduled.isoformat() if previous_scheduled else None,
        "last_scheduled_cycle_at": last_scheduled_cycle.isoformat() if last_scheduled_cycle else None,
        "last_authoritative_cycle_at": last_authoritative_cycle.isoformat() if last_authoritative_cycle else None,
        "missed_cycle": missed_cycle_count > 0,
        "missed_cycle_count": missed_cycle_count,
        "duplicate_scheduled_cycle": duplicate_scheduled_cycle,
        "baseline_inferred_from_legacy_manifest": baseline_inferred,
        "single_logical_acquisition_per_scheduler_slot": True,
    }


def apply_runtime_control(
    manifest: dict[str, Any],
    previous_manifest: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    event_name: str | None = None,
    run_id: str | None = None,
    schedule_kind: str | None = None,
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
    )

    control_failures = []
    if control["missed_cycle"]:
        control_failures.append("MISSED_SCHEDULED_CYCLE")
    if control["duplicate_scheduled_cycle"]:
        control_failures.append("DUPLICATE_SCHEDULED_CYCLE")
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
            "authoritative_trigger_kinds": ["primary", "recovery", "master_orchestrated"],
            "master_orchestrated_is_authoritative": True,
            "governed_manual_recovery_enabled": True,
            "manual_recovery_is_authoritative": False,
            "single_logical_acquisition_per_scheduler_slot": True,
            "runtime_schedule_health_is_manifested": True,
            "scheduled_recovery_is_idempotent": True,
        }
    )
    out["governance"] = governance

    source_overall = str(out.get("overall") or "AMBER")
    if control["health"] == "RED":
        out["overall"] = "RED"
    elif control["health"] == "AMBER" and source_overall == "GREEN":
        out["overall"] = "AMBER"

    return out, control


def main() -> int:
    previous_path = Path(os.getenv("V6_PREVIOUS_MANIFEST", "/tmp/v6-previous-manifest.json"))
    manifest = _read_json(MANIFEST)
    if not manifest:
        raise SystemExit("V6 manifest missing before runtime-control application")
    previous = _read_json(previous_path)
    updated, control = apply_runtime_control(manifest, previous)
    write_json(MANIFEST, updated)
    write_json(HEALTH / "runtime_control.json", control)
    print(json.dumps(control, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
