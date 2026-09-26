from __future__ import annotations

"""Unified Stage-F delivery barrier for V12 visible reports.

This module owns no football model, no factual acquisition and no scheduler.
It composes the current Stage A-E report-plane validators into one fail-closed
delivery gate. It must never reconstruct football decisions.
"""

from typing import Any, Mapping

from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery
from src.runtime_v6.domains.report_plane.report_qa import (
    _validate_v12_rendered_body,
    validate_v12_visible_content_contract,
)


DEEP_SECTION_IDS = [
    "S01", "S02", "S03", "S04", "S05", "S06", "S06B", "S07",
    "S08", "S09", "S10", "S11", "S12", "S13", "S14", "S14B",
    "S15", "S15B", "S16", "S16B", "S17", "S18", "S19",
]
MATCH_SECTION_IDS = [f"MATCH{i}" for i in range(1, 14)]
POST_ALL_MATCH_SECTION_IDS = [f"POST_ALL_MATCH{i}" for i in range(1, 14)]

DEEP_STRUCTURAL_MODES = {
    "DEEP",
    "FULL",
    "DEADLINE",
    "FINAL",
    "OVERLAP",
    "DEEP+MATCH",
    "MATCH+DEEP",
    "FULL+MATCH",
    "MATCH+FULL",
    "PRICE+MATCH",
    "MATCH+PRICE",
    "DEADLINE+MATCH",
    "MATCH+DEADLINE",
}


def _section_ids(report: Mapping[str, Any]) -> list[str]:
    return [
        str(row.get("section_id") or "").upper()
        for row in report.get("sections") or []
        if isinstance(row, Mapping)
    ]


def _exact_catalog_failures(
    *,
    actual: list[str],
    expected: list[str],
    prefix: str,
) -> list[str]:
    failures: list[str] = []
    if actual != expected:
        failures.append(
            f"{prefix}_CATALOG_MISMATCH=" + ",".join(actual)
        )
    if len(actual) != len(set(actual)):
        failures.append(f"{prefix}_DUPLICATE_SECTION")
    return failures


def _resolve_contract(
    report: Mapping[str, Any],
    content_contract: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if isinstance(content_contract, Mapping):
        return dict(content_contract)
    candidate = report.get("content_contract")
    if isinstance(candidate, Mapping):
        return dict(candidate)
    return None


def _current_mode_contract_failures(
    *,
    mode: str,
    report: Mapping[str, Any],
    body: str,
    content_contract: Mapping[str, Any] | None,
) -> list[str]:
    contract = _resolve_contract(report, content_contract)
    if contract is None:
        return [f"{mode}_CONTENT_CONTRACT_MISSING"]

    semantic = validate_v12_visible_content_contract(
        report_mode=mode,
        content_contract=contract,
    )
    failures = list(semantic.get("failures") or [])
    failures.extend(
        _validate_v12_rendered_body(
            report_mode=mode,
            rendered_body=body,
            content_contract=contract,
        )
    )
    return failures


def validate_final_delivery_barrier(
    *,
    report_mode: str,
    report: Mapping[str, Any],
    body: str,
    content_contract: Mapping[str, Any] | None = None,
    finalization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one final fail-closed delivery verdict across Stage A-E semantics."""
    mode = str(report_mode or "").strip().upper()
    text = str(body or "")
    failures: list[str] = []
    ids = _section_ids(report)

    if mode in DEEP_STRUCTURAL_MODES:
        failures.extend(
            _exact_catalog_failures(
                actual=ids,
                expected=DEEP_SECTION_IDS,
                prefix="DEEP",
            )
        )
        failures.extend(validate_deep_decision_content_delivery(report, text))

    elif mode == "MATCH":
        failures.extend(
            _exact_catalog_failures(
                actual=ids,
                expected=MATCH_SECTION_IDS,
                prefix="MATCH",
            )
        )
        failures.extend(
            _current_mode_contract_failures(
                mode="MATCH",
                report=report,
                body=text,
                content_contract=content_contract,
            )
        )

    elif mode == "POST_ALL_MATCH":
        failures.extend(
            _exact_catalog_failures(
                actual=ids,
                expected=POST_ALL_MATCH_SECTION_IDS,
                prefix="POST_ALL_MATCH",
            )
        )
        failures.extend(
            _current_mode_contract_failures(
                mode="POST_ALL_MATCH",
                report=report,
                body=text,
                content_contract=content_contract,
            )
        )

    elif mode == "POST_MATCH":
        # POST_MATCH is incremental evidence carried inside the MATCH lifecycle,
        # not a competing top-level report schema.
        if "RELEVANT LEAGUE-WIDE SIGNALS" not in text.upper():
            failures.append("POST_MATCH_SIGNAL_SURFACE_NOT_VISIBLE")
        if (
            "MODEL UPDATE PENDING" not in text.upper()
            and "POSTERIOR UPDATED" not in text.upper()
            and "ACTUAL MODEL UPDATE" not in text.upper()
        ):
            failures.append("POST_MATCH_MODEL_UPDATE_STATE_NOT_VISIBLE")

    else:
        failures.append("FINAL_BARRIER_UNSUPPORTED_MODE=" + mode)

    if finalization is not None:
        final = dict(finalization)
        due = bool(final.get("final_report_due"))
        visible_count = final.get("visible_report_count")
        if due and visible_count != 1:
            failures.append(
                f"FINALIZATION_VISIBLE_REPORT_COUNT={visible_count}"
            )
        if final.get("combined_report") is True and visible_count != 1:
            failures.append("OVERLAP_DUPLICATE_VISIBLE_REPORT")

        lifecycle_event = str(
            final.get("dynamic_lifecycle_event") or ""
        ).upper()
        final_mode = str(final.get("final_mode") or "").upper()
        obligations = {
            str(value).upper()
            for value in final.get("embedded_obligations") or []
        }
        if (
            lifecycle_event == "POST_MATCH"
            and final_mode == "MATCH"
            and "POST_MATCH_INCREMENTAL" not in obligations
        ):
            failures.append("POST_MATCH_INCREMENTAL_OBLIGATION_MISSING")
        if (
            lifecycle_event == "POST_ALL_MATCH"
            and "POST_ALL_MATCH" not in final_mode
        ):
            failures.append("POST_ALL_MATCH_FINAL_MODE_MISMATCH")

    failures = list(dict.fromkeys(failures))
    return {
        "status": "PASS" if not failures else "FAIL",
        "can_emit": not failures,
        "report_mode": mode,
        "section_ids": ids,
        "failures": failures,
        "governance": {
            "single_visible_report": True,
            "no_second_model_authority": True,
            "v6_factual_plane_unchanged": True,
            "human_facing_pass_requires_final_barrier_pass": True,
            "uses_current_stage_e_contract": True,
        },
    }
