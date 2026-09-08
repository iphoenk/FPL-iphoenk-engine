from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .runtime_control import CHATGPT_GREEN_STREAK, CHATGPT_SCHEDULER_AUTHORITY, CHATGPT_SCHEDULER_EPOCH
from .store import HEALTH, MANIFEST, read_json, write_json


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _densify(rows: list[dict[str, Any]], interval_minutes: int, window_size: int) -> list[dict[str, Any]]:
    existing = {
        str(row.get("slot")): dict(row)
        for row in rows
        if isinstance(row, dict) and _parse(row.get("slot")) is not None
    }
    ordered = sorted((_parse(slot), slot) for slot in existing)
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


def densify_operational_slots(
    ledger: dict[str, Any] | None,
    *,
    interval_minutes: int = 60,
    window_size: int = 48,
) -> dict[str, Any]:
    """Recompute current ChatGPT-scheduler reliability without rewriting legacy evidence."""
    source = dict(ledger or {})
    previous_schema = int(source.get("schema_version") or 0)
    if previous_schema >= 3:
        legacy_rows = [dict(row) for row in source.get("legacy_slots") or [] if isinstance(row, dict)]
        rows = [dict(row) for row in source.get("slots") or [] if isinstance(row, dict)]
        auxiliary = [dict(row) for row in source.get("auxiliary_operational_slots") or [] if isinstance(row, dict)]
        epoch = dict(source.get("epoch") or {})
    else:
        legacy_rows = [dict(row) for row in source.get("slots") or [] if isinstance(row, dict)]
        rows = []
        auxiliary = []
        epoch = {}

    rows = _densify(rows, interval_minutes, window_size)
    tracked = len(rows)
    fulfilled = sum(row.get("fulfilled_by") == "CHATGPT" and row.get("fulfilled") is True for row in rows)
    missing = sum(row.get("fulfilled_by") == "MISSING" for row in rows)
    ratio = round(fulfilled / tracked, 4) if tracked else None
    consecutive = 0
    for row in reversed(rows):
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

    epoch.setdefault("id", CHATGPT_SCHEDULER_EPOCH)
    epoch.setdefault("authority", CHATGPT_SCHEDULER_AUTHORITY)
    epoch.setdefault("start_at", rows[0]["slot"] if rows else None)
    epoch.setdefault("green_after_consecutive_slots", CHATGPT_GREEN_STREAK)

    return {
        **source,
        "schema_version": 3,
        "window_size": max(1, int(window_size)),
        "epoch": epoch,
        "slots": rows,
        "auxiliary_operational_slots": auxiliary[-max(1, int(window_size)):],
        "legacy_slots": legacy_rows[-max(1, int(window_size)):],
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
            "auxiliary_master_slots": len(auxiliary),
            "reliability_basis": "CHATGPT_MASTER_LOGICAL_HOURLY_SLOTS",
            "legacy_github_scheduler_excluded_from_current_health": True,
            "data_availability_health_is_separate": True,
        },
        "governance": {
            **dict(source.get("governance") or {}),
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
        governance["scheduler_authority"] = CHATGPT_SCHEDULER_AUTHORITY
        governance["scheduler_epoch"] = CHATGPT_SCHEDULER_EPOCH
        governance["legacy_github_scheduler_evidence_is_historical_only"] = True
        governance["missing_slots_are_retrospective_only"] = True
        manifest["governance"] = governance
        write_json(manifest_path, manifest)
    return updated
