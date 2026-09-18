from __future__ import annotations

"""Fail-closed report rendering QA gates.

Wave 6 sits after deterministic report compute and before Wave 7 delivery proof.
It never acquires data, publishes V6 artifacts, or marks a report delivered.
"""

from collections import Counter
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .delivery_integrity import MANDATORY_SECTIONS, PARTIAL_ALLOWED_SECTIONS
from .visible_body_contract import validate_visible_report_body


_FULL_COUNT_TARGETS = {
    "OUR15": 15,
    "XI": 11,
    "BENCH": 4,
    "WATCHLIST20": 20,
    "RISE20": 20,
    "FALL20": 20,
}
_MATCH_COUNT_TARGETS = {
    "OUR15": 15,
    "XI": 11,
    "BENCH": 4,
}
_MATCH_SECTION_IDS = tuple(f"MATCH{index}" for index in range(1, 9))
_FULL_BACKBONE_CATALOG_MODES = frozenset(
    {"LEGACY", "DEEP", "FULL", "DEADLINE", "FINAL", "OVERLAP", "POST_ALL_MATCH"}
)
_VALID_SECTION_STATES = frozenset({"COMPLETE", "PARTIAL"})
_MANDATORY_ORDER = {section_id: index for index, section_id in enumerate(MANDATORY_SECTIONS)}
_DEEP_WEATHER_MODES = frozenset(
    {"DEEP", "FULL", "DEADLINE", "FINAL", "OVERLAP", "POST_ALL_MATCH"}
)
_WEATHER_STATES_BY_MODE = {
    **{mode: frozenset({"DIRECT_CHATGPT", "SOURCE_DEGRADED"}) for mode in _DEEP_WEATHER_MODES},
    "MATCH": frozenset({"MATCH_CURRENT", "SOURCE_DEGRADED"}),
    "PRICE": frozenset({"DIRECT_CHATGPT", "PRICE_NOT_IN_SCOPE"}),
}


def _expected_visible_catalog(report_mode: str, generated_section_ids: Sequence[str]) -> list[str]:
    mode = str(report_mode or "LEGACY").strip().upper() or "LEGACY"
    if mode == "MATCH":
        return list(_MATCH_SECTION_IDS)
    if mode in _FULL_BACKBONE_CATALOG_MODES:
        return list(MANDATORY_SECTIONS)
    return list(generated_section_ids)


def _expected_visible_counts(report_mode: str) -> dict[str, int]:
    mode = str(report_mode or "LEGACY").strip().upper() or "LEGACY"
    if mode == "MATCH":
        return dict(_MATCH_COUNT_TARGETS)
    return dict(_FULL_COUNT_TARGETS)


def _required_visible_markers(report_mode: str) -> list[str]:
    mode = str(report_mode or "").strip().upper()
    if mode == "POST_ALL_MATCH":
        return ["GW COMPLETED MATCH-BY-MATCH SCOUT"]
    return []


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _section_sort_key(section_id: str) -> tuple[int, int | str]:
    if section_id in _MANDATORY_ORDER:
        return (0, _MANDATORY_ORDER[section_id])
    return (1, section_id)


def _canonical_section_manifest(
    section_manifest: Sequence[Mapping[str, Any]],
    *,
    expected_section_ids: Sequence[str],
) -> tuple[
    list[dict[str, str]],
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
]:
    rows: list[dict[str, str]] = []
    ids: list[str] = []
    invalid_states: list[str] = []
    partial_not_allowed: list[str] = []
    partial_sections: list[str] = []
    expected_order = {
        str(section_id).strip().upper(): index
        for index, section_id in enumerate(expected_section_ids)
    }

    def sort_key(section_id: str) -> tuple[int, int | str]:
        if section_id in expected_order:
            return (0, expected_order[section_id])
        return (1, section_id)

    for row in section_manifest:
        section_id = str(row.get("section_id") or "").strip().upper()
        state = str(row.get("status") or "").strip().upper()
        ids.append(section_id)
        rows.append({"section_id": section_id, "status": state})
        if not section_id:
            invalid_states.append("<missing>:SECTION_ID_MISSING")
        if state not in _VALID_SECTION_STATES:
            invalid_states.append(f"{section_id or '<missing>'}:{state or '<empty>'}")
        if state == "PARTIAL":
            partial_sections.append(section_id)
            if section_id not in PARTIAL_ALLOWED_SECTIONS:
                partial_not_allowed.append(section_id)

    counts = Counter(ids)
    duplicates = sorted(
        (section_id for section_id, count in counts.items() if section_id and count > 1),
        key=sort_key,
    )
    present = set(ids)
    missing = [
        section_id
        for section_id in expected_section_ids
        if section_id not in present
    ]
    canonical_rows = sorted(rows, key=lambda row: sort_key(row["section_id"]))
    canonical_ids = [row["section_id"] for row in canonical_rows if row["section_id"]]
    return (
        canonical_rows,
        canonical_ids,
        missing,
        duplicates,
        sorted(partial_sections, key=sort_key),
        sorted(partial_not_allowed, key=sort_key),
        invalid_states,
    )


