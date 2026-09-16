from __future__ import annotations

"""Wave 10 read-only regression acceptance and production closeout gate.

The closeout layer does not acquire, mutate, render, publish, retry, or deliver
anything. It only evaluates explicit evidence produced by Waves 1-9 and fails
closed when the locked regression matrix, E2E evidence, or verification
provenance is incomplete.
"""

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping


REGRESSION_SCENARIO_IDS = tuple(f"R{index:02d}" for index in range(1, 17))

CLOSEOUT_EVIDENCE_KEYS = (
    "report_slot_id_exact",
    "data_slot_already_published_report_continues",
    "public_scopes_ready",
    "private_auth_degraded_non_blocking",
    "compute_pass",
    "pre_render_qa_pass",
    "post_render_qa_pass",
    "delivery_same_slot_receipt_pass",
    "report_observability_independent",
    "catch_up_inside_window_pass",
    "catch_up_expired_noop_pass",
    "ad_hoc_on_demand_e2e_pass",
    "legacy_fallback_forbidden",
)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _is_hex(value: Any, *, length: int) -> bool:
    text = str(value or "").strip()
    return len(text) == length and all(
        character in "0123456789abcdefABCDEF" for character in text
    )


def _is_aware_iso8601(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def evaluate_regression_acceptance(
    scenario_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Require the exact locked R01-R16 matrix and PASS from every scenario."""
    expected = set(REGRESSION_SCENARIO_IDS)
    supplied = {str(scenario_id).strip().upper() for scenario_id in scenario_results}
    missing = sorted(expected - supplied)
    unexpected = sorted(supplied - expected)

    canonical_results: dict[str, dict[str, Any]] = {}
    failed: list[str] = []
    passed_count = 0
    for scenario_id in REGRESSION_SCENARIO_IDS:
        row = scenario_results.get(scenario_id)
        if not isinstance(row, Mapping):
            canonical_results[scenario_id] = {"status": "MISSING"}
            continue
        status = str(row.get("status") or "").strip().upper()
        canonical_row = {"status": status or "UNKNOWN"}
        if "detail" in row:
            canonical_row["detail"] = row["detail"]
        canonical_results[scenario_id] = canonical_row
        if status == "PASS":
            passed_count += 1
        else:
            failed.append(scenario_id)

    failures = [*(f"MISSING={scenario_id}" for scenario_id in missing)]
    failures.extend(f"UNEXPECTED={scenario_id}" for scenario_id in unexpected)
    failures.extend(f"FAILED={scenario_id}" for scenario_id in failed)
    ready = not failures and passed_count == len(REGRESSION_SCENARIO_IDS)

    fingerprint = _fingerprint(
        {
            "scenario_ids": REGRESSION_SCENARIO_IDS,
            "results": canonical_results,
        }
    )
    failed_or_missing_count = len(
        {
            *missing,
            *failed,
        }
    )

    return {
        "status": "PASS" if ready else "FAIL",
        "regression_ready": ready,
        "scenario_count": len(REGRESSION_SCENARIO_IDS),
        "passed_count": passed_count,
        "failed_or_missing_count": failed_or_missing_count,
        "scenario_ids": list(REGRESSION_SCENARIO_IDS),
        "missing_scenarios": missing,
        "unexpected_scenarios": unexpected,
        "failed_scenarios": failed,
        "failures": failures,
        "scenario_results": canonical_results,
        "acceptance_fingerprint": fingerprint,
        "legacy_fallback_allowed": False,
    }


def evaluate_production_closeout(
    *,
    regression_acceptance: Mapping[str, Any],
    e2e_evidence: Mapping[str, Any],
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Close recovery only when regression, E2E facts, and provenance are proven."""
    failures: list[str] = []
    regression_ready = bool(
        regression_acceptance.get("status") == "PASS"
        and regression_acceptance.get("regression_ready") is True
        and regression_acceptance.get("scenario_ids") == list(REGRESSION_SCENARIO_IDS)
        and regression_acceptance.get("passed_count") == len(REGRESSION_SCENARIO_IDS)
        and regression_acceptance.get("failed_or_missing_count") == 0
        and regression_acceptance.get("legacy_fallback_allowed") is False
    )
    if not regression_ready:
        failures.append("REGRESSION_ACCEPTANCE_NOT_READY")

    required = set(CLOSEOUT_EVIDENCE_KEYS)
    supplied = {str(key) for key in e2e_evidence}
    missing = sorted(required - supplied)
    unexpected = sorted(supplied - required)
    failures.extend(f"EVIDENCE_MISSING={key}" for key in missing)
    failures.extend(f"EVIDENCE_UNEXPECTED={key}" for key in unexpected)

    canonical_evidence: dict[str, bool] = {}
    evidence_passed = 0
    for key in CLOSEOUT_EVIDENCE_KEYS:
        passed = e2e_evidence.get(key) is True
        canonical_evidence[key] = passed
        if passed:
            evidence_passed += 1
        elif key in supplied:
            failures.append(f"EVIDENCE_FAILED={key}")

    raw_provenance = provenance if isinstance(provenance, Mapping) else {}
    canonical_provenance = {
        "commit_sha": str(raw_provenance.get("commit_sha") or "").strip().lower(),
        "acceptance_fingerprint": str(
            raw_provenance.get("acceptance_fingerprint") or ""
        ).strip().lower(),
        "verified_at": str(raw_provenance.get("verified_at") or "").strip(),
    }
    if not _is_hex(canonical_provenance["commit_sha"], length=40):
        failures.append("PROVENANCE_COMMIT_SHA_INVALID")
    if not _is_hex(canonical_provenance["acceptance_fingerprint"], length=64):
        failures.append("PROVENANCE_ACCEPTANCE_FINGERPRINT_INVALID")
    elif canonical_provenance["acceptance_fingerprint"] != str(
        regression_acceptance.get("acceptance_fingerprint") or ""
    ).lower():
        failures.append("PROVENANCE_ACCEPTANCE_FINGERPRINT_MISMATCH")
    if not _is_aware_iso8601(canonical_provenance["verified_at"]):
        failures.append("PROVENANCE_VERIFIED_AT_INVALID")

    ready = not failures and evidence_passed == len(CLOSEOUT_EVIDENCE_KEYS)
    closeout_fingerprint = _fingerprint(
        {
            "regression_fingerprint": regression_acceptance.get("acceptance_fingerprint"),
            "e2e_evidence": canonical_evidence,
            "provenance": canonical_provenance,
        }
    )

    return {
        "status": "PASS" if ready else "FAIL",
        "closeout_ready": ready,
        "program_state": "RECOVERY_CLOSED" if ready else "RECOVERY_OPEN",
        "required_evidence_count": len(CLOSEOUT_EVIDENCE_KEYS),
        "e2e_evidence_passed": evidence_passed,
        "e2e_evidence": canonical_evidence,
        "provenance": canonical_provenance,
        "failures": failures,
        "regression_acceptance_fingerprint": regression_acceptance.get(
            "acceptance_fingerprint"
        ),
        "closeout_fingerprint": closeout_fingerprint,
        "legacy_fallback_allowed": False,
    }
