from __future__ import annotations

"""Canonical terminality semantics for occurrence-bound report verification.

This module is deliberately downstream of the report publisher. It classifies
already-collected, allowlisted evidence and never creates facts, model output,
or delivery evidence.
"""

from typing import Any, Mapping


READY_FULL = "READY_FULL"
READY_DEGRADED = "READY_DEGRADED"
FAILED_VERIFY = "FAILED_VERIFY"

_ALLOWED_RUNNER_STATES = {"PASS", "PARTIAL"}
_ALLOWED_DEGRADED_REASONS = {
    "ANALYTICS_INCOMPLETE",
    "BLOCKED_UPSTREAM",
    "PREFETCH_NOT_TERMINAL",
}


def _status(value: Any) -> str:
    return str(value or "").strip().upper()


def _add(failures: list[str], name: str) -> None:
    if name not in failures:
        failures.append(name)


def classify_occurrence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one fully collected occurrence as full, degraded, or failed.

    Every safety boundary is fail-closed. In particular, PARTIAL is accepted
    only when the publisher explicitly emitted READY_DEGRADED and the
    degradation is attributable to a known governed report-first condition.
    """

    failures: list[str] = []
    mode = _status(evidence.get("report_mode"))
    requested_slot = str(evidence.get("report_slot") or "")
    occurrence_id = str(evidence.get("occurrence_id") or "")
    serving = evidence.get("serving")
    delivery = evidence.get("delivery")
    historical = evidence.get("historical")
    latest = evidence.get("latest")
    stage3 = evidence.get("stage3")
    degradation = evidence.get("degradation")

    if not isinstance(serving, Mapping):
        serving = {}
        _add(failures, "SERVING_EVIDENCE_MISSING")
    if not isinstance(delivery, Mapping):
        delivery = {}
        _add(failures, "DELIVERY_EVIDENCE_MISSING")
    if not isinstance(historical, Mapping):
        historical = {}
        _add(failures, "HISTORICAL_EVIDENCE_MISSING")
    if not isinstance(latest, Mapping):
        latest = {}
        _add(failures, "LATEST_EVIDENCE_MISSING")
    if not isinstance(stage3, Mapping):
        stage3 = {}
        _add(failures, "STAGE3_EVIDENCE_MISSING")
    if not isinstance(degradation, Mapping):
        degradation = {}

    if mode not in {"DEEP", "PRICE"}:
        _add(failures, "REPORT_MODE_INVALID")
    if not requested_slot or serving.get("report_slot") != requested_slot:
        _add(failures, "EXACT_SLOT_MISMATCH")
    if serving.get("report_mode") != mode:
        _add(failures, "REPORT_MODE_MISMATCH")
    if occurrence_id != (f"{mode}|{requested_slot}" if mode and requested_slot else ""):
        _add(failures, "OCCURRENCE_ID_MISMATCH")

    runner_status = _status(serving.get("runner_status"))
    if runner_status not in _ALLOWED_RUNNER_STATES:
        _add(failures, "RUNNER_STATUS_INVALID")

    for key, failure in (
        ("pre_render_status", "PRE_RENDER_QA_NOT_PASS"),
        ("post_render_status", "POST_RENDER_QA_NOT_PASS"),
        ("human_facing_status", "HUMAN_FACING_QA_NOT_PASS"),
    ):
        if _status(serving.get(key)) != "PASS":
            _add(failures, failure)

    if _status(evidence.get("private_delivery_status")) != "PASS":
        _add(failures, "PRIVATE_DELIVERY_NOT_PASS")
    if evidence.get("exact_publication") is not True:
        _add(failures, "EXACT_PUBLICATION_NOT_PROVEN")
    if historical.get("exists") is not True:
        _add(failures, "HISTORICAL_PUBLICATION_MISSING")
    if not str(historical.get("path") or "").strip():
        _add(failures, "HISTORICAL_PATH_MISSING")
    if int(historical.get("body_size") or 0) <= 0:
        _add(failures, "HISTORICAL_BODY_EMPTY")

    body_sha = str(historical.get("body_sha256") or "")
    expected_sha = str(serving.get("canonical_body_sha256") or "")
    for value in (
        body_sha,
        str(historical.get("receipt_body_sha256") or ""),
        str(historical.get("digest_body_sha256") or ""),
        str(latest.get("body_sha256") or ""),
    ):
        if len(value) != 64 or value != expected_sha:
            _add(failures, "BODY_DIGEST_MISMATCH")
    if len(expected_sha) != 64:
        _add(failures, "BODY_DIGEST_MISSING")

    if latest.get("exists") is not True or latest.get("advanced") is not True:
        _add(failures, "LATEST_ADVANCEMENT_INVALID")

    if evidence.get("personal_authority_violation") is True:
        _add(failures, "PERSONAL_AUTHORITY_VIOLATION")
    if evidence.get("privacy_violation") is True:
        _add(failures, "PRIVACY_BOUNDARY_VIOLATION")
    if evidence.get("fabricated_evidence") is True:
        _add(failures, "FABRICATED_EVIDENCE")
    if evidence.get("mandatory_math_failure") is True:
        _add(failures, "MANDATORY_FOOTBALL_MATH_FAILURE")

    delivery_status = _status(delivery.get("delivery_status"))
    root_failure = str(delivery.get("root_failure") or "").strip().upper()
    stage3_status = _status(stage3.get("validation"))
    engineering_blocks = stage3.get("engineering_closure_blocks_report") is True
    engineering_status = "DEGRADED" if stage3_status == "DEGRADED" else stage3_status or "UNKNOWN"

    if delivery_status not in {READY_FULL, READY_DEGRADED}:
        _add(failures, "DELIVERY_TERMINALITY_INVALID")

    if delivery_status == READY_FULL:
        if runner_status != "PASS":
            _add(failures, "READY_FULL_WITHOUT_RUNNER_PASS")
        if stage3_status not in {"PASS", "NOT_APPLICABLE"}:
            _add(failures, "READY_FULL_WITHOUT_STAGE3_PASS")
    elif delivery_status == READY_DEGRADED:
        if runner_status != "PARTIAL":
            _add(failures, "READY_DEGRADED_WITHOUT_PARTIAL_RUNNER")
        if not root_failure or root_failure not in _ALLOWED_DEGRADED_REASONS:
            _add(failures, "DEGRADED_REASON_NOT_GOVERNED")
        if degradation.get("governed") is not True or degradation.get("attributable") is not True:
            _add(failures, "UNGOVERNED_DEGRADATION")
        if str(degradation.get("reason") or "").strip().upper() != root_failure:
            _add(failures, "DEGRADATION_REASON_NOT_BOUND")
        if stage3_status == "DEGRADED" and engineering_blocks:
            _add(failures, "STAGE3_DEGRADATION_BLOCKS_REPORT")
        if stage3_status not in {"DEGRADED", "NOT_APPLICABLE"}:
            _add(failures, "READY_DEGRADED_WITHOUT_GOVERNED_STAGE3_STATE")

    terminality = READY_FULL if delivery_status == READY_FULL else READY_DEGRADED
    if failures:
        terminality = FAILED_VERIFY

    return {
        "terminality": terminality,
        "failures": failures,
        "report_mode": mode,
        "report_slot": requested_slot,
        "engineering_status": engineering_status,
    }
