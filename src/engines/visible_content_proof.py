from __future__ import annotations

"""Transient evidence builder for V12 visible-content conformance.

This module does not validate report content, acquire data, persist state, or become
methodology authority. It only packages occurrence-bound evidence about how the
Canonical visible-content contract was applied by the actual runtime.
"""

from datetime import datetime
from hashlib import sha256
from typing import Any, Mapping, Sequence


CANONICAL_AUTHORITY = "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
RUNTIME_NAME = "FPL Master Monitor V12 ChatGPT Automation"
SECTION_STATES = frozenset({"COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE"})
DEGRADED_STATES = frozenset({"PARTIAL", "DEGRADED", "UNAVAILABLE"})
SEARCH_AUTHORITIES = frozenset({"FULL", "PARTIAL"})
PYTHON_QA_MODULE = "src/runtime_v6/domains/report_plane/report_qa.py"


class VisibleContentProofError(ValueError):
    pass


def canonical_content_fingerprint(canonical_text: str) -> str:
    if not isinstance(canonical_text, str) or not canonical_text.strip():
        raise VisibleContentProofError("canonical text is required")
    return sha256(canonical_text.encode("utf-8")).hexdigest()


def _nonempty(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise VisibleContentProofError(f"{label} is required")
    return text


def _sha256(value: Any, *, label: str) -> str:
    text = _nonempty(value, label=label)
    if len(text) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        raise VisibleContentProofError(f"{label} must be a SHA-256 fingerprint")
    return text.lower()


def _normalise_section_state(row: Mapping[str, Any]) -> dict[str, Any]:
    section_id = _nonempty(row.get("section_id"), label="section_id")
    state = str(row.get("state") or "").strip().upper()
    if state not in SECTION_STATES:
        raise VisibleContentProofError(
            f"invalid section state for {section_id}: {state or '<empty>'}"
        )

    available = row.get("available_count")
    expected = row.get("expected_count")
    if available is not None:
        try:
            available = int(available)
        except (TypeError, ValueError) as exc:
            raise VisibleContentProofError(
                f"available_count must be integer for {section_id}"
            ) from exc
        if available < 0:
            raise VisibleContentProofError(
                f"available_count must be non-negative for {section_id}"
            )
    if expected is not None:
        try:
            expected = int(expected)
        except (TypeError, ValueError) as exc:
            raise VisibleContentProofError(
                f"expected_count must be integer for {section_id}"
            ) from exc
        if expected < 0:
            raise VisibleContentProofError(
                f"expected_count must be non-negative for {section_id}"
            )
    if available is not None and expected is not None and available > expected:
        raise VisibleContentProofError(
            f"available_count cannot exceed expected_count for {section_id}"
        )

    reason = str(row.get("degradation_reason") or "").strip()
    missing_scope = list(row.get("missing_scope") or [])
    if state in DEGRADED_STATES and not reason:
        raise VisibleContentProofError(
            f"degradation_reason is required for {section_id} state={state}"
        )

    return {
        "section_id": section_id,
        "state": state,
        "available_count": available,
        "expected_count": expected,
        "degradation_reason": reason or None,
        "missing_scope": missing_scope,
        "provenance": row.get("provenance"),
        "freshness": row.get("freshness"),
    }


def _python_runtime_provenance(
    *,
    repository_python_qa_executed: bool,
    python_execution_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    executed = bool(repository_python_qa_executed)
    evidence = dict(python_execution_evidence or {})

    if not executed:
        if evidence:
            raise VisibleContentProofError(
                "python_execution_evidence is forbidden when repository Python QA execution is not proven"
            )
        return {
            "runtime": RUNTIME_NAME,
            "repository_python_qa_executed": False,
            "python_qa_status": "NOT_PROVEN",
            "python_execution_evidence": None,
        }

    required = (
        "report_slot",
        "qa_module_path",
        "executed_at",
        "pre_render_status",
        "post_render_status",
        "evidence_fingerprint",
    )
    missing = [field for field in required if not evidence.get(field)]
    if missing:
        raise VisibleContentProofError(
            "repository Python QA execution requires exact evidence: "
            + ",".join(missing)
        )
    if str(evidence.get("qa_module_path")) != PYTHON_QA_MODULE:
        raise VisibleContentProofError("python QA execution evidence must bind to existing report_qa.py")
    _sha256(evidence.get("evidence_fingerprint"), label="evidence_fingerprint")
    return {
        "runtime": RUNTIME_NAME,
        "repository_python_qa_executed": True,
        "python_qa_status": "EXECUTED",
        "python_execution_evidence": evidence,
    }


def build_visible_content_proof(
    *,
    canonical_authority_path: str,
    canonical_content_fingerprint_sha256: str,
    canonical_version: str,
    report_slot: str,
    report_mode: str,
    report_due: bool,
    observed_at: str,
    section_states: Sequence[Mapping[str, Any]],
    hard_failures: Sequence[str] = (),
    section_degradations: Sequence[Mapping[str, Any]] = (),
    warnings: Sequence[str] = (),
    report_can_continue: bool,
    search_authority: str | None = None,
    repository_python_qa_executed: bool = False,
    python_execution_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one transient VISIBLE_CONTENT_PROOF for a due report occurrence."""
    if canonical_authority_path != CANONICAL_AUTHORITY:
        raise VisibleContentProofError("VISIBLE_CONTENT_PROOF must bind Canonical V12")
    fingerprint = _sha256(
        canonical_content_fingerprint_sha256,
        label="canonical_content_fingerprint_sha256",
    )
    version = _nonempty(canonical_version, label="canonical_version")
    slot = _nonempty(report_slot, label="report_slot")
    mode = _nonempty(report_mode, label="report_mode").upper()
    observed = _nonempty(observed_at, label="observed_at")
    try:
        datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VisibleContentProofError("observed_at must be ISO-8601") from exc

    normalised_sections = [_normalise_section_state(row) for row in section_states]
    ids = [row["section_id"] for row in normalised_sections]
    if len(ids) != len(set(ids)):
        raise VisibleContentProofError("section_states must contain unique section_id values")

    failures = [str(value) for value in hard_failures if str(value).strip()]
    degradations = [dict(row) for row in section_degradations if isinstance(row, Mapping)]
    degradation_ids = {
        str(row.get("section") or row.get("section_id") or "").strip()
        for row in degradations
        if str(row.get("section") or row.get("section_id") or "").strip()
    }
    state_by_id = {row["section_id"]: row["state"] for row in normalised_sections}
    declared_degraded_ids = {
        section_id for section_id, state in state_by_id.items() if state in DEGRADED_STATES
    }
    if degradation_ids != declared_degraded_ids:
        raise VisibleContentProofError(
            "section_degradations must match degraded section_states exactly"
        )

    due = bool(report_due)
    can_continue = bool(report_can_continue)
    if due and can_continue != (not failures):
        raise VisibleContentProofError(
            "for REPORT_DUE, report_can_continue must be true iff there are no hard failures"
        )

    search = None
    if search_authority is not None:
        search = str(search_authority).strip().upper()
        if search not in SEARCH_AUTHORITIES:
            raise VisibleContentProofError("search_authority must be FULL/PARTIAL when present")

    runtime = _python_runtime_provenance(
        repository_python_qa_executed=repository_python_qa_executed,
        python_execution_evidence=python_execution_evidence,
    )
    if runtime["repository_python_qa_executed"]:
        evidence_slot = str(
            (runtime.get("python_execution_evidence") or {}).get("report_slot") or ""
        ).strip()
        if evidence_slot != slot:
            raise VisibleContentProofError(
                "python execution evidence must bind to the same report_slot"
            )

    severity = "FAIL" if failures else "DEGRADED" if degradations else "PASS"
    return {
        "proof_kind": "TRANSIENT_VISIBLE_CONTENT_PROOF",
        "authoritative": False,
        "durable_state": False,
        "persistence_forbidden": True,
        "canonical_authority": {
            "path": CANONICAL_AUTHORITY,
            "content_sha256": fingerprint,
            "version": version,
        },
        "report_slot": slot,
        "report_mode": mode,
        "report_due": due,
        "observed_at": observed,
        "section_states": normalised_sections,
        "hard_failures": failures,
        "section_degradations": degradations,
        "warnings": [str(value) for value in warnings if str(value).strip()],
        "report_can_continue": can_continue,
        "content_contract_status": severity,
        "search_authority": search,
        "runtime_provenance": runtime,
    }


def compact_visible_content_status(proof: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the compact user-facing status, never the full audit proof."""
    status = str(proof.get("content_contract_status") or "").upper()
    rows = []
    for row in proof.get("section_states") or []:
        if not isinstance(row, Mapping):
            continue
        state = str(row.get("state") or "").upper()
        if state not in DEGRADED_STATES:
            continue
        rows.append(
            {
                "section": row.get("section_id"),
                "state": state,
                "available_count": row.get("available_count"),
                "expected_count": row.get("expected_count"),
            }
        )
    return {
        "content_contract": status or "UNKNOWN",
        "degraded_sections": rows,
    }
