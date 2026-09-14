from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree

from src.runtime_v6.wave3_chaos_acceptance import (
    CANONICAL_SCENARIOS,
    EXPECTED_SCENARIO_IDS,
    build_chaos_acceptance,
    validate_canonical_registry,
)


EVALUATED_AT = "2026-09-14T06:45:00Z"


def _write_junit(
    path: Path,
    *,
    omitted: set[str] | None = None,
    skipped: set[str] | None = None,
    failed: set[str] | None = None,
    duplicate: set[str] | None = None,
) -> None:
    omitted = omitted or set()
    skipped = skipped or set()
    failed = failed or set()
    duplicate = duplicate or set()
    root = ElementTree.Element("testsuites")
    suite = ElementTree.SubElement(root, "testsuite", name="wave3-chaos")
    names = sorted({row["testcase"] for row in CANONICAL_SCENARIOS})
    for name in names:
        if name in omitted:
            continue
        copies = 2 if name in duplicate else 1
        for _ in range(copies):
            case = ElementTree.SubElement(suite, "testcase", classname="tests.test_data_platform_wave3_chaos_matrix", name=name)
            if name in skipped:
                ElementTree.SubElement(case, "skipped", message="deliberately skipped")
            if name in failed:
                ElementTree.SubElement(case, "failure", message="deliberate failure")
    ElementTree.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_canonical_chaos_registry_is_exact_and_complete():
    assert validate_canonical_registry() == []
    assert {row["scenario_id"] for row in CANONICAL_SCENARIOS} == EXPECTED_SCENARIO_IDS
    assert len(CANONICAL_SCENARIOS) == 16


def test_complete_executable_chaos_evidence_builds_bound_pass_summary(tmp_path):
    junit = tmp_path / "wave3-chaos.xml"
    _write_junit(junit)

    summary = build_chaos_acceptance(junit, evaluated_at=EVALUATED_AT)

    assert summary["status"] == "PASS"
    assert summary["evaluated_at"] == EVALUATED_AT
    assert summary["canonical_scenario_count"] == 16
    assert summary["passed_scenario_count"] == 16
    assert summary["failed_or_missing_scenario_count"] == 0
    assert summary["errors"] == []
    assert summary["natural_slot_counter_affected"] is False
    assert summary["runtime_write_authorized"] is False
    assert summary["junit_sha256"] == hashlib.sha256(junit.read_bytes()).hexdigest()


def test_missing_required_chaos_testcase_fails_closed(tmp_path):
    junit = tmp_path / "wave3-chaos.xml"
    missing = CANONICAL_SCENARIOS[0]["testcase"]
    _write_junit(junit, omitted={missing})

    summary = build_chaos_acceptance(junit, evaluated_at=EVALUATED_AT)

    assert summary["status"] == "FAIL"
    assert any(error.startswith("missing_testcase:provider_timeout:") for error in summary["errors"])


def test_skipped_or_failed_chaos_testcase_fails_closed(tmp_path):
    junit = tmp_path / "wave3-chaos.xml"
    skipped = CANONICAL_SCENARIOS[1]["testcase"]
    failed = CANONICAL_SCENARIOS[-1]["testcase"]
    _write_junit(junit, skipped={skipped}, failed={failed})

    summary = build_chaos_acceptance(junit, evaluated_at=EVALUATED_AT)

    assert summary["status"] == "FAIL"
    assert "scenario_not_pass:provider_incomplete_amber:SKIPPED" in summary["errors"]
    assert "scenario_not_pass:last_good_recovery:FAIL" in summary["errors"]


def test_duplicate_testcase_evidence_is_ambiguous_and_fails_closed(tmp_path):
    junit = tmp_path / "wave3-chaos.xml"
    duplicate = CANONICAL_SCENARIOS[6]["testcase"]
    _write_junit(junit, duplicate={duplicate})

    summary = build_chaos_acceptance(junit, evaluated_at=EVALUATED_AT)

    assert summary["status"] == "FAIL"
    assert any(error.startswith("ambiguous_testcase:identity_conflict:") for error in summary["errors"])


def test_unknown_or_missing_canonical_registry_entry_fails_closed():
    missing = list(CANONICAL_SCENARIOS[:-1])
    missing_errors = validate_canonical_registry(missing)
    assert any(error.startswith("canonical_scenarios_missing:") for error in missing_errors)

    unknown = [*CANONICAL_SCENARIOS, {"scenario_id": "unknown_chaos", "runbook_scenario": "unknown", "testcase": "test_unknown"}]
    unknown_errors = validate_canonical_registry(unknown)
    assert "canonical_scenarios_unknown:unknown_chaos" in unknown_errors
