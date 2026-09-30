from __future__ import annotations

"""Report-first acceptance for FPL Master V12.

This module is downstream-only. It does not acquire facts, run optimizers,
Monte Carlo, lineup selection, package ranking, rendering, or scheduling.

It separates two verdicts:
- REPORT PROD: whether a canonical visible report is safe and usable to serve.
- ENGINEERING: whether P4/PERF-F/technical closure is fully green.

Engineering closure evidence is intentionally observability-only here and must
never be used as a hidden publication prerequisite.
"""

from typing import Any, Mapping, Sequence

from src.engines.v12_delivery_reliability import (
    CANONICAL_DEEP_SECTIONS,
    DELIVERY_STATES,
    validate_presentation_qa_manifest,
    validate_serving_snapshot,
)


REPORT_PRODUCTION_GATE_VERSION = "V12_REPORT_PRODUCTION_GATE_V1"

REPORT_PRODUCTION_REQUIREMENTS: tuple[str, ...] = (
    "CANONICAL_23_SECTION_ORDER",
    "VISIBLE_CONTENT_QA",
    "OUR15_IDENTITY",
    "CURRENT_FACTUAL_BINDING",
    "NO_FALSE_CURRENT",
    "PRIOR_PROVENANCE",
    "S01_S19_CONSISTENCY",
    "SERVING_SNAPSHOT",
)

ENGINEERING_CLOSURE_REQUIREMENTS: tuple[str, ...] = (
    "P4_SCENARIO_PACKAGE",
    "P4_HIT_MISS",
    "PERF_F_LE_15S",
    "WARM_CACHE_PERFORMANCE",
    "TECHNICAL_HARD_GATES",
    "FINAL_53_GATE_CLOSURE",
)


def _section_ids(bundle: Mapping[str, Any]) -> list[str]:
    report = bundle.get("report")
    if isinstance(report, Mapping) and isinstance(report.get("sections"), Sequence):
        return [
            str(row.get("section_id") or "")
            for row in report.get("sections") or []
            if isinstance(row, Mapping)
        ]
    return [
        str(row.get("section_id") or row.get("id") or "")
        for row in bundle.get("section_manifest") or []
        if isinstance(row, Mapping)
    ]


