from __future__ import annotations

"""Transient evidence builder for V12 visible-content conformance.

This module does not validate report content, acquire data, persist state, or become
methodology authority. It only packages occurrence-bound evidence about how the
Canonical visible-content contract was applied by the actual runtime.
"""

from datetime import datetime
from hashlib import sha256
import re
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


def _git_revision(value: Any, *, label: str) -> str:
    text = _nonempty(value, label=label)
    if len(text) not in {40, 64} or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        raise VisibleContentProofError(f"{label} must be a Git revision hex digest")
    return text.lower()


def _normalise_revision(
    *,
    canonical_authority_path: str,
    canonical_version: str,
    canonical_revision: Mapping[str, Any] | None,
    legacy_content_sha256: str | None,
) -> dict[str, Any]:
    if canonical_revision is None:
        if legacy_content_sha256 is None:
            raise VisibleContentProofError("canonical_revision or computed content SHA-256 is required")
        return {
            "path": canonical_authority_path,
            "branch_or_ref": None,
            "branch_head_sha": None,
            "file_blob_sha": None,
            "content_sha256": _sha256(legacy_content_sha256, label="canonical_content_fingerprint_sha256"),
            "content_sha256_computed": True,
            "canonical_version": canonical_version,
        }
    row = dict(canonical_revision)
    if str(row.get("path") or "") != canonical_authority_path:
        raise VisibleContentProofError("canonical_revision.path must match Canonical V12")
    branch_or_ref = _nonempty(row.get("branch_or_ref"), label="canonical_revision.branch_or_ref")
    branch_head = _git_revision(row.get("branch_head_sha"), label="canonical_revision.branch_head_sha")
    blob = _git_revision(row.get("file_blob_sha"), label="canonical_revision.file_blob_sha")
    computed = bool(row.get("content_sha256_computed"))
    content_sha = row.get("content_sha256")
    if computed:
        content_sha = _sha256(content_sha, label="canonical_revision.content_sha256")
    elif content_sha not in (None, ""):
        raise VisibleContentProofError(
            "content_sha256 must be null when content_sha256_computed=false"
        )
    else:
        content_sha = None
    version = _nonempty(row.get("canonical_version") or canonical_version, label="canonical_revision.canonical_version")
    return {
        "path": canonical_authority_path,
        "branch_or_ref": branch_or_ref,
        "branch_head_sha": branch_head,
        "file_blob_sha": blob,
        "content_sha256": content_sha,
        "content_sha256_computed": computed,
        "canonical_version": version,
    }


def _canonical_subsection(canonical_text: str, tag: str) -> tuple[str, str]:
    """Return one Canonical 14x subsection title/body without duplicating its schema."""
    heading = re.compile(rf"(?m)^{re.escape(tag)}\.\s+(?P<title>.+)$").search(canonical_text)
    if not heading:
        raise VisibleContentProofError(f"Canonical {tag} subsection not found")
    next_heading = re.compile(r"(?m)^14[A-Z](?:\d+)?\.\s+").search(
        canonical_text, heading.end()
    )
    end = next_heading.start() if next_heading else len(canonical_text)
    return heading.group("title").strip(), canonical_text[heading.end():end]


def _canonical_numbered_rows(
    canonical_text: str,
    *,
    tag: str,
    section_prefix: str,
    zero_pad: bool = False,
) -> list[dict[str, str]]:
    """Parse the numbered visible structure owned by one Canonical subsection."""
    _, block = _canonical_subsection(canonical_text, tag)
    rows: list[dict[str, str]] = []
    for raw in block.splitlines():
        match = re.match(r"^(?P<ordinal>\d+B?)\s+(?P<label>.+?)\.?$", raw.strip())
        if not match:
            continue
        ordinal = match.group("ordinal").upper()
        label = match.group("label").strip().rstrip(".")
        number_match = re.fullmatch(r"(?P<number>\d+)(?P<suffix>B?)", ordinal)
        if not number_match:
            continue
        number = int(number_match.group("number"))
        suffix = number_match.group("suffix")
        if zero_pad:
            section_id = f"{section_prefix}{number:02d}{suffix}"
        else:
            section_id = f"{section_prefix}{number}{suffix}"
        rows.append({"section_id": section_id, "label": label})
    if not rows:
        raise VisibleContentProofError(f"Canonical {tag} numbered visible-order rows not found")
    return rows


