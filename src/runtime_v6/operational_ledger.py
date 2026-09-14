from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .report_contract import core_slot_key
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
                    "core_slot_key": core_slot_key("chatgpt_scheduler", key),
                    "fulfilled_by": "MISSING",
                    "fulfilled": False,
                    "chatgpt_scheduler_fulfillment": False,
                    "run_id": None,
                    "observed_at": None,
                    "schedule_kind": "chatgpt_scheduler",
                    "schedule_lag_seconds": None,
                    "publication_generation_id": None,
                    "missing_reason": "NO_CHATGPT_MASTER_SCHEDULER_PROOF_BEFORE_LATER_SLOT",
                    "missing_classification_is_retrospective": True,
                }
            cursor += step
    return [existing[key] for key in sorted(existing)][-max(1, int(window_size)):]


def _latest_chatgpt_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        row
        for row in rows
        if row.get("fulfilled_by") == "CHATGPT" and row.get("fulfilled") is True
    ]
    return max(eligible, key=lambda row: str(row.get("slot") or ""), default={})


def _latest_observed_at(rows: list[dict[str, Any]]) -> str | None:
    values = [str(row.get("observed_at")) for row in rows if row.get("observed_at")]
    if not values:
        return None
    return max(values, key=lambda value: _parse_dt(value) or datetime.min.replace(tzinfo=timezone.utc))


def _control_plane_state(
    active_rows: list[dict[str, Any]],
    auxiliary_rows: list[dict[str, Any]],
    *,
    interval_minutes: int,
    observed_at: str | None,
) -> dict[str, Any]:
    latest = _latest_chatgpt_row(active_rows)
    logical_slot = latest.get("slot")
    authoritative_cycle_at = latest.get("observed_at")
    operational_cycle_at = _latest_observed_at(active_rows + auxiliary_rows)
    next_expected = None
    if logical_slot and _parse_dt(str(logical_slot)) is not None:
        next_expected = (
            _parse_dt(str(logical_slot)) + timedelta(minutes=max(1, int(interval_minutes)))
        ).isoformat()

    telemetry = scheduler_proof_telemetry(
        str(authoritative_cycle_at) if authoritative_cycle_at else None,
        now=observed_at,
    )
    return {
        "logical_slot": logical_slot,
        "last_processed_logical_slot": logical_slot,
        "next_expected_logical_slot": next_expected,
        "last_chatgpt_scheduler_cycle_at": authoritative_cycle_at,
        "last_authoritative_cycle_at": authoritative_cycle_at,
        "last_operational_cycle_at": operational_cycle_at,
        **telemetry,
        "run_provenance": {
            "run_id": latest.get("run_id"),
            "schedule_kind": latest.get("schedule_kind"),
            "core_slot_key": latest.get("core_slot_key"),
            "publication_generation_id": latest.get("publication_generation_id"),
            "source_commit": latest.get("source_commit"),
            "runtime_branch": latest.get("runtime_branch"),
        },
        "governance": {
            "scheduler_proof_authority": "FPL_MASTER_SLOT",
            "report_prefetch_advances_scheduler_proof": False,
            "payload_freshness_advances_scheduler_proof": False,
            "core_slot_first_owner_wins": True,
        },
    }


