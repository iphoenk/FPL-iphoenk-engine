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


_COUNT_TARGETS = {
    "OUR15": 15,
    "XI": 11,
    "BENCH": 4,
    "WATCHLIST20": 20,
    "RISE20": 20,
    "FALL20": 20,
}
_VALID_SECTION_STATES = frozenset({"COMPLETE", "PARTIAL"})
_MANDATORY_ORDER = {section_id: index for index, section_id in enumerate(MANDATORY_SECTIONS)}


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _section_sort_key(section_id: str) -> tuple[int, int | str]:
    if section_id in _MANDATORY_ORDER:
        return (0, _MANDATORY_ORDER[section_id])
    return (1, section_id)


def _canonical_section_manifest(
    section_manifest: Sequence[Mapping[str, Any]],
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
        key=_section_sort_key,
    )
    present = set(ids)
    missing = [section_id for section_id in MANDATORY_SECTIONS if section_id not in present]
    canonical_rows = sorted(rows, key=lambda row: _section_sort_key(row["section_id"]))
    canonical_ids = [row["section_id"] for row in canonical_rows if row["section_id"]]
    return (
        canonical_rows,
        canonical_ids,
        missing,
        duplicates,
        sorted(partial_sections, key=_section_sort_key),
        sorted(partial_not_allowed, key=_section_sort_key),
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

    for label, target in _COUNT_TARGETS.items():
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


def _render_contract_token(
    *,
    compute_fingerprint: str,
    canonical_manifest: Sequence[Mapping[str, str]],
    mini_league_denominator_complete: bool,
    expected_counts: Mapping[str, int],
    expected_fact_keys: Sequence[str],
    expected_model_keys: Sequence[str],
) -> str:
    payload = {
        "compute_fingerprint": compute_fingerprint,
        "section_manifest": list(canonical_manifest),
        "mini_league_denominator_complete": bool(mini_league_denominator_complete),
        "expected_counts": dict(expected_counts),
        "expected_fact_keys": list(expected_fact_keys),
        "expected_model_keys": list(expected_model_keys),
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
) -> dict[str, Any]:
    """Fail closed before rendering and mint an immutable render handoff token."""
    compute_failures = _compute_handoff_failures(compute_contract)
    (
        canonical_manifest,
        expected_section_ids,
        missing_sections,
        duplicate_sections,
        partial_sections,
        partial_not_allowed_sections,
        invalid_section_states,
    ) = _canonical_section_manifest(section_manifest)

    failures = list(compute_failures)
    if missing_sections:
        failures.append(f"MANDATORY_SECTIONS_MISSING={','.join(missing_sections)}")
    if duplicate_sections:
        failures.append(f"SECTION_IDENTITY_DUPLICATE={','.join(duplicate_sections)}")
    if partial_not_allowed_sections:
        failures.append(
            f"PARTIAL_NOT_ALLOWED={','.join(partial_not_allowed_sections)}"
        )
    if invalid_section_states:
        failures.append(f"SECTION_STATUS_INVALID={','.join(invalid_section_states)}")
    if not mini_league_denominator_complete:
        failures.append("MINI_LEAGUE_DENOMINATOR_INCOMPLETE")

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
    expected_counts = dict(_COUNT_TARGETS)
    compute_fingerprint = str(compute_contract.get("compute_fingerprint") or "")

    qa_passed = not failures
    token = (
        _render_contract_token(
            compute_fingerprint=compute_fingerprint,
            canonical_manifest=canonical_manifest,
            mini_league_denominator_complete=True,
            expected_counts=expected_counts,
            expected_fact_keys=expected_fact_keys,
            expected_model_keys=expected_model_keys,
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
        "required_section_count": len(MANDATORY_SECTIONS),
        "manifest_section_count": len(section_manifest),
        "expected_section_ids": expected_section_ids,
        "section_manifest": canonical_manifest,
        "missing_sections": missing_sections,
        "duplicate_sections": duplicate_sections,
        "partial_sections": partial_sections,
        "partial_not_allowed_sections": partial_not_allowed_sections,
        "invalid_section_states": invalid_section_states,
        "mini_league_denominator_complete": bool(mini_league_denominator_complete),
        "expected_counts": expected_counts,
        "expected_fact_keys": expected_fact_keys,
        "expected_model_keys": expected_model_keys,
    }


def validate_post_render_qa(
    *,
    pre_render_qa: Mapping[str, Any],
    rendered_section_ids: Sequence[str],
    rendered_section_states: Mapping[str, str],
    rendered_compute_fingerprint: str | None,
    render_contract_token: str | None,
    rendered_counts: Mapping[str, int],
    rendered_fact_keys: Sequence[str],
    rendered_model_keys: Sequence[str],
    rendered_mini_league_denominator_complete: bool,
    truncated: bool,
) -> dict[str, Any]:
    """Verify rendered output still matches the approved pre-render handoff."""
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
        str(row.get("section_id") or "").strip().upper():
        str(row.get("status") or "").strip().upper()
        for row in pre_render_qa.get("section_manifest", [])
        if str(row.get("section_id") or "").strip()
    }
    actual_section_states = {
        str(section_id or "").strip().upper(): str(status or "").strip().upper()
        for section_id, status in rendered_section_states.items()
    }
    unexpected_state_sections = sorted(
        set(actual_section_states) - expected_set,
        key=_section_sort_key,
    )

    failures: list[str] = []
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
            failures.append(
                f"SECTION_STATUS_MISMATCH={section_id}:{actual_state}!={expected_state}"
            )
    if unexpected_state_sections:
        failures.append(
            f"SECTION_STATUS_UNEXPECTED={','.join(unexpected_state_sections)}"
        )

    expected_compute_fingerprint = str(pre_render_qa.get("compute_fingerprint") or "")
    if rendered_compute_fingerprint != expected_compute_fingerprint:
        failures.append("COMPUTE_FINGERPRINT_MISMATCH")
    expected_token = pre_render_qa.get("render_contract_token")
    if render_contract_token != expected_token:
        failures.append("RENDER_CONTRACT_TOKEN_MISMATCH")

    expected_counts = dict(pre_render_qa.get("expected_counts", {}))
    for label, target in expected_counts.items():
        actual = rendered_counts.get(label)
        if actual != target:
            failures.append(f"COUNT_MISMATCH={label}:{actual}!={target}")

    expected_fact_keys = sorted(str(key) for key in pre_render_qa.get("expected_fact_keys", []))
    expected_model_keys = sorted(str(key) for key in pre_render_qa.get("expected_model_keys", []))
    actual_fact_keys = sorted(str(key) for key in rendered_fact_keys)
    actual_model_keys = sorted(str(key) for key in rendered_model_keys)
    if set(actual_fact_keys) & set(actual_model_keys):
        failures.append("FACT_MODEL_BLEED")
    if actual_fact_keys != expected_fact_keys:
        failures.append("FACT_KEYS_MISMATCH")
    if actual_model_keys != expected_model_keys:
        failures.append("MODEL_KEYS_MISMATCH")

    if not rendered_mini_league_denominator_complete:
        failures.append("MINI_LEAGUE_DENOMINATOR_INCOMPLETE")

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
        "render_contract_token": expected_token,
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
        "rendered_fact_keys": actual_fact_keys,
        "rendered_model_keys": actual_model_keys,
        "mini_league_denominator_complete": bool(
            rendered_mini_league_denominator_complete
        ),
        "truncated": bool(truncated),
    }