def _compute_handoff_failures(compute_contract: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if not (
        compute_contract.get("status") == "PASS"
        and compute_contract.get("compute_ready") is True
        and compute_contract.get("next_action") == "PRE_RENDER_QA"
        and compute_contract.get("delivery_ready") is False
        and compute_contract.get("legacy_fallback_allowed") is False
    ):
        failures.append("COMPUTE_CONTRACT_NOT_READY")

    fingerprint = compute_contract.get("compute_fingerprint")
    if not _is_sha256(fingerprint):
        failures.append("COMPUTE_FINGERPRINT_INVALID")

    for label, target in _FULL_COUNT_TARGETS.items():
        row = compute_contract.get(label)
        if not isinstance(row, Mapping) or row.get("status") != "PASS":
            failures.append(f"COMPUTE_CHECK_FAILED={label}")
            continue
        if row.get("total") != target:
            failures.append(f"COMPUTE_COUNT_MISMATCH={label}:{row.get('total')}!={target}")

    fact_model = compute_contract.get("FACT_MODEL")
    if not isinstance(fact_model, Mapping) or fact_model.get("status") != "PASS":
        failures.append("FACT_MODEL_CONTRACT_FAILED")
    elif fact_model.get("overlap"):
        failures.append("FACT_MODEL_CONTRACT_OVERLAP")
    return failures


def _normalize_weather_contract(
    *,
    report_mode: str | None,
    weather_contract_state: str | None,
    weather_required: bool,
    weather_direct_chat_present: bool,
) -> tuple[str, str, bool, bool, str | None]:
    """Resolve new mode-aware weather semantics while preserving legacy callers."""
    explicit_mode = report_mode is not None or weather_contract_state is not None
    if not explicit_mode:
        mode = "LEGACY"
        if weather_direct_chat_present:
            state = "DIRECT_CHATGPT"
            valid = True
        elif not weather_required:
            state = "NOT_REQUIRED"
            valid = True
        else:
            state = "MISSING"
            valid = False
        failure = None if valid else "MANDATORY_WEATHER_MISSING"
        return mode, state, bool(weather_required), bool(weather_direct_chat_present), failure

    mode = str(report_mode or "").strip().upper()
    state = str(weather_contract_state or "MISSING").strip().upper() or "MISSING"
    allowed = _WEATHER_STATES_BY_MODE.get(mode)
    valid = bool(allowed and state in allowed)
    failure = None if valid else f"WEATHER_CONTRACT_INVALID={mode or '<empty>'}:{state}"
    direct_present = state in {"DIRECT_CHATGPT", "MATCH_CURRENT"}
    return mode, state, True, direct_present, failure


def _render_contract_token(
    *,
    compute_fingerprint: str,
    canonical_manifest: Sequence[Mapping[str, str]],
    mini_league_denominator_complete: bool,
    mini_league_contract_state: str,
    report_mode: str,
    weather_contract_state: str,
    weather_required: bool,
    weather_direct_chat_present: bool,
    expected_counts: Mapping[str, int],
    expected_fact_keys: Sequence[str],
    expected_model_keys: Sequence[str],
    expected_inference_keys: Sequence[str],
    required_visible_markers: Sequence[str],
) -> str:
    payload = {
        "compute_fingerprint": compute_fingerprint,
        "section_manifest": list(canonical_manifest),
        "mini_league_denominator_complete": bool(mini_league_denominator_complete),
        "mini_league_contract_state": mini_league_contract_state,
        "report_mode": report_mode,
        "weather_contract_state": weather_contract_state,
        "weather_required": bool(weather_required),
        "weather_direct_chat_present": bool(weather_direct_chat_present),
        "expected_counts": dict(expected_counts),
        "expected_fact_keys": list(expected_fact_keys),
        "expected_model_keys": list(expected_model_keys),
        "expected_inference_keys": list(expected_inference_keys),
        "required_visible_markers": list(required_visible_markers),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def validate_pre_render_qa(
    *,
    compute_contract: Mapping[str, Any],
    section_manifest: Sequence[Mapping[str, Any]],
    mini_league_denominator_complete: bool,
    weather_required: bool = True,
    weather_direct_chat_present: bool = False,
    report_mode: str | None = None,
    weather_contract_state: str | None = None,
) -> dict[str, Any]:
    """Fail closed before rendering and mint an immutable render handoff token."""
    compute_failures = _compute_handoff_failures(compute_contract)
    generated_section_ids = [
        str(row.get("section_id") or "").strip().upper()
        for row in section_manifest
        if str(row.get("section_id") or "").strip()
    ]

    (
        resolved_report_mode,
        resolved_weather_state,
        resolved_weather_required,
        resolved_weather_direct_present,
        weather_failure,
    ) = _normalize_weather_contract(
        report_mode=report_mode,
        weather_contract_state=weather_contract_state,
        weather_required=weather_required,
        weather_direct_chat_present=weather_direct_chat_present,
    )
    expected_section_ids = _expected_visible_catalog(
        resolved_report_mode,
        generated_section_ids,
    )
    (
        canonical_manifest,
        canonical_section_ids,
        missing_sections,
        duplicate_sections,
        partial_sections,
        partial_not_allowed_sections,
        invalid_section_states,
    ) = _canonical_section_manifest(
        section_manifest,
        expected_section_ids=expected_section_ids,
    )

    s14b_state = next(
        (
            str(row.get("status") or "").strip().upper()
            for row in canonical_manifest
            if str(row.get("section_id") or "").strip().upper() == "S14B"
        ),
        "MISSING",
    )
    if mini_league_denominator_complete:
        mini_league_contract_state = "COMPLETE"
    elif s14b_state == "PARTIAL":
        mini_league_contract_state = "DEGRADED"
    else:
        mini_league_contract_state = "INCOMPLETE"

    failures = list(compute_failures)
    if generated_section_ids != expected_section_ids:
        failures.append("VISIBLE_CATALOG_MISMATCH")
    if canonical_section_ids != expected_section_ids and not missing_sections and not duplicate_sections:
        failures.append("CANONICAL_CATALOG_MISMATCH")
    if missing_sections:
        failures.append(f"MANDATORY_SECTIONS_MISSING={','.join(missing_sections)}")
    if duplicate_sections:
        failures.append(f"SECTION_IDENTITY_DUPLICATE={','.join(duplicate_sections)}")
    if partial_not_allowed_sections:
        failures.append(f"PARTIAL_NOT_ALLOWED={','.join(partial_not_allowed_sections)}")
    if invalid_section_states:
        failures.append(f"SECTION_STATUS_INVALID={','.join(invalid_section_states)}")
    if mini_league_contract_state == "INCOMPLETE":
        failures.append("MINI_LEAGUE_DENOMINATOR_INCOMPLETE")
    if weather_failure:
        failures.append(weather_failure)

    fact_model = compute_contract.get("FACT_MODEL")
    expected_fact_keys = (
        sorted(str(key) for key in fact_model.get("fact_keys", []))
        if isinstance(fact_model, Mapping)
        else []
    )
    expected_model_keys = (
        sorted(str(key) for key in fact_model.get("model_keys", []))
        if isinstance(fact_model, Mapping)
        else []
    )
    expected_inference_keys = (
        sorted(str(key) for key in fact_model.get("inference_keys", []))
        if isinstance(fact_model, Mapping)
        else []
    )
    expected_counts = _expected_visible_counts(resolved_report_mode)
    required_visible_markers = _required_visible_markers(resolved_report_mode)
    compute_fingerprint = str(compute_contract.get("compute_fingerprint") or "")

    qa_passed = not failures
    token = (
        _render_contract_token(
            compute_fingerprint=compute_fingerprint,
            canonical_manifest=canonical_manifest,
            mini_league_denominator_complete=bool(mini_league_denominator_complete),
            mini_league_contract_state=mini_league_contract_state,
            report_mode=resolved_report_mode,
            weather_contract_state=resolved_weather_state,
            weather_required=resolved_weather_required,
            weather_direct_chat_present=resolved_weather_direct_present,
            expected_counts=expected_counts,
            expected_fact_keys=expected_fact_keys,
            expected_model_keys=expected_model_keys,
            expected_inference_keys=expected_inference_keys,
            required_visible_markers=required_visible_markers,
        )
        if qa_passed
        else None
    )
    next_action = (
        "RECOMPUTE"
        if compute_failures
        else "RENDER_REPORT" if qa_passed else "PRE_RENDER_RECOVERY"
    )

    return {
        "status": "PASS" if qa_passed else "FAIL",
        "qa_stage": "PRE_RENDER",
        "qa_passed": qa_passed,
        "render_allowed": qa_passed,
        "post_render_required": qa_passed,
        "delivery_ready": False,
        "report_state": "BUILDING" if qa_passed else "QA_FAILED",
        "next_action": next_action,
        "legacy_fallback_allowed": False,
        "failures": failures,
        "compute_fingerprint": compute_fingerprint,
        "render_contract_token": token,
        "required_section_count": len(expected_section_ids),
        "manifest_section_count": len(section_manifest),
        "expected_section_ids": expected_section_ids,
        "generated_section_ids": generated_section_ids,
        "section_manifest": canonical_manifest,
        "missing_sections": missing_sections,
        "duplicate_sections": duplicate_sections,
        "partial_sections": partial_sections,
        "partial_not_allowed_sections": partial_not_allowed_sections,
        "invalid_section_states": invalid_section_states,
        "mini_league_denominator_complete": bool(mini_league_denominator_complete),
        "mini_league_contract_state": mini_league_contract_state,
        "report_mode": resolved_report_mode,
        "weather_contract_state": resolved_weather_state,
        "weather_required": resolved_weather_required,
        "weather_direct_chat_present": resolved_weather_direct_present,
        "expected_counts": expected_counts,
        "expected_fact_keys": expected_fact_keys,
        "expected_model_keys": expected_model_keys,
        "expected_inference_keys": expected_inference_keys,
        "required_visible_markers": required_visible_markers,
    }


def validate_post_render_qa(
    *,
    pre_render_qa: Mapping[str, Any],
    rendered_body: str,
    rendered_section_ids: Sequence[str],
    rendered_section_states: Mapping[str, str],
    rendered_compute_fingerprint: str | None,
    render_contract_token: str | None,
    rendered_counts: Mapping[str, int],
    rendered_fact_keys: Sequence[str],
    rendered_model_keys: Sequence[str],
    rendered_mini_league_denominator_complete: bool,
    rendered_weather_direct_chat_present: bool = False,
    rendered_weather_contract_state: str | None = None,
    truncated: bool,
) -> dict[str, Any]:
    """Verify both the actual visible body and renderer metadata against pre-render QA."""
    if not (
        pre_render_qa.get("status") == "PASS"
        and pre_render_qa.get("qa_stage") == "PRE_RENDER"
        and pre_render_qa.get("qa_passed") is True
        and pre_render_qa.get("render_allowed") is True
        and pre_render_qa.get("delivery_ready") is False
    ):
        return {
            "status": "BLOCKED",
            "qa_stage": "POST_RENDER",
            "qa_passed": False,
            "delivery_ready": False,
            "report_state": "QA_FAILED",
            "next_action": "PRE_RENDER_QA",
            "legacy_fallback_allowed": False,
            "failures": ["PRE_RENDER_QA_NOT_PASSED"],
            "visible_body_validated": False,
        }

    expected_sections = list(pre_render_qa.get("expected_section_ids", []))
    rendered_sections = [str(section_id or "").strip().upper() for section_id in rendered_section_ids]
    rendered_counts_by_id = Counter(rendered_sections)
    duplicate_sections = sorted(
        (section_id for section_id, count in rendered_counts_by_id.items() if section_id and count > 1),
        key=_section_sort_key,
    )
    rendered_set = set(rendered_sections)
    expected_set = set(expected_sections)
    missing_sections = sorted(expected_set - rendered_set, key=_section_sort_key)
    unexpected_sections = sorted(rendered_set - expected_set, key=_section_sort_key)

    expected_section_states = {
        str(row.get("section_id") or "").strip().upper(): str(row.get("status") or "").strip().upper()
        for row in pre_render_qa.get("section_manifest", [])
        if str(row.get("section_id") or "").strip()
    }
    actual_section_states = {
        str(section_id or "").strip().upper(): str(status or "").strip().upper()
        for section_id, status in rendered_section_states.items()
    }
    unexpected_state_sections = sorted(set(actual_section_states) - expected_set, key=_section_sort_key)

    expected_compute_fingerprint = str(pre_render_qa.get("compute_fingerprint") or "")
    expected_counts = dict(pre_render_qa.get("expected_counts", {}))
    expected_fact_keys = sorted(str(key) for key in pre_render_qa.get("expected_fact_keys", []))
    expected_model_keys = sorted(str(key) for key in pre_render_qa.get("expected_model_keys", []))
    expected_inference_keys = sorted(str(key) for key in pre_render_qa.get("expected_inference_keys", []))
    required_visible_markers = [
        str(marker)
        for marker in pre_render_qa.get("required_visible_markers", [])
        if str(marker).strip()
    ]
    expected_report_mode = str(pre_render_qa.get("report_mode") or "LEGACY").strip().upper()
    expected_mini_league_state = str(
        pre_render_qa.get("mini_league_contract_state")
        or ("COMPLETE" if pre_render_qa.get("mini_league_denominator_complete") else "INCOMPLETE")
    ).strip().upper()
    expected_weather_state = str(
        pre_render_qa.get("weather_contract_state")
        or ("DIRECT_CHATGPT" if pre_render_qa.get("weather_direct_chat_present") else "MISSING")
    ).strip().upper()
    expected_weather_required = bool(pre_render_qa.get("weather_required", True))
    expected_weather_present = bool(pre_render_qa.get("weather_direct_chat_present", False))

    canonical_pre_manifest = [
        {
            "section_id": str(row.get("section_id") or "").strip().upper(),
            "status": str(row.get("status") or "").strip().upper(),
        }
        for row in pre_render_qa.get("section_manifest", [])
    ]
    recomputed_pre_token = _render_contract_token(
        compute_fingerprint=expected_compute_fingerprint,
        canonical_manifest=canonical_pre_manifest,
        mini_league_denominator_complete=bool(pre_render_qa.get("mini_league_denominator_complete")),
        mini_league_contract_state=expected_mini_league_state,
        report_mode=expected_report_mode,
        weather_contract_state=expected_weather_state,
        weather_required=expected_weather_required,
        weather_direct_chat_present=expected_weather_present,
        expected_counts=expected_counts,
        expected_fact_keys=expected_fact_keys,
        expected_model_keys=expected_model_keys,
        expected_inference_keys=expected_inference_keys,
        required_visible_markers=required_visible_markers,
    )
    stored_pre_token = pre_render_qa.get("render_contract_token")

    if rendered_weather_contract_state is not None:
        actual_weather_state = str(rendered_weather_contract_state or "MISSING").strip().upper() or "MISSING"
    elif expected_report_mode == "LEGACY":
        if rendered_weather_direct_chat_present:
            actual_weather_state = "DIRECT_CHATGPT"
        elif not expected_weather_required:
            actual_weather_state = "NOT_REQUIRED"
        else:
            actual_weather_state = "MISSING"
    else:
        actual_weather_state = "DIRECT_CHATGPT" if rendered_weather_direct_chat_present else "MISSING"

    visible_body = validate_visible_report_body(
        rendered_body=rendered_body,
        expected_section_ids=expected_sections,
        expected_counts=expected_counts,
        expected_fact_keys=expected_fact_keys,
        expected_model_keys=expected_model_keys,
        expected_inference_keys=expected_inference_keys,
        expected_weather_state=expected_weather_state,
        mini_league_denominator_complete_required=expected_mini_league_state == "COMPLETE",
        expected_mini_league_state=expected_mini_league_state,
        required_visible_markers=required_visible_markers,
    )

    failures: list[str] = list(visible_body["failures"])
    if stored_pre_token != recomputed_pre_token:
        failures.append("PRE_RENDER_CONTRACT_TOKEN_INVALID")
    if truncated:
        failures.append("RENDER_TRUNCATED")
    if missing_sections:
        failures.append(f"RENDER_SECTIONS_MISSING={','.join(missing_sections)}")
    if duplicate_sections:
        failures.append(f"RENDER_SECTION_DUPLICATE={','.join(duplicate_sections)}")
    if unexpected_sections:
        failures.append(f"RENDER_SECTION_UNEXPECTED={','.join(unexpected_sections)}")
    if rendered_sections != expected_sections:
        failures.append("SECTION_SEQUENCE_MISMATCH")

    for section_id in expected_sections:
        expected_state = expected_section_states.get(section_id, "<missing>")
        actual_state = actual_section_states.get(section_id, "<missing>")
        if actual_state != expected_state:
            failures.append(f"SECTION_STATUS_MISMATCH={section_id}:{actual_state}!={expected_state}")
    if unexpected_state_sections:
        failures.append(f"SECTION_STATUS_UNEXPECTED={','.join(unexpected_state_sections)}")

    if rendered_compute_fingerprint != expected_compute_fingerprint:
        failures.append("COMPUTE_FINGERPRINT_MISMATCH")
    if render_contract_token != recomputed_pre_token:
        failures.append("RENDER_CONTRACT_TOKEN_MISMATCH")

    for label, target in expected_counts.items():
        actual = rendered_counts.get(label)
        if actual != target:
            failures.append(f"COUNT_MISMATCH={label}:{actual}!={target}")

    actual_fact_keys = sorted(str(key) for key in rendered_fact_keys)
    actual_model_keys = sorted(str(key) for key in rendered_model_keys)
    if set(actual_fact_keys) & set(actual_model_keys):
        failures.append("FACT_MODEL_BLEED")
    if actual_fact_keys != expected_fact_keys:
        failures.append("FACT_KEYS_MISMATCH")
    if actual_model_keys != expected_model_keys:
        failures.append("MODEL_KEYS_MISMATCH")

    expected_mini_complete = expected_mini_league_state == "COMPLETE"
    if bool(rendered_mini_league_denominator_complete) != expected_mini_complete:
        failures.append(
            "MINI_LEAGUE_METADATA_STATE_MISMATCH="
            f"{bool(rendered_mini_league_denominator_complete)}!={expected_mini_complete}"
        )
    if actual_weather_state != expected_weather_state:
        if (
            expected_report_mode == "LEGACY"
            and expected_weather_required
            and actual_weather_state == "MISSING"
        ):
            failures.append("MANDATORY_WEATHER_MISSING")
        else:
            failures.append(
                f"WEATHER_CONTRACT_STATE_MISMATCH={actual_weather_state}!={expected_weather_state}"
            )

    qa_passed = not failures
    return {
        "status": "PASS" if qa_passed else "FAIL",
        "qa_stage": "POST_RENDER",
        "qa_passed": qa_passed,
        "delivery_ready": False,
        "report_state": "BUILDING" if qa_passed else "QA_FAILED",
        "next_action": "BUILD_DELIVERY_PROOF" if qa_passed else "RENDER_RECOVERY",
        "legacy_fallback_allowed": False,
        "failures": failures,
        "compute_fingerprint": expected_compute_fingerprint,
        "render_contract_token": recomputed_pre_token,
        "expected_section_ids": expected_sections,
        "rendered_section_ids": rendered_sections,
        "expected_section_states": expected_section_states,
        "rendered_section_states": actual_section_states,
        "missing_sections": missing_sections,
        "duplicate_sections": duplicate_sections,
        "unexpected_sections": unexpected_sections,
        "unexpected_state_sections": unexpected_state_sections,
        "expected_counts": expected_counts,
        "rendered_counts": dict(rendered_counts),
        "expected_fact_keys": expected_fact_keys,
        "expected_model_keys": expected_model_keys,
        "expected_inference_keys": expected_inference_keys,
        "required_visible_markers": required_visible_markers,
        "rendered_fact_keys": actual_fact_keys,
        "rendered_model_keys": actual_model_keys,
        "mini_league_denominator_complete": bool(rendered_mini_league_denominator_complete),
        "mini_league_contract_state": expected_mini_league_state,
        "report_mode": expected_report_mode,
        "weather_contract_state": actual_weather_state,
        "weather_required": expected_weather_required,
        "weather_direct_chat_present": actual_weather_state in {"DIRECT_CHATGPT", "MATCH_CURRENT"},
        "truncated": bool(truncated),
        "visible_body_validated": visible_body["status"] == "PASS",
        "visible_body_sha256": visible_body["body_sha256"],
        "visible_section_ids": visible_body["section_ids"],
        "visible_counts": visible_body["counts"],
        "visible_fact_keys": visible_body["fact_keys"],
        "visible_model_keys": visible_body["model_keys"],
        "visible_inference_keys": visible_body["inference_keys"],
        "visible_weather_contract_state": visible_body["weather_contract_state"],
        "visible_mini_league_denominator_complete": visible_body[
            "mini_league_denominator_complete"
        ],
        "visible_mini_league_contract_state": visible_body["mini_league_contract_state"],
    }


# P0.5 strict Deadline/Final report-plane gates. These wrappers deliberately reuse
# the existing R6 validators above rather than creating a second QA implementation.
_P05_CONTRACT_VERSION = "P0.5"


def _p05_timestamp(value: Any, *, label: str):
    from .temporal import try_parse_timestamp
    parsed = try_parse_timestamp(value)
    if parsed is None:
        raise ValueError(f"{label} must be timezone-aware ISO-8601")
    return parsed


def _p05_gate_token(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _p05_weather_evidence(
    weather_evidence: Mapping[str, Any],
) -> tuple[bool, str, list[str], dict[str, Any]]:
    evidence = dict(weather_evidence or {})
    attempted = evidence.get("weather_attempted") is True
    result = str(evidence.get("weather_result") or "").strip().upper()
    source = str(evidence.get("source") or "").strip()
    provenance = evidence.get("provenance")
    evaluated_at = evidence.get("evaluated_at")
    failures: list[str] = []
    if not attempted:
        failures.append("WEATHER_NOT_ATTEMPTED")
    if result not in {"AVAILABLE", "DEGRADED_AFTER_ATTEMPT"}:
        failures.append("WEATHER_RESULT_INVALID")
    if not source:
        failures.append("WEATHER_SOURCE_MISSING")
    if provenance in (None, "", {}, []):
        failures.append("WEATHER_PROVENANCE_MISSING")
    try:
        _p05_timestamp(evaluated_at, label="weather.evaluated_at")
    except ValueError:
        failures.append("WEATHER_EVALUATED_AT_INVALID")
    state = "DIRECT_CHATGPT" if result == "AVAILABLE" else "SOURCE_DEGRADED"
    return not failures, state, failures, {
        "weather_attempted": attempted,
        "weather_result": result or None,
        "source": source or None,
        "provenance": provenance,
        "evaluated_at": evaluated_at,
    }


def validate_p05_pre_render_qa(
    *,
    report_slot_id: str,
    evaluated_at: str,
    compute_contract: Mapping[str, Any],
    section_manifest: Sequence[Mapping[str, Any]],
    mini_league_denominator_complete: bool,
    report_mode: str,
    decision_context: Mapping[str, Any],
    prefetch_readiness: Mapping[str, Any],
    weather_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Strict P0.5 PRE_RENDER_QA for canonical Deadline/Final report occurrences."""
    slot_id = str(report_slot_id or "").strip()
    failures: list[str] = []
    try:
        evaluated = _p05_timestamp(evaluated_at, label="evaluated_at")
    except ValueError:
        evaluated = None
        failures.append("EVALUATED_AT_INVALID")
    if not slot_id or "|" not in slot_id:
        failures.append("REPORT_SLOT_ID_INVALID")

    context = dict(decision_context or {})
    context_pass = bool(
        context.get("status") == "PASS"
        and context.get("context_kind") == "CURRENT_DECISION_CONTEXT"
        and context.get("report_slot_id") == slot_id
        and context.get("context_fingerprint")
    )
    if not context_pass:
        failures.append("DECISION_CONTEXT_GATE_FAILED")

    prefetch = dict(prefetch_readiness or {})
    prefetch_identity_pass = bool(
        prefetch.get("ready") is True
        and prefetch.get("report_kind_match") is True
        and prefetch.get("target_logical_slot_match") is True
        and prefetch.get("scope_match") is True
        and str(prefetch.get("selected_report_prefetch_run_id") or "").strip()
    )
    if not prefetch_identity_pass:
        failures.append("PREFETCH_IDENTITY_GATE_FAILED")

    weather_pass, weather_state, weather_failures, normalized_weather = _p05_weather_evidence(
        weather_evidence
    )
    failures.extend(weather_failures)

    base = validate_pre_render_qa(
        compute_contract=compute_contract,
        section_manifest=section_manifest,
        mini_league_denominator_complete=mini_league_denominator_complete,
        weather_required=True,
        weather_direct_chat_present=weather_state == "DIRECT_CHATGPT",
        report_mode=report_mode,
        weather_contract_state=weather_state,
    )
    failures.extend(
        failure for failure in base.get("failures", []) if failure not in failures
    )

    mandatory_scope_pass = bool(
        compute_contract.get("status") == "PASS"
        and compute_contract.get("compute_ready") is True
        and not base.get("missing_sections")
        and not base.get("duplicate_sections")
    )
    input_completeness_pass = bool(
        mandatory_scope_pass
        and all(
            isinstance(compute_contract.get(label), Mapping)
            and compute_contract[label].get("status") == "PASS"
            for label in ("OUR15", "XI", "BENCH", "WATCHLIST20", "RISE20", "FALL20")
        )
    )
    if not mandatory_scope_pass:
        failures.append("MANDATORY_SCOPE_GATE_FAILED")
    if not input_completeness_pass:
        failures.append("INPUT_COMPLETENESS_GATE_FAILED")
    failures = list(dict.fromkeys(failures))
    qa_passed = bool(base.get("status") == "PASS" and not failures)

    gate_payload = {
        "contract_version": _P05_CONTRACT_VERSION,
        "report_slot_id": slot_id,
        "evaluated_at": evaluated_at,
        "base_render_contract_token": base.get("render_contract_token"),
        "decision_context_fingerprint": context.get("context_fingerprint"),
        "active_scenario_ids": list(context.get("active_scenario_ids") or []),
        "prefetch_identity": prefetch.get("selected_report_prefetch_run_id"),
        "prefetch_slot": prefetch.get("selected_target_logical_report_slot"),
        "weather_attempt": normalized_weather,
        "mandatory_scope_gate_pass": mandatory_scope_pass,
        "input_completeness_pass": input_completeness_pass,
    }
    strict_token = _p05_gate_token(gate_payload) if qa_passed else None

    return {
        **base,
        "status": "PASS" if qa_passed else "FAIL",
        "qa_stage": "PRE_RENDER",
        "qa_passed": qa_passed,
        "render_allowed": qa_passed,
        "can_render": qa_passed,
        "can_emit": False,
        "report_contract_pass": False,
        "report_slot_id": slot_id,
        "evaluated_at": evaluated_at,
        "contract_version": _P05_CONTRACT_VERSION,
        "mandatory_scope_gate": {"status": "PASS" if mandatory_scope_pass else "FAIL"},
        "input_completeness": {"status": "PASS" if input_completeness_pass else "FAIL"},
        "decision_context": context,
        "prefetch_identity": {
            "status": "PASS" if prefetch_identity_pass else "FAIL",
            "report_prefetch_run_id": prefetch.get("selected_report_prefetch_run_id"),
            "logical_slot": prefetch.get("selected_target_logical_report_slot"),
        },
        "weather_attempt": normalized_weather,
        "failed_checks": failures,
        "failures": failures,
        "warnings": [],
        "evidence": {
            "compute_fingerprint": base.get("compute_fingerprint"),
            "render_contract_token": base.get("render_contract_token"),
            "decision_context_fingerprint": context.get("context_fingerprint"),
            "prefetch_refresh_identity": prefetch.get("refresh_identity"),
        },
        "p05_gate_payload": gate_payload,
        "p05_render_gate_token": strict_token,
        "strict_report_plane_contract": True,
        "next_action": "RENDER_REPORT" if qa_passed else "PRE_RENDER_RECOVERY",
    }


def validate_p05_post_render_qa(
    *,
    pre_render_qa: Mapping[str, Any],
    report_slot_id: str,
    evaluated_at: str,
    render_completed_at: str,
    rendered_report_mode: str,
    rendered_body: str,
    rendered_section_ids: Sequence[str],
    rendered_section_states: Mapping[str, str],
    rendered_compute_fingerprint: str | None,
    render_contract_token: str | None,
    rendered_counts: Mapping[str, int],
    rendered_fact_keys: Sequence[str],
    rendered_model_keys: Sequence[str],
    rendered_mini_league_denominator_complete: bool,
    rendered_weather_direct_chat_present: bool = False,
    rendered_weather_contract_state: str | None = None,
    truncated: bool = False,
    status_only: bool = False,
) -> dict[str, Any]:
    """Strict P0.5 POST_RENDER_QA and the sole CAN_EMIT gate."""
    base = validate_post_render_qa(
        pre_render_qa=pre_render_qa,
        rendered_body=rendered_body,
        rendered_section_ids=rendered_section_ids,
        rendered_section_states=rendered_section_states,
        rendered_compute_fingerprint=rendered_compute_fingerprint,
        render_contract_token=render_contract_token,
        rendered_counts=rendered_counts,
        rendered_fact_keys=rendered_fact_keys,
        rendered_model_keys=rendered_model_keys,
        rendered_mini_league_denominator_complete=rendered_mini_league_denominator_complete,
        rendered_weather_direct_chat_present=rendered_weather_direct_chat_present,
        rendered_weather_contract_state=rendered_weather_contract_state,
        truncated=truncated,
    )
    failures = list(base.get("failures", []))
    expected_slot = str(pre_render_qa.get("report_slot_id") or "").strip()
    if str(report_slot_id or "").strip() != expected_slot:
        failures.append("REPORT_SLOT_ID_MISMATCH")
    expected_mode = str(pre_render_qa.get("report_mode") or "").strip().upper()
    if str(rendered_report_mode or "").strip().upper() != expected_mode:
        failures.append("REPORT_KIND_MISMATCH")
    if status_only:
        failures.append("STATUS_ONLY_NOT_CANONICAL_REPORT")

    stored_payload = pre_render_qa.get("p05_gate_payload")
    stored_token = pre_render_qa.get("p05_render_gate_token")
    if not isinstance(stored_payload, Mapping) or not stored_token:
        failures.append("P05_PRE_RENDER_GATE_MISSING")
    elif _p05_gate_token(stored_payload) != stored_token:
        failures.append("P05_PRE_RENDER_GATE_TAMPERED")

    context = pre_render_qa.get("decision_context")
    active_scenarios = (
        list(context.get("active_scenarios") or [])
        if isinstance(context, Mapping)
        else []
    )
    body_lower = str(rendered_body or "").lower()
    missing_active: list[str] = []
    invalid_active: list[str] = []
    for row in active_scenarios:
        if str(row.get("state") or "").strip().upper() != "CONTEMPLATED":
            invalid_active.append(str(row.get("scenario_id") or "<missing>"))
            continue
        marker = str(row.get("visible_marker") or row.get("scenario_id") or "").strip()
        if not marker or marker.lower() not in body_lower:
            missing_active.append(str(row.get("scenario_id") or marker or "<missing>"))
    if invalid_active:
        failures.append(f"ACTIVE_SCENARIO_STATE_INVALID={','.join(invalid_active)}")
    if missing_active:
        failures.append(f"ACTIVE_SCENARIOS_MISSING={','.join(missing_active)}")

    try:
        pre_time = _p05_timestamp(pre_render_qa.get("evaluated_at"), label="pre_render.evaluated_at")
        render_time = _p05_timestamp(render_completed_at, label="render_completed_at")
        post_time = _p05_timestamp(evaluated_at, label="evaluated_at")
        if not (pre_time <= render_time <= post_time):
            failures.append("RENDER_QA_CHRONOLOGY_INVALID")
    except ValueError:
        failures.append("RENDER_QA_TIMESTAMP_INVALID")

    failures = list(dict.fromkeys(failures))
    passed = bool(base.get("status") == "PASS" and not failures)
    return {
        **base,
        "status": "PASS" if passed else "FAIL",
        "qa_stage": "POST_RENDER",
        "qa_passed": passed,
        "report_slot_id": expected_slot,
        "evaluated_at": evaluated_at,
        "render_completed_at": render_completed_at,
        "contract_version": _P05_CONTRACT_VERSION,
        "failed_checks": failures,
        "failures": failures,
        "warnings": [],
        "provenance": {
            "compute_fingerprint": pre_render_qa.get("compute_fingerprint"),
            "render_contract_token": pre_render_qa.get("render_contract_token"),
            "p05_render_gate_token": stored_token,
        },
        "mandatory_scope_gate_pass": pre_render_qa.get("mandatory_scope_gate", {}).get("status") == "PASS",
        "input_completeness_pass": pre_render_qa.get("input_completeness", {}).get("status") == "PASS",
        "decision_context_gate_pass": pre_render_qa.get("decision_context", {}).get("status") == "PASS",
        "prefetch_identity_pass": pre_render_qa.get("prefetch_identity", {}).get("status") == "PASS",
        "weather_attempt_gate_pass": pre_render_qa.get("weather_attempt", {}).get("weather_attempted") is True,
        "pre_render_qa_pass": pre_render_qa.get("status") == "PASS",
        "post_render_qa_pass": passed,
        "report_contract_pass": passed,
        "can_emit": passed and not status_only,
        "visible_emitted": False,
        "status_only": bool(status_only),
        "active_scenario_ids_expected": list(
            pre_render_qa.get("decision_context", {}).get("active_scenario_ids") or []
        ),
        "active_scenario_ids_missing": missing_active,
        "next_action": "BUILD_DELIVERY_PROOF" if passed else "RENDER_RECOVERY",
    }
