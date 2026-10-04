from __future__ import annotations

"""Unified Stage-F delivery barrier for V12 visible reports.

This module owns no football model, no factual acquisition and no scheduler.
It composes the current Stage A-E report-plane validators into one fail-closed
delivery gate. It must never reconstruct football decisions.
"""

from typing import Any, Mapping

from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery
from src.engines.v12_deep_presentation_lock import validate_rendered_deep_presentation
from src.engines.v12_delivery_reliability import canonical_deep_sections
from src.runtime_v6.domains.report_plane.report_qa import (
    _validate_v12_rendered_body,
    validate_v12_visible_content_contract,
)


DEEP_SECTION_IDS = [
    section_id
    for section_id, _ in canonical_deep_sections(s16b_due=False)
]
DEEP_SECTION_IDS_WITH_S16B = [
    section_id
    for section_id, _ in canonical_deep_sections(s16b_due=True)
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


def _deep_semantic_population_failures(
    report: Mapping[str, Any],
    body: str,
) -> list[str]:
    """Fail closed when occurrence-supported evidence is lost after production."""

    def section(section_id: str) -> tuple[str, dict[str, Any]]:
        for raw in report.get("sections") or []:
            if not isinstance(raw, Mapping):
                continue
            if str(raw.get("section_id") or "").upper() != section_id:
                continue
            return (
                str(raw.get("state") or raw.get("status") or "").upper(),
                dict(raw.get("content") or {}),
            )
        return ("MISSING", {})

    def missing(value: Any) -> bool:
        return value is None or str(value).strip().upper() == "UNAVAILABLE"

    def body_section(start_number: str, end_number: str) -> str:
        start_token = f"## {start_number}."
        end_token = f"## {end_number}."
        start = body.find(start_token)
        if start < 0:
            return ""
        end = body.find(end_token, start + len(start_token))
        return body[start:] if end < 0 else body[start:end]

    failures: list[str] = []

    # S08: canonical PMF evidence may be incomplete truthfully, but it may not
    # disappear between the captain owner and the visible RETURN PROFILE.
    s08_state, s08 = section("S08")
    profiles = [
        dict(row)
        for row in s08.get("captain_profiles") or []
        if isinstance(row, Mapping)
    ]
    pmf_supported = [
        row for row in profiles if row.get("pmf_available") is True
    ]
    for row in pmf_supported:
        if any(
            missing(row.get(key))
            for key in ("p_blank", "p_haul", "p_ge_10")
        ):
            failures.append(
                "S08_AVAILABLE_PMF_DROPPED="
                + str(row.get("element_id") or "UNKNOWN")
            )
    if s08_state == "COMPLETE":
        incomplete = [
            str(row.get("element_id") or "UNKNOWN")
            for row in profiles
            if row.get("football_evidence_complete") is not True
        ]
        if incomplete:
            failures.append(
                "S08_COMPLETE_MASKS_INCOMPLETE_EVIDENCE="
                + ",".join(incomplete)
            )
    s08_body = body_section("8", "9")
    if (
        pmf_supported
        and "Pblank=UNAVAILABLE | Phaul=UNAVAILABLE | P>=10=UNAVAILABLE"
        in s08_body
    ):
        failures.append("S08_RENDER_DROPPED_AVAILABLE_RETURN_PROFILE")

    # S10: use canonical element identity. Matching predictor evidence must bind
    # to visible direction/progress; genuine no-row/unsupported evidence may
    # remain unavailable only under a degraded section state.
    s10_state, s10 = section("S10")
    s10_rows = [
        dict(row)
        for row in s10.get("rows") or []
        if isinstance(row, Mapping)
    ]
    binding_failures = [
        str(value)
        for value in s10.get("semantic_binding_failures") or []
    ]
    if binding_failures:
        failures.append(
            "S10_PREDICTOR_BINDING_FAILURE="
            + ",".join(binding_failures)
        )
    genuine_missing = list(s10.get("genuine_predictor_unavailable") or [])
    if s10_state == "COMPLETE" and genuine_missing:
        failures.append("S10_COMPLETE_MASKS_GENUINE_PREDICTOR_UNAVAILABLE")
    by_element: dict[int, dict[str, Any]] = {}
    for row in s10_rows:
        try:
            element = int(row.get("element_id") or 0)
        except (TypeError, ValueError):
            element = 0
        if element > 0:
            by_element[element] = row
        if row.get("predictor_binding_state") == "BOUND" and (
            missing(row.get("direction"))
            or missing(row.get("official_or_provider_progress"))
        ):
            failures.append(
                "S10_AVAILABLE_PREDICTOR_DROPPED="
                + str(row.get("element_id") or "UNKNOWN")
            )

    supported_elsewhere: set[int] = set()
    for sid in ("S12", "S13"):
        _, content = section(sid)
        for row in content.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            try:
                element = int(
                    row.get("element_id")
                    or row.get("element")
                    or row.get("id")
                    or 0
                )
            except (TypeError, ValueError):
                element = 0
            progress = row.get(
                "official_or_provider_progress",
                row.get("current_progress_percent", row.get("projected_percent")),
            )
            if element > 0 and not missing(progress):
                supported_elsewhere.add(element)
    for element in sorted(supported_elsewhere & set(by_element)):
        row = by_element[element]
        if missing(row.get("direction")) or missing(
            row.get("official_or_provider_progress")
        ):
            failures.append(
                f"S10_S12_S13_CROSS_SECTION_BINDING_LOSS={element}"
            )
    s10_body = body_section("10", "11")
    supported_s10 = sum(
        row.get("predictor_binding_state") == "BOUND"
        and not missing(row.get("direction"))
        and not missing(row.get("official_or_provider_progress"))
        for row in s10_rows
    )
    if (
        supported_s10 > 0
        and s10_rows
        and s10_body.count("| UNAVAILABLE | UNAVAILABLE |") >= len(s10_rows)
    ):
        failures.append("S10_RENDER_DROPPED_AVAILABLE_PREDICTOR_FIELDS")

    # S11: presentation adapter is a direct view over canonical football_score
    # and admission_gate. Actionable must equal the admitted Scanner20 subset.
    s11_state, s11 = section("S11")
    s11_rows = [
        dict(row)
        for row in (s11.get("scanner20") or s11.get("rows") or [])
        if isinstance(row, Mapping)
    ]
    semantic_s11 = [
        str(value)
        for value in s11.get("semantic_binding_failures") or []
    ]
    if semantic_s11:
        failures.append(
            "S11_PRESENTATION_BINDING_FAILURE="
            + ",".join(semantic_s11)
        )
    admitted_ids: set[int] = set()
    for row in s11_rows:
        gate = dict(row.get("admission_gate") or {})
        gate_admitted = gate.get("admitted")
        element = int(row.get("element_id") or 0)
        if row.get("football_score") is not None and missing(row.get("score")):
            failures.append(f"S11_AVAILABLE_SCORE_DROPPED={element}")
        if isinstance(gate_admitted, bool):
            if missing(row.get("admit")) or row.get("admit") is not gate_admitted:
                failures.append(f"S11_ADMISSION_BINDING_LOSS={element}")
            if gate_admitted:
                admitted_ids.add(element)
        if gate and missing(row.get("evidence")):
            failures.append(f"S11_EVIDENCE_BINDING_LOSS={element}")
    actionable_ids = {
        int(row.get("element_id") or 0)
        for row in s11.get("actionable_watchlist") or []
        if isinstance(row, Mapping)
    }
    if s11_rows and actionable_ids != admitted_ids:
        failures.append("S11_ACTIONABLE_ADMISSION_INCONSISTENT")
    if s11_state == "COMPLETE" and any(
        missing(row.get("score"))
        or missing(row.get("admit"))
        or missing(row.get("evidence"))
        for row in s11_rows
    ):
        failures.append("S11_COMPLETE_MASKS_REQUIRED_UNAVAILABLE")
    s11_body = body_section("11", "12")
    if (
        s11_rows
        and not any(
            missing(row.get("score"))
            or missing(row.get("admit"))
            or missing(row.get("evidence"))
            for row in s11_rows
        )
        and s11_body.count("| UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |")
        >= len(s11_rows)
    ):
        failures.append("S11_RENDER_DROPPED_CANONICAL_PRESENTATION_FIELDS")

    # S16: values are copied from canonical 1GW event probabilities and PMF.
    # Genuine unsupported fields force DEGRADED; available evidence may not be
    # silently lost while the section still claims COMPLETE.
    s16_state, s16 = section("S16")
    s16_rows = [
        dict(row)
        for row in s16.get("rows") or []
        if isinstance(row, Mapping)
    ]
    if s16.get("semantic_binding_failures"):
        failures.append("S16_CANONICAL_PROBABILITY_BINDING_FAILURE")
    genuine_probability_missing = list(
        s16.get("genuine_probability_unavailable") or []
    )
    if s16_state == "COMPLETE" and genuine_probability_missing:
        failures.append("S16_COMPLETE_MASKS_GENUINE_PROBABILITY_UNAVAILABLE")
    supported_rows = 0
    for row in s16_rows:
        probabilities = dict(row.get("probabilities") or {})
        evidence = dict(row.get("probability_evidence") or {})
        unsupported = {
            str(value)
            for value in evidence.get("unsupported_fields") or []
        }
        if evidence.get("binding_failures"):
            failures.append(
                "S16_AVAILABLE_PROBABILITY_DROPPED="
                + str(row.get("element_id") or "UNKNOWN")
            )
        required = ("p_goal", "p_assist", "p_return", "p_haul", "p_blank")
        for key in required:
            if key not in unsupported and (
                evidence.get("event_probabilities_available") is True
                or evidence.get("point_distribution_available") is True
            ) and missing(probabilities.get(key)):
                failures.append(
                    "S16_VISIBLE_PROBABILITY_MISSING="
                    + str(row.get("element_id") or "UNKNOWN")
                    + ":"
                    + key
                )
        if all(not missing(probabilities.get(key)) for key in required):
            supported_rows += 1

    s16_body = body_section("16", "17")
    all_unavailable_probability_line = (
        "Probability: Pgoal UNAVAILABLE; Passist UNAVAILABLE; "
        "Preturn UNAVAILABLE; Phaul UNAVAILABLE; Pblank UNAVAILABLE"
    )
    if (
        supported_rows > 0
        and s16_body.count(all_unavailable_probability_line) >= supported_rows
    ):
        failures.append("S16_RENDER_DROPPED_AVAILABLE_PROBABILITIES")

    return list(dict.fromkeys(failures))


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
                expected=(
                    DEEP_SECTION_IDS_WITH_S16B
                    if report.get("s16b_due") is True
                    else DEEP_SECTION_IDS
                ),
                prefix="DEEP",
            )
        )
        failures.extend(validate_deep_decision_content_delivery(report, text))
        failures.extend(validate_rendered_deep_presentation(text, report))
        failures.extend(_deep_semantic_population_failures(report, text))

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
