from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree


SCHEMA_VERSION = 1
EVIDENCE_SCOPE = "DETERMINISTIC_CI_READ_ONLY"
EXPECTED_SCENARIO_IDS = frozenset(
    {
        "provider_timeout",
        "provider_incomplete_amber",
        "auth_expired",
        "auth_not_requested",
        "stale_optional_cache",
        "registry_activation_transition",
        "identity_conflict",
        "duplicate_identity",
        "broken_stable_id_bridge",
        "malformed_candidate",
        "corrupt_candidate",
        "publisher_rejection",
        "duplicate_core_trigger",
        "duplicate_report_prefetch",
        "delayed_scheduler_execution",
        "last_good_recovery",
    }
)

# The Wave 3 runbook intentionally names some slash-separated failure modes.
# Keep them separate here so every mandatory condition has explicit evidence.
CANONICAL_SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "scenario_id": "provider_timeout",
        "runbook_scenario": "provider timeout",
        "testcase": "test_provider_timeout_can_degrade_acquisition_without_cancelling_due_report",
    },
    {
        "scenario_id": "provider_incomplete_amber",
        "runbook_scenario": "provider incomplete / AMBER",
        "testcase": "test_provider_incomplete_amber_is_local_when_core_integrity_remains_valid",
    },
    {
        "scenario_id": "auth_expired",
        "runbook_scenario": "auth expired",
        "testcase": "test_auth_expired_and_not_requested_are_distinct_chaos_states",
    },
    {
        "scenario_id": "auth_not_requested",
        "runbook_scenario": "auth not requested",
        "testcase": "test_auth_expired_and_not_requested_are_distinct_chaos_states",
    },
    {
        "scenario_id": "stale_optional_cache",
        "runbook_scenario": "stale optional cache",
        "testcase": "test_stale_optional_cache_does_not_override_fresh_core_delivery",
    },
    {
        "scenario_id": "registry_activation_transition",
        "runbook_scenario": "registry activation transition",
        "testcase": "test_registry_activation_transition_is_proven_by_fingerprint_not_inferred",
    },
    {
        "scenario_id": "identity_conflict",
        "runbook_scenario": "identity conflict",
        "testcase": "test_structural_identity_and_publisher_chaos_remain_fail_closed[identity_conflict]",
    },
    {
        "scenario_id": "duplicate_identity",
        "runbook_scenario": "duplicate identity",
        "testcase": "test_structural_identity_and_publisher_chaos_remain_fail_closed[duplicate_identity]",
    },
    {
        "scenario_id": "broken_stable_id_bridge",
        "runbook_scenario": "broken stable-ID bridge",
        "testcase": "test_structural_identity_and_publisher_chaos_remain_fail_closed[broken_stable_id_bridge]",
    },
    {
        "scenario_id": "malformed_candidate",
        "runbook_scenario": "malformed candidate",
        "testcase": "test_structural_identity_and_publisher_chaos_remain_fail_closed[malformed_candidate]",
    },
    {
        "scenario_id": "corrupt_candidate",
        "runbook_scenario": "corrupt candidate",
        "testcase": "test_structural_identity_and_publisher_chaos_remain_fail_closed[corrupt_candidate]",
    },
    {
        "scenario_id": "publisher_rejection",
        "runbook_scenario": "publisher rejection",
        "testcase": "test_structural_identity_and_publisher_chaos_remain_fail_closed[publisher_revalidation_rejected]",
    },
    {
        "scenario_id": "duplicate_core_trigger",
        "runbook_scenario": "duplicate core trigger",
        "testcase": "test_duplicate_core_trigger_is_not_eligible_for_rolling_production_green",
    },
    {
        "scenario_id": "duplicate_report_prefetch",
        "runbook_scenario": "duplicate report-prefetch",
        "testcase": "test_duplicate_report_prefetch_is_safety_net_noop",
    },
    {
        "scenario_id": "delayed_scheduler_execution",
        "runbook_scenario": "delayed scheduler execution",
        "testcase": "test_delayed_scheduler_execution_keeps_truthful_proof_age",
    },
    {
        "scenario_id": "last_good_recovery",
        "runbook_scenario": "LAST_GOOD recovery",
        "testcase": "test_last_good_recovery_is_allowed_only_for_nonvolatile_fields",
    },
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _testcase_status(testcase: ElementTree.Element) -> tuple[str, str | None]:
    failure = testcase.find("failure")
    if failure is not None:
        return "FAIL", failure.get("message") or (failure.text or "pytest failure").strip()
    error = testcase.find("error")
    if error is not None:
        return "FAIL", error.get("message") or (error.text or "pytest error").strip()
    skipped = testcase.find("skipped")
    if skipped is not None:
        return "SKIPPED", skipped.get("message") or (skipped.text or "pytest skipped").strip()
    return "PASS", None


