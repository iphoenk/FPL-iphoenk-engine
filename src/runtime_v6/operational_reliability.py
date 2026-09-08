from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_control import (
    CHATGPT_SCHEDULER_AUTHORITY,
    CHATGPT_SCHEDULER_EPOCH,
    build_operational_slots,
)
from .store import HEALTH, MANIFEST, read_json, write_json


def densify_operational_slots(
    ledger: dict[str, Any] | None,
    *,
    interval_minutes: int = 60,
    window_size: int = 48,
) -> dict[str, Any]:
    """Re-evaluate reliability through the single canonical V6 slot evaluator.

    This function intentionally delegates to runtime_control.build_operational_slots
    with a non-fulfilling control event. It therefore recomputes missing-slot and
    health telemetry without adding a synthetic scheduler success.
    """
    source = dict(ledger or {})
    control = {
        "cycle_observed_at": source.get("generated_at"),
        "scheduler_interval_minutes": max(1, int(interval_minutes)),
        "counts_as_completed_operational_slot": False,
        "expected_cycle_at": None,
    }
    return build_operational_slots(source, control, window_size=window_size)


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
        governance["scheduler_reliability_evaluator"] = "runtime_control.build_operational_slots"
        manifest["governance"] = governance
        write_json(manifest_path, manifest)
    return updated
