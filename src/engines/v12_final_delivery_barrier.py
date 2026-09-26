from __future__ import annotations

"""Unified Stage-F delivery barrier for V12 visible reports.

This module owns no football model, no factual acquisition and no scheduler.
It only composes existing report-plane validators into one fail-closed gate.
"""

from typing import Any, Mapping

from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery
from src.engines.v12_report_orchestration import (
    validate_match_lifecycle_surface,
    validate_post_all_match_lifecycle_surface,
)


DEEP_SECTION_IDS = [
    "S01", "S02", "S03", "S04", "S05", "S06", "S06B", "S07",
    "S08", "S09", "S10", "S11", "S12", "S13", "S14", "S14B",
    "S15", "S15B", "S16", "S16B", "S17", "S18", "S19",
]
MATCH_SECTION_IDS = [f"MATCH{i}" for i in range(1, 14)]
POST_ALL_MATCH_SECTION_IDS = [f"POST_ALL_MATCH{i}" for i in range(1, 14)]


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
            f"{prefix}_CATALOG_MISMATCH="
            + ",".join(actual)
        )
    if len(actual) != len(set(actual)):
        failures.append(f"{prefix}_DUPLICATE_SECTION")
    return failures


def validate_final_delivery_barrier(
    *,
    report_mode: str,
    report: Mapping[str, Any],
    body: str,
    content_contract: Mapping[str, Any] | None = None,
    finalization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one final fail-closed delivery verdict across A-E semantics."""
    mode = str(report_mode or "").upper()
    text = str(body or "")
    failures: list[str] = []
    ids = _section_ids(report)

    if mode in {"DEEP", "FULL", "DEADLINE", "FINAL"}:
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
        surface = (
            report.get("match_surface")
            if isinstance(report.get("match_surface"), Mapping)
            else content_contract
        )
        failures.extend(validate_match_lifecycle_surface(surface or {}))
        for marker in (
            "MATCH CHECKPOINT / GW STATUS",
            "LOCKED PERSONAL TEAM",
            "PERSONAL IMPACT FIRST",
            "GLOBAL AUTOSUB STATE",
            "CAPTAIN / VICE CONSEQUENCE",
            "OWNED LIVE/FINAL POINTS",
            "BONUS/BPS",
            "SOURCE / FRESHNESS STATUS",
        ):
            if marker not in text.upper():
                failures.append("MATCH_VISIBLE_MARKER_MISSING=" + marker)

    elif mode == "POST_ALL_MATCH":
        failures.extend(
            _exact_catalog_failures(
                actual=ids,
                expected=POST_ALL_MATCH_SECTION_IDS,
                prefix="POST_ALL_MATCH",
            )
        )
        surface = (
            report.get("post_all_match_surface")
            if isinstance(report.get("post_all_match_surface"), Mapping)
            else content_contract
        )
        failures.extend(
            validate_post_all_match_lifecycle_surface(surface or {})
        )
        if "GW COMPLETED MATCH-BY-MATCH SCOUT" not in text.upper():
            failures.append("POST_ALL_MATCH_SCOUT_NOT_VISIBLE")

    elif mode == "POST_MATCH":
        if "RELEVANT LEAGUE-WIDE SIGNALS" not in text.upper():
            failures.append("POST_MATCH_SIGNAL_SURFACE_NOT_VISIBLE")
        if "MODEL UPDATE PENDING" not in text.upper() and "ACTUAL MODEL UPDATE" not in text.upper():
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
        },
    }