def _parse_junit_testcases(junit_path: Path) -> dict[str, list[ElementTree.Element]]:
    root = ElementTree.parse(junit_path).getroot()
    cases: dict[str, list[ElementTree.Element]] = defaultdict(list)
    for testcase in root.iter("testcase"):
        name = str(testcase.get("name") or "").strip()
        if name:
            cases[name].append(testcase)
    return cases


def validate_canonical_registry(scenarios: Iterable[dict[str, str]] = CANONICAL_SCENARIOS) -> list[str]:
    errors: list[str] = []
    rows = list(scenarios)
    ids = [row.get("scenario_id", "") for row in rows]
    if any(not value for value in ids):
        errors.append("canonical_scenario_id_missing")
    duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
    if duplicate_ids:
        errors.append(f"duplicate_canonical_scenario_ids:{','.join(duplicate_ids)}")
    actual_ids = frozenset(ids)
    missing_ids = sorted(EXPECTED_SCENARIO_IDS - actual_ids)
    unknown_ids = sorted(actual_ids - EXPECTED_SCENARIO_IDS)
    if missing_ids:
        errors.append(f"canonical_scenarios_missing:{','.join(missing_ids)}")
    if unknown_ids:
        errors.append(f"canonical_scenarios_unknown:{','.join(unknown_ids)}")
    for row in rows:
        if not row.get("runbook_scenario") or not row.get("testcase"):
            errors.append(f"canonical_scenario_mapping_incomplete:{row.get('scenario_id') or '<missing>'}")
    return errors


def build_chaos_acceptance(
    junit_path: Path,
    *,
    evaluated_at: str | None = None,
    scenarios: Iterable[dict[str, str]] = CANONICAL_SCENARIOS,
) -> dict:
    scenario_rows = list(scenarios)
    errors = validate_canonical_registry(scenario_rows)
    cases = _parse_junit_testcases(junit_path)
    results: list[dict] = []

    for scenario in scenario_rows:
        testcase_name = scenario["testcase"]
        matches = cases.get(testcase_name, [])
        if not matches:
            status = "MISSING"
            detail = "required executable testcase absent from JUnit evidence"
            errors.append(f"missing_testcase:{scenario['scenario_id']}:{testcase_name}")
        elif len(matches) != 1:
            status = "AMBIGUOUS"
            detail = f"expected exactly one testcase result; found {len(matches)}"
            errors.append(f"ambiguous_testcase:{scenario['scenario_id']}:{testcase_name}:{len(matches)}")
        else:
            status, detail = _testcase_status(matches[0])
            if status != "PASS":
                errors.append(f"scenario_not_pass:{scenario['scenario_id']}:{status}")

        results.append(
            {
                "scenario_id": scenario["scenario_id"],
                "runbook_scenario": scenario["runbook_scenario"],
                "testcase": testcase_name,
                "status": status,
                "detail": detail,
            }
        )

    passed_count = sum(1 for row in results if row["status"] == "PASS")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "acceptance_kind": "WAVE3_CONTROLLED_CHAOS_MATRIX",
        "status": "PASS" if not errors and passed_count == len(results) else "FAIL",
        "evaluated_at": evaluated_at or _utc_now_iso(),
        "evidence_scope": EVIDENCE_SCOPE,
        "junit_sha256": _sha256(junit_path),
        "runtime_write_authorized": False,
        "natural_slot_counter_affected": False,
        "canonical_scenario_count": len(results),
        "passed_scenario_count": passed_count,
        "failed_or_missing_scenario_count": len(results) - passed_count,
        "scenarios": results,
        "errors": errors,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build fail-closed Wave 3 chaos acceptance from pytest JUnit evidence")
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    summary = build_chaos_acceptance(args.junit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
