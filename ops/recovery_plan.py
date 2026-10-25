"""Future-only recovery PLAN (advisory). It cannot dispatch anything.

Owner decision: reconciliation logic may be implemented, automatic dispatch may
not be enabled without separate authorization. This module therefore only
DECIDES, per audited occurrence, whether a governed recovery would be eligible
and records an idempotency key; there is no dispatch code path anywhere in it.

Policy (all conditions must hold):
  * state is MISSING and the clock diagnosis is a platform gap
    (CLOCK_NO_TICK_IN_RESOLVER_WINDOW); a tick inside the window with no
    dispatch is a defect to investigate, never retried blindly.
  * the occurrence is still current: overdue beyond the resolver window but
    within MAX_OVERDUE_MINUTES, and the next slot of the same mode is not yet due.
  * no VERIFIED/ACTIVE/FAILED/UNKNOWN evidence for the same occurrence or any
    FAILED row for the same mode in the audit window (no retry loops).
  * at most one candidate per mode (bounded), the newest only.
Everything older is HISTORICAL and is never eligible (no backfill).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ops.clock_cadence import NO_TICK_IN_WINDOW
from ops.render_external_clock import RESOLVER_WINDOW_MINUTES, due_report_occurrences

DISPATCH_ENABLED = False  # requires separate owner authorization; no code path uses it
MAX_OVERDUE_MINUTES = 180
SCHEMA = "FPL_RECOVERY_PLAN_V1"

ELIGIBLE = "ELIGIBLE_IF_AUTHORIZED"
HISTORICAL = "INELIGIBLE_HISTORICAL"
SUPERSEDED = "INELIGIBLE_SUPERSEDED_BY_NEXT_SLOT"
DEFECT = "INELIGIBLE_CLOCK_DEFECT_INVESTIGATE"
NOT_MISSING = "INELIGIBLE_NOT_MISSING"
RETRY_LOOP = "INELIGIBLE_MODE_HAS_FAILED_RUN"
NOT_NEWEST = "INELIGIBLE_NOT_NEWEST_FOR_MODE"
NO_DIAGNOSIS = "INELIGIBLE_NO_CLOCK_EVIDENCE"
WITHIN_WINDOW = "INELIGIBLE_STILL_WITHIN_RESOLVER_WINDOW"


def idempotency_key(occurrence_id: str) -> str:
    return f"RECOVERY|{occurrence_id}"


def _next_slot_started(row: Mapping[str, Any], now: datetime) -> bool:
    slot = datetime.fromisoformat(str(row["report_slot"]))
    return any(
        o["report_mode"] == row["report_mode"] and datetime.fromisoformat(o["report_slot"]) > slot
        for o in due_report_occurrences(now, lookback_hours=72)
    )


def plan(now: datetime, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    failed_modes = {r["report_mode"] for r in rows if r.get("state") == "FAILED"}
    decisions: list[dict[str, Any]] = []
    candidates: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: str(r["report_slot"]), reverse=True):
        slot = datetime.fromisoformat(str(row["report_slot"]))
        overdue = (now - slot).total_seconds() / 60
        decision, reason = None, ""
        if row.get("state") != "MISSING":
            decision = NOT_MISSING
        elif row.get("diagnosis") != NO_TICK_IN_WINDOW:
            decision = NO_DIAGNOSIS if not row.get("diagnosis") else DEFECT
        elif overdue > MAX_OVERDUE_MINUTES:
            decision = HISTORICAL
        elif overdue <= RESOLVER_WINDOW_MINUTES[1]:
            decision = WITHIN_WINDOW
        elif _next_slot_started(row, now):
            decision = SUPERSEDED
        elif row["report_mode"] in failed_modes:
            decision = RETRY_LOOP
        elif row["report_mode"] in candidates:
            decision = NOT_NEWEST
        else:
            decision = ELIGIBLE
        out = {
            "occurrence_id": row["occurrence_id"],
            "report_mode": row["report_mode"],
            "report_slot": row["report_slot"],
            "overdue_minutes": round(overdue, 1),
            "decision": decision,
        }
        if decision == ELIGIBLE:
            out["idempotency_key"] = idempotency_key(row["occurrence_id"])
            out["label"] = "RECOVERY"
            out["natural_acceptance_eligible"] = False
            candidates[row["report_mode"]] = out
        decisions.append(out)
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "dispatch_enabled": DISPATCH_ENABLED,
        "dispatch": "NOT_PERFORMED_AUTHORIZATION_REQUIRED",
        "max_overdue_minutes": MAX_OVERDUE_MINUTES,
        "eligible": sorted(candidates.values(), key=lambda d: d["occurrence_id"]),
        "decisions": decisions,
    }
