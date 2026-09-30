from __future__ import annotations

"""Canonical section-source resolver for report-first DEEP delivery.

This resolver is presentation/delivery logic only. It never computes football
analytics. Candidate priority is locked to:

CURRENT -> CURRENT-BOUND -> PRIOR -> UNAVAILABLE.
"""

from copy import deepcopy
from typing import Any, Mapping

SECTION_SOURCE_STATES = ("CURRENT", "CURRENT-BOUND", "PRIOR", "UNAVAILABLE")


class SectionResolutionError(RuntimeError):
    pass


def _content(candidate: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(candidate, Mapping):
        return None
    value = candidate.get("content")
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if value not in (None, "", [], {}):
        return {"value": deepcopy(value)}
    return None


def _semantic_state(candidate: Mapping[str, Any] | None, default: str) -> str:
    state = str((candidate or {}).get("state") or default).strip().upper()
    if state not in {"COMPLETE", "DEGRADED", "UNAVAILABLE"}:
        return default
    return state


def _current_bound_proof_valid(proof: Any) -> bool:
    return (
        isinstance(proof, Mapping)
        and proof.get("exact_lineage_match") is True
        and proof.get("dependency_unchanged") is True
        and proof.get("mathematically_applicable") is True
    )


def resolve_section(
    *,
    section_id: str,
    label: str,
    current: Mapping[str, Any] | None = None,
    current_bound: Mapping[str, Any] | None = None,
    prior: Mapping[str, Any] | None = None,
    prior_source_occurrence: str | None = None,
    unavailable_reason: str = "current authoritative evidence unavailable",
) -> dict[str, Any]:
    """Resolve exactly one canonical section without inventing freshness."""

    current_content = _content(current)
    if current_content is not None and _semantic_state(current, "COMPLETE") != "UNAVAILABLE":
        if (
            str(current_content.get("presentation_status") or "").upper() == "PRIOR"
            or current_content.get("prior_source_occurrence")
        ):
            raise SectionResolutionError(
                f"{section_id}: prior payload cannot be admitted as CURRENT"
            )
        current_content["presentation_status"] = "CURRENT"
        return {
            "section_id": section_id,
            "label": label,
            "state": _semantic_state(current, "COMPLETE"),
            "degradation_reason": (current or {}).get("degradation_reason"),
            "content": current_content,
            "source_state": "CURRENT",
        }

    bound_content = _content(current_bound)
    if bound_content is not None:
        proof = (
            (current_bound or {}).get("current_bound_proof")
            or bound_content.get("current_bound_proof")
        )
        if _current_bound_proof_valid(proof):
            bound_content.pop("prior_source_occurrence", None)
            bound_content["presentation_status"] = "CURRENT-BOUND"
            bound_content["current_bound_proof"] = deepcopy(dict(proof))
            return {
                "section_id": section_id,
                "label": label,
                "state": _semantic_state(current_bound, "COMPLETE"),
                "degradation_reason": (current_bound or {}).get("degradation_reason"),
                "content": bound_content,
                "source_state": "CURRENT-BOUND",
            }

    prior_content = _content(prior)
    if prior_content is not None:
        source_occurrence = str(
            prior_source_occurrence
            or prior_content.get("prior_source_occurrence")
            or ""
        ).strip()
        if not source_occurrence:
            raise SectionResolutionError(
                f"{section_id}: PRIOR requires source occurrence provenance"
            )
        prior_content["presentation_status"] = "PRIOR"
        prior_content["prior_source_occurrence"] = source_occurrence
        prior_content["prior_reason"] = (
            prior_content.get("prior_reason")
            or "historical context only; not fresh decision evidence"
        )
        return {
            "section_id": section_id,
            "label": label,
            "state": "DEGRADED",
            "degradation_reason": "PRIOR_ANALYTICS_EXPLICITLY_LABELLED",
            "content": prior_content,
            "source_state": "PRIOR",
        }

    return {
        "section_id": section_id,
        "label": label,
        "state": "UNAVAILABLE",
        "degradation_reason": unavailable_reason,
        "content": {
            "presentation_status": "UNAVAILABLE",
            "root_failure": unavailable_reason,
            "empty_is_truthful": True,
        },
        "source_state": "UNAVAILABLE",
    }


def validate_resolved_sections(sections: list[Mapping[str, Any]]) -> list[str]:
    failures: list[str] = []
    for row in sections:
        section_id = str(row.get("section_id") or "UNKNOWN")
        source_state = str(row.get("source_state") or "").upper()
        content = row.get("content")
        payload = dict(content) if isinstance(content, Mapping) else {}
        presentation = str(payload.get("presentation_status") or "").upper()

        if source_state not in SECTION_SOURCE_STATES:
            failures.append(f"{section_id}:SOURCE_STATE_INVALID")
            continue
        if presentation != source_state:
            failures.append(f"{section_id}:PRESENTATION_SOURCE_STATE_MISMATCH")
        if source_state == "PRIOR" and not payload.get("prior_source_occurrence"):
            failures.append(f"{section_id}:PRIOR_PROVENANCE_MISSING")
        if source_state == "CURRENT" and payload.get("prior_source_occurrence"):
            failures.append(f"{section_id}:FALSE_CURRENT")
        if source_state == "CURRENT-BOUND" and not _current_bound_proof_valid(
            payload.get("current_bound_proof")
        ):
            failures.append(f"{section_id}:CURRENT_BOUND_PROOF_INVALID")
    return failures
