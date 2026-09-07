from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .store import HEALTH, MANIFEST, read_json, write_json


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def densify_operational_slots(
    ledger: dict[str, Any] | None,
    *,
    interval_minutes: int = 60,
    window_size: int = 48,
) -> dict[str, Any]:
    """Densify observed slot history with factual missed-slot rows.

    A missing row is emitted only between two already-observed operational slots, so
    V6 never guesses about a future/current slot or about a cron arrival that was
    skipped after another authority had already fulfilled the slot.
    """
    source = dict(ledger or {})
    interval = max(1, int(interval_minutes))
    limit = max(1, int(window_size))
    existing = {
        str(row.get("slot")): dict(row)
        for row in source.get("slots") or []
        if isinstance(row, dict) and _parse(row.get("slot")) is not None
    }
    ordered = sorted((_parse(slot), slot) for slot in existing)
    if ordered:
        cursor = ordered[0][0]
        end = ordered[-1][0]
        assert cursor is not None and end is not None
        step = timedelta(minutes=interval)
        while cursor <= end:
            slot = cursor.isoformat()
            if slot not in existing:
                existing[slot] = {
                    "slot": slot,
                    "fulfilled_by": "MISSING",
                    "fulfilled": False,
                    "natural_scheduler_fulfillment": False,
                    "master_orchestrated_fulfillment": False,
                    "run_id": None,
                    "observed_at": None,
                    "schedule_kind": None,
                    "schedule_lag_seconds": None,
                    "missing_reason": "NO_AUTHORITATIVE_OPERATIONAL_SNAPSHOT_OBSERVED_BEFORE_LATER_SLOT",
                    "missing_classification_is_retrospective": True,
                }
            cursor += step

    rows = [existing[key] for key in sorted(existing)][-limit:]
    for row in rows:
        row.setdefault("fulfilled", row.get("fulfilled_by") in {"PRIMARY", "RECOVERY", "MASTER"})

    tracked = len(rows)
    primary = sum(row.get("fulfilled_by") == "PRIMARY" for row in rows)
    recovery = sum(row.get("fulfilled_by") == "RECOVERY" for row in rows)
    master = sum(row.get("fulfilled_by") == "MASTER" for row in rows)
    missing = sum(row.get("fulfilled_by") == "MISSING" for row in rows)
    natural = primary + recovery
    fulfilled = natural + master
    natural_ratio = round(natural / tracked, 4) if tracked else None
    fulfillment_ratio = round(fulfilled / tracked, 4) if tracked else None
    master_ratio = round(master / tracked, 4) if tracked else None

    if tracked < 6:
        health, maturity = "AMBER", "WARMING_UP"
    elif natural_ratio is not None and natural_ratio >= 0.90:
        health, maturity = "GREEN", "ESTABLISHED"
    elif natural_ratio is not None and natural_ratio >= 0.75:
        health, maturity = "AMBER", "ESTABLISHED"
    else:
        health, maturity = "RED", "ESTABLISHED"

    return {
        **source,
        "schema_version": 2,
        "window_size": limit,
        "slots": rows,
        "summary": {
            "health": health,
            "maturity": maturity,
            "tracked_operational_slots": tracked,
            "fulfilled_operational_slots": fulfilled,
            "missing_operational_slots": missing,
            "fulfilled_by_primary": primary,
            "fulfilled_by_recovery": recovery,
            "fulfilled_by_master": master,
            "natural_fulfilled_slots": natural,
            "operational_fulfillment_ratio": fulfillment_ratio,
            "natural_fulfillment_ratio": natural_ratio,
            "master_reliance_ratio": master_ratio,
            "reliability_basis": "EXPECTED_SLOTS_BETWEEN_OBSERVED_OPERATIONAL_BOUNDARIES",
            "post_fulfillment_skipped_cron_arrivals_observable": False,
            "data_availability_health_is_separate": True,
        },
        "governance": {
            **dict(source.get("governance") or {}),
            "data_only": True,
            "scheduler_observability_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "natural_scheduler_presence_is_not_inferred": True,
            "missing_slots_are_retrospective_only": True,
        },
    }


def refresh_operational_reliability(
    *,
    manifest_path: Path = MANIFEST,
    ledger_path: Path = HEALTH / "operational_slots.json",
) -> dict[str, Any]:
    manifest = read_json(manifest_path) or {}
    ledger = read_json(ledger_path) or {}
    interval = int((manifest.get("polling") or {}).get("scheduler_interval_minutes") or 60)
    updated = densify_operational_slots(ledger, interval_minutes=interval, window_size=48)
    write_json(ledger_path, updated)
    if manifest:
        manifest["operational_reliability"] = updated["summary"]
        governance = dict(manifest.get("governance") or {})
        governance["scheduler_reliability_uses_expected_slot_denominator"] = True
        governance["missing_slots_are_retrospective_only"] = True
        manifest["governance"] = governance
        write_json(manifest_path, manifest)
    return updated
