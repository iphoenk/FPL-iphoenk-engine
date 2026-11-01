"""O2 decision safety gate (Phase E, Kresna mandate 2026-11-01).

Pure, read-only evaluation.  A Captain ``LOCK`` or an executable XI requires
(a) OUR15 identity proven current for the planning GW and (b) no critical
evidence in a failed or unknown state.  Non-critical supplementary evidence
never lowers a decision.

The gate never invents a status: it only maps ``LOCK`` to the already
published ``PREPARE`` (non-executable) and, when OUR15 is entirely
unavailable, ``WAIT``.  It does not touch the source gate, Stage3 acceptance
or any historical artifact.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

CONTRACT = "V12_DECISION_SAFETY_GATE_V1"

# Resolution statuses that prove OUR15 for the planning GW.  PUBLIC_INFERRED
# (O1 public reconstruction) is deliberately NOT executable-grade: it is not
# authenticated-current and has no finance authority.  Owner may relax later.
EXECUTABLE_RESOLUTION_STATUSES = frozenset({"CURRENT_VALID"})
UNAVAILABLE_RESOLUTION_STATUSES = frozenset({"", "UNAVAILABLE", "NONE", "UNKNOWN"})
# Maximum age (minutes before the cutoff) at which an authenticated snapshot is
# accepted as executable without public-transfer verification.
UNCHECKED_SNAPSHOT_MAX_AGE_MINUTES = 15.0
CRITICAL_EVIDENCE_OK = frozenset({"PASS", "COMPLETE", "AVAILABLE", "GREEN", "OK"})


def evaluate_decision_safety_gate(
    personal_resolution: Mapping[str, Any] | None,
    *,
    critical_evidence: Mapping[str, Any] | None = None,
    our15_consistency_failures: Iterable[str] = (),
) -> dict[str, Any]:
    """Return a traceable gate verdict.

    ``critical_evidence`` maps an evidence id to its status; only ids the
    caller deems critical belong here.  ``our15_consistency_failures`` are
    caller-detected inconsistencies (the runner passes OUR15 not being 15 unique
    elements; captain/vice legality is enforced separately by the surface).
    """
    resolution = dict(personal_resolution or {})
    status = str(resolution.get("resolution_status") or resolution.get("status") or "").upper()
    reasons: list[dict[str, Any]] = []

    if status in UNAVAILABLE_RESOLUTION_STATUSES:
        reasons.append({"code": "OUR15_UNAVAILABLE", "detail": f"resolution_status={status or 'MISSING'}"})
    elif status not in EXECUTABLE_RESOLUTION_STATUSES:
        reasons.append({
            "code": "OUR15_NOT_CURRENT_VALID",
            "detail": (
                f"resolution_status={status}; source={resolution.get('source')}; "
                f"observed_at={resolution.get('observed_at')}; applicable_gw={resolution.get('gw')}"
            ),
        })
    elif resolution.get("stale") is True:
        reasons.append({"code": "OUR15_STALE", "detail": "resolution flagged stale"})

    # O1 follow-through: an authenticated snapshot older than the cutoff whose
    # completeness against public transfers was not verified cannot support an
    # executable decision (a sale/purchase between snapshot and cutoff would be
    # invisible).  Legacy resolutions without a cutoff carry no such field.
    gap = str(resolution.get("transfer_gap_check") or "").upper()
    if status in EXECUTABLE_RESOLUTION_STATUSES and gap in {
        "NOT_PERFORMED_NO_TRANSFER_EVIDENCE",
        "FAILED_TRANSFER_AFTER_SNAPSHOT",
    }:
        age = resolution.get("snapshot_age_minutes")
        if gap != "NOT_PERFORMED_NO_TRANSFER_EVIDENCE" or not isinstance(age, (int, float)) or age > UNCHECKED_SNAPSHOT_MAX_AGE_MINUTES:
            reasons.append({
                "code": "OUR15_TRANSFER_GAP_UNCHECKED",
                "detail": f"transfer_gap_check={gap}; snapshot_age_minutes={age}",
            })

    for failure in our15_consistency_failures:
        reasons.append({"code": "OUR15_INCONSISTENT", "detail": str(failure)})

    for evidence_id, raw in sorted((critical_evidence or {}).items()):
        state = str(raw or "UNKNOWN").upper()
        if state not in CRITICAL_EVIDENCE_OK:
            reasons.append({"code": "CRITICAL_EVIDENCE_DEGRADED", "detail": f"{evidence_id}={state}"})

    unavailable = any(r["code"] == "OUR15_UNAVAILABLE" for r in reasons)
    return {
        "contract": CONTRACT,
        "executable": not reasons,
        "max_state": "LOCK" if not reasons else ("WAIT" if unavailable else "PREPARE"),
        "reasons": reasons,
        "reason_codes": [r["code"] for r in reasons],
        "resolution_status": status or "MISSING",
    }


def clamp_state(state: Any, gate: Mapping[str, Any] | None, *, default: str = "WAIT") -> str:
    """Clamp a WAIT/PREPARE/LOCK state to what the gate allows."""
    value = str(state or default).upper()
    if gate is None:
        return value
    order = {"WAIT": 0, "PREPARE": 1, "LOCK": 2}
    ceiling = str(gate.get("max_state") or "LOCK").upper()
    if value not in order or ceiling not in order:
        return value
    return value if order[value] <= order[ceiling] else ceiling


def gate_summary(gate: Mapping[str, Any] | None) -> str:
    if not gate or gate.get("executable") is not False:
        return ""
    return "; ".join(f"{r['code']}: {r['detail']}" for r in gate.get("reasons") or [])