def _sections(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    report = bundle.get("report")
    if not isinstance(report, Mapping):
        return []
    return [
        dict(row)
        for row in report.get("sections") or []
        if isinstance(row, Mapping)
    ]


def _decision_token(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("decision", "operational_state", "primary_decision", "transfer_action"):
            token = _decision_token(value.get(key))
            if token:
                return token
        return None
    token = str(value or "").strip().upper()
    if not token:
        return None
    for candidate in ("WAIT", "PREPARE", "ACT"):
        if token == candidate or token.startswith(candidate + ".") or token.startswith(candidate + " "):
            return candidate
    return token


def _qa_pass(status: Any) -> bool:
    token = str(status or "").strip().upper()
    return token in {"PASS", "DEGRADED_PRESENTATION_PASS"}


def _validate_truthful_section_states(
    sections: Sequence[Mapping[str, Any]],
) -> list[str]:
    failures: list[str] = []
    for row in sections:
        section_id = str(row.get("section_id") or "UNKNOWN")
        content = row.get("content")
        if not isinstance(content, Mapping):
            continue
        presentation_status = str(content.get("presentation_status") or "").upper()

        if presentation_status == "PRIOR":
            if not str(content.get("prior_source_occurrence") or "").strip():
                failures.append(f"{section_id}:PRIOR_WITHOUT_SOURCE_OCCURRENCE")

        if presentation_status == "CURRENT":
            if content.get("prior_source_occurrence"):
                failures.append(f"{section_id}:PRIOR_RELABELED_CURRENT")

        if presentation_status == "CURRENT_BOUND":
            proof = content.get("current_bound_proof")
            if not isinstance(proof, Mapping):
                failures.append(f"{section_id}:CURRENT_BOUND_PROOF_MISSING")
                continue
            if proof.get("exact_lineage_match") is not True:
                failures.append(f"{section_id}:CURRENT_BOUND_LINEAGE_NOT_EXACT")
            if proof.get("dependency_unchanged") is not True:
                failures.append(f"{section_id}:CURRENT_BOUND_DEPENDENCY_CHANGED")
            if proof.get("mathematically_applicable") is not True:
                failures.append(f"{section_id}:CURRENT_BOUND_NOT_APPLICABLE")

    return failures


def _validate_our15_identity(
    bundle: Mapping[str, Any],
    presentation_qa: Mapping[str, Any] | None,
) -> list[str]:
    failures: list[str] = []
    qa = dict(presentation_qa or {})
    if qa:
        if qa.get("our15_complete_when_claimed") is not True:
            failures.append("OUR15_IDENTITY_INVALID")
        count = qa.get("our15_count")
        if count not in (None, 0, 15):
            failures.append("OUR15_COUNT_NOT_15")

    sections = _sections(bundle)
    s02 = next((row for row in sections if row.get("section_id") == "S02"), {})
    content = s02.get("content") if isinstance(s02, Mapping) else None
    if not isinstance(content, Mapping):
        return failures
    if str(content.get("presentation_status") or "").upper() in {"PRIOR", "UNAVAILABLE"}:
        return failures

    rows = content.get("rows")
    if not isinstance(rows, Sequence):
        return failures
    if len(rows) != 15:
        failures.append("OUR15_ROWS_NOT_15")
        return failures

    ids: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping):
            failures.append("OUR15_ROW_INVALID")
            continue
        value = row.get("element_id")
        try:
            element_id = int(value)
        except (TypeError, ValueError):
            failures.append("OUR15_ELEMENT_ID_INVALID")
            continue
        if element_id <= 0:
            failures.append("OUR15_ELEMENT_ID_INVALID")
        ids.append(element_id)
    if len(ids) != len(set(ids)):
        failures.append("OUR15_DUPLICATE_ELEMENT_ID")
    return failures


def evaluate_report_production_gate(
    bundle: Mapping[str, Any],
    *,
    presentation_qa: Mapping[str, Any] | None = None,
    serving_snapshot: Mapping[str, Any] | None = None,
    visible_body_non_empty: bool | None = None,
) -> dict[str, Any]:
    """Evaluate only report-serving safety, never P4/PERF-F closure."""

    report_mode = str(bundle.get("report_mode") or "").upper()
    delivery_status = str(bundle.get("delivery_status") or "").upper()
    failures: list[str] = []

    if report_mode != "DEEP":
        return {
            "contract": REPORT_PRODUCTION_GATE_VERSION,
            "status": "PASS",
            "report_delivery_allowed": True,
            "failures": [],
            "engineering_closure_required_for_publish": False,
            "engineering_requirements": list(ENGINEERING_CLOSURE_REQUIREMENTS),
        }

    expected_ids = [section_id for section_id, _ in CANONICAL_DEEP_SECTIONS]
    ids = _section_ids(bundle)
    if ids != expected_ids:
        failures.append("SECTION_ORDER_OR_COUNT")
    if len(ids) != 23:
        failures.append("SECTION_COUNT_NOT_23")

    if delivery_status and delivery_status not in DELIVERY_STATES:
        failures.append("INVALID_DELIVERY_STATUS")

    pre = (bundle.get("pre_render_qa") or {}).get("status")
    post = (bundle.get("post_render_qa") or {}).get("status")
    human = (bundle.get("human_facing_qa") or {}).get("status")
    if not _qa_pass(pre):
        failures.append("PRE_RENDER_PRESENTATION_QA")
    if not _qa_pass(post):
        failures.append("POST_RENDER_PRESENTATION_QA")
    if str(human or "").upper() != "PASS":
        failures.append("HUMAN_FACING_QA")

    if visible_body_non_empty is False:
        failures.append("VISIBLE_BODY_EMPTY")

    if presentation_qa is not None:
        failures.extend(validate_presentation_qa_manifest(presentation_qa))

    sections = _sections(bundle)
    failures.extend(_validate_truthful_section_states(sections))
    failures.extend(_validate_our15_identity(bundle, presentation_qa))

    if sections:
        by_id = {str(row.get("section_id") or ""): row for row in sections}
        s01 = dict((by_id.get("S01") or {}).get("content") or {})
        s19 = dict((by_id.get("S19") or {}).get("content") or {})
        d01 = _decision_token(
            s01.get("decision")
            or s01.get("operational_state")
            or s01.get("primary_decision")
        )
        d19 = _decision_token(s19.get("decision") or s19.get("final_judgement"))
        if not d01:
            failures.append("S01_DECISION_MISSING")
        if not d19:
            failures.append("S19_DECISION_MISSING")
        if d01 and d19 and d01 != d19:
            failures.append("S01_S19_DECISION_MISMATCH")

    proof = bundle.get("execution_proof")
    if not isinstance(proof, Mapping):
        proof = {}
    if delivery_status == "READY_FULL":
        if str(bundle.get("runner_status") or "").upper() != "PASS":
            failures.append("READY_FULL_WITHOUT_RUNNER_PASS")
        if proof.get("prior_analytics_relabelled_fresh") is True:
            failures.append("FALSE_CURRENT_PRIOR_RELABEL")
    elif delivery_status == "READY_DEGRADED":
        root_failure = str(bundle.get("root_failure") or "").strip()
        if not root_failure:
            failures.append("DEGRADED_ROOT_FAILURE_MISSING")

    if serving_snapshot is not None:
        failures.extend(validate_serving_snapshot(serving_snapshot))

    unique = list(dict.fromkeys(failures))
    status = "PASS" if not unique else "FAIL"
    return {
        "contract": REPORT_PRODUCTION_GATE_VERSION,
        "status": status,
        "report_delivery_allowed": status == "PASS",
        "failures": unique,
        "delivery_status": delivery_status or "LEGACY",
        "report_mode": report_mode,
        "engineering_closure_required_for_publish": False,
        "engineering_requirements": list(ENGINEERING_CLOSURE_REQUIREMENTS),
    }