def build_operational_slots(
    previous_ledger: dict[str, Any] | None,
    control: dict[str, Any],
    *,
    window_size: int = 48,
) -> dict[str, Any]:
    """Build factual ChatGPT scheduler epoch plus immutable legacy evidence.

    Wave 2 makes core-slot ownership first-writer-wins. A duplicate trigger for an
    already fulfilled logical slot is recorded as duplicate evidence and MUST NOT
    replace the original run/publication provenance or advance scheduler proof.
    """
    limit = max(1, int(window_size))
    previous = dict(previous_ledger or {})
    previous_schema = int(previous.get("schema_version") or 0)

    if previous_schema >= 3:
        legacy_rows = [dict(row) for row in previous.get("legacy_slots") or [] if isinstance(row, dict)]
        active_rows = [dict(row) for row in previous.get("slots") or [] if isinstance(row, dict)]
        auxiliary_rows = [dict(row) for row in previous.get("auxiliary_operational_slots") or [] if isinstance(row, dict)]
        epoch = dict(previous.get("epoch") or {})
        duplicate_core_attempts = [
            dict(row) for row in previous.get("duplicate_core_attempts") or [] if isinstance(row, dict)
        ]
    else:
        legacy_rows = [dict(row) for row in previous.get("slots") or [] if isinstance(row, dict)]
        active_rows = []
        auxiliary_rows = []
        epoch = {}
        duplicate_core_attempts = []

    if control.get("counts_as_completed_operational_slot") is True and control.get("expected_cycle_at"):
        slot = str(control["expected_cycle_at"])
        if control.get("chatgpt_scheduler") is True:
            existing = next((row for row in active_rows if str(row.get("slot")) == slot), None)
            if existing is None:
                schedule_kind = str(control.get("schedule_kind") or "chatgpt_scheduler")
                active_rows.append(
                    {
                        "slot": slot,
                        "core_slot_key": core_slot_key(schedule_kind, slot),
                        "fulfilled_by": "CHATGPT",
                        "fulfilled": True,
                        "chatgpt_scheduler_fulfillment": True,
                        "run_id": control.get("run_id"),
                        "observed_at": control.get("cycle_observed_at"),
                        "schedule_kind": schedule_kind,
                        "schedule_lag_seconds": control.get("schedule_lag_seconds"),
                        "publication_generation_id": control.get("publication_generation_id")
                        or control.get("candidate_generation_id"),
                        "source_commit": control.get("source_commit"),
                        "runtime_branch": control.get("runtime_branch") or "runtime-data-v6",
                        "data_slot_already_fulfilled_before_scheduler_proof": control.get(
                            "data_slot_already_fulfilled_before_scheduler_proof",
                            False,
                        ),
                        "duplicate_trigger_count": 0,
                    }
                )
            else:
                existing["duplicate_trigger_count"] = int(existing.get("duplicate_trigger_count") or 0) + 1
                duplicate_core_attempts.append(
                    {
                        "slot": slot,
                        "core_slot_key": existing.get("core_slot_key")
                        or core_slot_key(str(existing.get("schedule_kind") or "chatgpt_scheduler"), slot),
                        "authoritative_run_id": existing.get("run_id"),
                        "duplicate_run_id": control.get("run_id"),
                        "duplicate_observed_at": control.get("cycle_observed_at"),
                        "duplicate_publication_generation_id": control.get("publication_generation_id")
                        or control.get("candidate_generation_id"),
                        "reason": "CORE_SLOT_ALREADY_OWNED_FIRST_OWNER_PRESERVED",
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
    duplicate_core_attempts = sorted(
        duplicate_core_attempts,
        key=lambda row: str(row.get("duplicate_observed_at") or ""),
    )[-limit:]

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

    control_plane = _control_plane_state(
        active_rows,
        auxiliary_rows,
        interval_minutes=interval,
        observed_at=control.get("cycle_observed_at"),
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
        "duplicate_core_attempts": duplicate_core_attempts,
        "legacy_slots": legacy_rows,
        "legacy_summary": _legacy_summary(legacy_rows),
        "control_plane": control_plane,
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
            "last_chatgpt_scheduler_cycle_at": control_plane.get("last_chatgpt_scheduler_cycle_at"),
            "last_authoritative_cycle_at": control_plane.get("last_authoritative_cycle_at"),
            "last_operational_cycle_at": control_plane.get("last_operational_cycle_at"),
            "last_processed_logical_slot": control_plane.get("last_processed_logical_slot"),
            "next_expected_logical_slot": control_plane.get("next_expected_logical_slot"),
            "last_chatgpt_scheduler_proof_at": control_plane.get("last_chatgpt_scheduler_proof_at"),
            "scheduler_proof_age_seconds": control_plane.get("scheduler_proof_age_seconds"),
            "scheduler_proof_freshness": control_plane.get("scheduler_proof_freshness"),
            "scheduler_proof_health": control_plane.get("scheduler_proof_health"),
            "proof_fresh_after_minutes": SCHEDULE_POLICY.proof_fresh_after_minutes,
            "proof_stale_after_minutes": SCHEDULE_POLICY.proof_stale_after_minutes,
            "auxiliary_master_slots": len(auxiliary_rows),
            "duplicate_core_attempts": len(duplicate_core_attempts),
            "latest_run_provenance": control_plane.get("run_provenance"),
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
            "report_prefetch_is_not_scheduler_health_proof": True,
            "github_scheduler_is_not_current_health_authority": True,
            "legacy_scheduler_evidence_preserved": True,
            "missing_slots_are_retrospective_only": True,
            "scheduler_policy_source": "config/v6/schedule_policy.json",
            "scheduler_proof_age_does_not_fabricate_slots": True,
            "core_slot_first_owner_wins": True,
            "duplicate_core_trigger_does_not_replace_provenance": True,
        },
    }