def _contract_from_rows(mode: str, rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    return {
        "report_mode": mode,
        "expected_section_ids": [str(row["section_id"]) for row in rows],
        "expected_visible_order": [str(row["label"]) for row in rows],
    }


def canonical_mode_contract(canonical_text: str, report_mode: str) -> dict[str, Any]:
    """Derive structural section identity/order directly from the current Canonical text."""
    text = _nonempty(canonical_text, label="canonical_text")
    mode = str(report_mode or "").strip().upper()

    if mode in {"DEEP", "FULL", "DEADLINE", "FINAL"}:
        rows = _canonical_numbered_rows(
            text,
            tag="14A",
            section_prefix="S",
            zero_pad=True,
        )
        if mode == "FINAL":
            final_title, final_body = _canonical_subsection(text, "14I")
            lock_label = re.sub(r"^FINAL\s+[—-]\s*", "", final_title).strip().rstrip(".")
            if not lock_label or "before alternatives" not in final_body.lower():
                raise VisibleContentProofError(
                    "Canonical FINAL GW LOCK PACKAGE placement semantics not found"
                )
            lock_section_id = re.sub(r"[^A-Z0-9]+", "_", lock_label.upper()).strip("_")
            alternatives_index = next(
                (
                    index
                    for index, row in enumerate(rows)
                    if "PACKAGE" in row["label"].upper()
                    and "FRONTIER" in row["label"].upper()
                ),
                None,
            )
            if alternatives_index is None:
                raise VisibleContentProofError(
                    "Canonical Full/Deep alternatives section not found for FINAL insertion"
                )
            rows.insert(
                alternatives_index,
                {"section_id": lock_section_id, "label": lock_label},
            )
        return _contract_from_rows(mode, rows)

    if mode == "MATCH":
        rows = _canonical_numbered_rows(
            text,
            tag="14B",
            section_prefix="MATCH",
        )
        return _contract_from_rows(mode, rows)

    if mode == "POST_ALL_MATCH":
        rows = _canonical_numbered_rows(
            text,
            tag="14J",
            section_prefix="POST_ALL_MATCH",
        )
        return _contract_from_rows(mode, rows)

    if mode == "PRICE":
        rows = _canonical_numbered_rows(
            text,
            tag="14L",
            section_prefix="PRICE",
        )
        return _contract_from_rows(mode, rows)

    return {"report_mode": mode, "expected_section_ids": [], "expected_visible_order": []}


def _coverage(
    *,
    expected_section_ids: Sequence[str],
    rendered_section_ids: Sequence[str],
    expected_visible_order: Sequence[str],
    rendered_visible_order: Sequence[str],
) -> dict[str, Any]:
    expected = [str(value) for value in expected_section_ids]
    rendered = [str(value) for value in rendered_section_ids]
    missing = [value for value in expected if value not in rendered]
    unexpected = [value for value in rendered if value not in expected]
    order_valid = rendered == expected and list(rendered_visible_order) == list(expected_visible_order)
    failures: list[str] = []
    if missing:
        failures.append("MODE_SECTIONS_MISSING=" + ",".join(missing))
    if unexpected:
        failures.append("MODE_SECTIONS_UNEXPECTED=" + ",".join(unexpected))
    if not order_valid:
        failures.append("MODE_VISIBLE_ORDER_INVALID")
    return {
        "expected_section_ids": expected,
        "rendered_section_ids": rendered,
        "missing_section_ids": missing,
        "unexpected_section_ids": unexpected,
        "expected_visible_order": list(expected_visible_order),
        "rendered_visible_order": list(rendered_visible_order),
        "visible_order_valid": order_valid,
        "hard_failures": failures,
    }


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
    canonical_revision: Mapping[str, Any] | None = None,
    canonical_content_fingerprint_sha256: str | None = None,
    canonical_text: str | None = None,
    expected_section_ids: Sequence[str] | None = None,
    rendered_section_ids: Sequence[str] = (),
    expected_visible_order: Sequence[str] | None = None,
    rendered_visible_order: Sequence[str] = (),
) -> dict[str, Any]:
    """Build one transient VISIBLE_CONTENT_PROOF for a due report occurrence."""
    if canonical_authority_path != CANONICAL_AUTHORITY:
        raise VisibleContentProofError("VISIBLE_CONTENT_PROOF must bind Canonical V12")
    version = _nonempty(canonical_version, label="canonical_version")
    revision = _normalise_revision(
        canonical_authority_path=canonical_authority_path,
        canonical_version=version,
        canonical_revision=canonical_revision,
        legacy_content_sha256=canonical_content_fingerprint_sha256,
    )
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

    derived = None
    if canonical_text is not None:
        derived = canonical_mode_contract(canonical_text, mode)
    expected_ids = list(
        expected_section_ids
        if expected_section_ids is not None
        else (derived or {}).get("expected_section_ids", [])
    )
    expected_order = list(
        expected_visible_order
        if expected_visible_order is not None
        else (derived or {}).get("expected_visible_order", [])
    )
    coverage = _coverage(
        expected_section_ids=expected_ids,
        rendered_section_ids=rendered_section_ids,
        expected_visible_order=expected_order,
        rendered_visible_order=rendered_visible_order,
    ) if expected_ids or rendered_section_ids or expected_order or rendered_visible_order else {
        "expected_section_ids": [],
        "rendered_section_ids": [],
        "missing_section_ids": [],
        "unexpected_section_ids": [],
        "expected_visible_order": [],
        "rendered_visible_order": [],
        "visible_order_valid": True,
        "hard_failures": [],
    }
    failures.extend(coverage["hard_failures"])
    missing_state_ids = [
        section_id for section_id in expected_ids if section_id not in state_by_id
    ]
    if missing_state_ids:
        failures.append("MODE_SECTION_STATE_MISSING=" + ",".join(missing_state_ids))
    failures = list(dict.fromkeys(failures))

    due = bool(report_due)
    can_continue = bool(report_can_continue)
    derived_continue = not failures
    if due and can_continue != derived_continue:
        raise VisibleContentProofError(
            "for REPORT_DUE, report_can_continue must match hard/structural conformance"
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
            "content_sha256": revision.get("content_sha256"),
            "version": revision.get("canonical_version"),
        },
        "canonical_revision": revision,
        "report_slot": slot,
        "report_mode": mode,
        "report_due": due,
        "observed_at": observed,
        "section_states": normalised_sections,
        "expected_section_ids": coverage["expected_section_ids"],
        "rendered_section_ids": coverage["rendered_section_ids"],
        "missing_section_ids": coverage["missing_section_ids"],
        "unexpected_section_ids": coverage["unexpected_section_ids"],
        "expected_visible_order": coverage["expected_visible_order"],
        "rendered_visible_order": coverage["rendered_visible_order"],
        "visible_order_valid": coverage["visible_order_valid"],
        "hard_failures": failures,
        "section_degradations": degradations,
        "warnings": [str(value) for value in warnings if str(value).strip()],
        "report_can_continue": can_continue,
        "content_contract_status": severity,
        "search_authority": search,
        "runtime_provenance": runtime,
    }


def compact_content_proof_audit_line(proof: Mapping[str, Any]) -> str:
    revision = proof.get("canonical_revision") if isinstance(proof.get("canonical_revision"), Mapping) else {}
    runtime = proof.get("runtime_provenance") if isinstance(proof.get("runtime_provenance"), Mapping) else {}
    canonical = str(revision.get("branch_head_sha") or revision.get("file_blob_sha") or "UNPROVEN")
    python_state = str(runtime.get("python_qa_status") or "NOT_PROVEN")
    contract = str(proof.get("content_contract_status") or "UNKNOWN")
    slot = str(proof.get("report_slot") or "")
    mode = str(proof.get("report_mode") or "")
    return (
        f"CONTENT PROOF slot={slot} mode={mode} Canonical={canonical} "
        f"runtime=ChatGPT Automation Python QA={python_state} contract={contract}"
    )



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
