"""Missed-slot reconciliation for DEEP/PRICE report occurrences (audit only).

GitHub cron is best-effort: ticks can be delayed or skipped. This module
classifies every *due* occurrence (see ``due_report_occurrences``) from
independently collected evidence. It is deliberately pure:

* it never dispatches, back-fills, publishes or comments;
* it never creates natural-execution proof (every record says so);
* a GitHub workflow conclusion is NOT publication evidence. Only a private
  repository readback that passes ``classify_occurrence`` (exact slot, QA,
  Stage3, receipt, manifest/digest, latest pointer) yields VERIFIED_PUBLISHED;
* evidence-source failures yield UNKNOWN, never MISSING and never VERIFIED.

Occurrence identity is ``MODE|ISO_REPORT_SLOT`` (Asia/Jakarta, +07:00).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from ops.render_external_clock import (
    DOWNSTREAM_WINDOW_MINUTES,
    due_report_occurrences,
)

VERIFIED_PUBLISHED = "VERIFIED_PUBLISHED"
ACTIVE = "ACTIVE"
FAILED = "FAILED"
MISSING = "MISSING"
UNKNOWN = "UNKNOWN"
STATES = (VERIFIED_PUBLISHED, ACTIVE, FAILED, MISSING, UNKNOWN)

PUBLISHED_TERMINALITY = frozenset(
    {"READY_FULL", "READY_DEGRADED", "READY_DEGRADED_PUBLIC_FIRST"}
)
# A slot younger than the downstream acceptance bound may still be legitimately
# dispatched, so absence of evidence is not yet MISSING.
PIPELINE_GRACE = timedelta(minutes=DOWNSTREAM_WINDOW_MINUTES[1])
SCHEMA = "FPL_MISSED_SLOT_AUDIT_V1"


def occurrence_id(report_mode: str, report_slot: str) -> str:
    return f"{report_mode}|{report_slot}"


def _published(result: Mapping[str, Any], mode: str, slot: str) -> tuple[bool, str]:
    """True only for a fully consistent, failure-free terminal verification."""
    terminality = str(result.get("terminality") or "").upper()
    failures = [str(item) for item in result.get("failures") or []]
    if failures:
        return False, "PRIVATE_VERIFICATION_FAILED:" + ",".join(failures)
    if terminality not in PUBLISHED_TERMINALITY:
        return False, f"TERMINALITY_NOT_PUBLISHED:{terminality or 'EMPTY'}"
    if result.get("report_mode") != mode or result.get("report_slot") != slot:
        return False, "VERIFICATION_BOUND_TO_DIFFERENT_OCCURRENCE"
    return True, terminality


def classify_due_occurrences(
    now: datetime,
    *,
    verified: Mapping[str, Mapping[str, Any]],
    active: Iterable[str] = (),
    failed: Iterable[str] = (),
    unknown: Mapping[str, str] | None = None,
    lookback_hours: int = 36,
) -> list[dict[str, Any]]:
    """Classify each due occurrence.

    Precedence: verified publication > active run > failure evidence >
    evidence-source error (UNKNOWN) > inside pipeline grace (UNKNOWN) > MISSING.
    ``unknown`` maps an occurrence id to the reason its evidence could not be
    collected (API failure, truncated tree, ...).
    """
    active_ids = frozenset(active)
    failed_ids = frozenset(failed)
    unknown = dict(unknown or {})
    now_utc = now.astimezone(timezone.utc)
    rows: list[dict[str, Any]] = []
    for due in due_report_occurrences(now, lookback_hours):
        mode, slot = due["report_mode"], due["report_slot"]
        oid = occurrence_id(mode, slot)
        age = now_utc - datetime.fromisoformat(slot).astimezone(timezone.utc)
        state, reason = MISSING, "NO_PUBLICATION_RUN_OR_FAILURE_EVIDENCE"

        result = verified.get(oid)
        verified_failure = ""
        if result is not None:
            ok, detail = _published(result, mode, slot)
            if ok:
                state, reason = VERIFIED_PUBLISHED, detail
            else:
                verified_failure = detail
        if state != VERIFIED_PUBLISHED:
            if oid in active_ids:
                state, reason = ACTIVE, "CONFIRMED_QUEUED_OR_IN_PROGRESS_RUN"
            elif verified_failure:
                state, reason = FAILED, verified_failure
            elif oid in failed_ids:
                state, reason = FAILED, "TERMINAL_FAILED_RUN_WITHOUT_VERIFIED_PUBLICATION"
            elif oid in unknown:
                state, reason = UNKNOWN, "EVIDENCE_UNAVAILABLE:" + unknown[oid]
            elif age < PIPELINE_GRACE:
                state, reason = UNKNOWN, "WITHIN_PIPELINE_WINDOW"
        rows.append(
            {
                "occurrence_id": oid,
                "report_mode": mode,
                "report_slot": slot,
                "checkpoint_time": due["checkpoint_time"],
                "age_minutes": int(age.total_seconds() // 60),
                "state": state,
                "reason": reason,
            }
        )
    return rows


def build_audit_record(
    now: datetime, rows: list[dict[str, Any]], lookback_hours: int
) -> dict[str, Any]:
    counts = Counter(row["state"] for row in rows)
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "lookback_hours": lookback_hours,
        "counts": {state: counts.get(state, 0) for state in STATES},
        "rows": rows,
        # Audit evidence is not execution evidence.
        "natural_execution_created": False,
        "natural_acceptance_eligible": False,
        "historical_dispatch": False,
        "backfill": False,
        "recovery_dispatch": "NOT_IMPLEMENTED_OWNER_AUTHORIZATION_REQUIRED",
        "all_due_verified": bool(rows)
        and all(row["state"] == VERIFIED_PUBLISHED for row in rows),
    }
