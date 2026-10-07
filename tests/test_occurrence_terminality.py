from __future__ import annotations

from src.engines.v12_occurrence_terminality import classify_occurrence


SLOT = "2026-10-07T21:30:00+07:00"
OCCURRENCE = f"DEEP|{SLOT}"
BODY_SHA = "a" * 64


def _evidence() -> dict:
    return {
        "report_mode": "DEEP",
        "report_slot": SLOT,
        "occurrence_id": OCCURRENCE,
        "serving": {
            "report_mode": "DEEP",
            "report_slot": SLOT,
            "runner_status": "PASS",
            "pre_render_status": "PASS",
            "post_render_status": "PASS",
            "human_facing_status": "PASS",
            "canonical_body_sha256": BODY_SHA,
        },
        "delivery": {"delivery_status": "READY_FULL", "root_failure": ""},
        "historical": {
            "exists": True,
            "path": "reports/2026-27/gw_6/occurrence/serving_report.md",
            "body_size": 123,
            "body_sha256": BODY_SHA,
            "receipt_body_sha256": BODY_SHA,
            "digest_body_sha256": BODY_SHA,
        },
        "latest": {"exists": True, "advanced": True, "body_sha256": BODY_SHA},
        "private_delivery_status": "PASS",
        "exact_publication": True,
        "stage3": {
            "validation": "PASS",
            "action": "COMPLETE",
            "engineering_closure_blocks_report": False,
        },
        "degradation": {"governed": False, "attributable": False, "reason": ""},
        "personal_authority_violation": False,
        "privacy_violation": False,
        "fabricated_evidence": False,
        "mandatory_math_failure": False,
    }


def test_full_occurrence_is_ready_full():
    result = classify_occurrence(_evidence())
    assert result["terminality"] == "READY_FULL"
    assert result["failures"] == []


def test_governed_partial_with_report_first_stage3_is_ready_degraded():
    evidence = _evidence()
    evidence["serving"]["runner_status"] = "PARTIAL"
    evidence["delivery"] = {"delivery_status": "READY_DEGRADED", "root_failure": "ANALYTICS_INCOMPLETE"}
    evidence["stage3"] = {"validation": "DEGRADED", "action": "WAIT", "engineering_closure_blocks_report": False}
    evidence["degradation"] = {"governed": True, "attributable": True, "reason": "ANALYTICS_INCOMPLETE"}
    result = classify_occurrence(evidence)
    assert result["terminality"] == "READY_DEGRADED"
    assert result["failures"] == []


def test_ungoverned_partial_fails_closed():
    evidence = _evidence()
    evidence["serving"]["runner_status"] = "PARTIAL"
    evidence["delivery"] = {"delivery_status": "READY_DEGRADED", "root_failure": "ANALYTICS_INCOMPLETE"}
    result = classify_occurrence(evidence)
    assert result["terminality"] == "FAILED_VERIFY"
    assert "UNGOVERNED_DEGRADATION" in result["failures"]


def test_delivery_failure_fails_closed():
    evidence = _evidence()
    evidence["private_delivery_status"] = "FAIL"
    result = classify_occurrence(evidence)
    assert result["terminality"] == "FAILED_VERIFY"
    assert "PRIVATE_DELIVERY_NOT_PASS" in result["failures"]


def test_human_facing_failure_fails_closed():
    evidence = _evidence()
    evidence["serving"]["human_facing_status"] = "FAIL"
    result = classify_occurrence(evidence)
    assert result["terminality"] == "FAILED_VERIFY"
    assert "HUMAN_FACING_QA_NOT_PASS" in result["failures"]


def test_post_render_failure_fails_closed():
    evidence = _evidence()
    evidence["serving"]["post_render_status"] = "FAIL"
    result = classify_occurrence(evidence)
    assert result["terminality"] == "FAILED_VERIFY"
    assert "POST_RENDER_QA_NOT_PASS" in result["failures"]


def test_slot_mismatch_fails_closed():
    evidence = _evidence()
    evidence["serving"]["report_slot"] = "2026-10-07T12:30:00+07:00"
    result = classify_occurrence(evidence)
    assert result["terminality"] == "FAILED_VERIFY"
    assert "EXACT_SLOT_MISMATCH" in result["failures"]


def test_publication_missing_fails_closed():
    evidence = _evidence()
    evidence["historical"]["exists"] = False
    evidence["exact_publication"] = False
    result = classify_occurrence(evidence)
    assert result["terminality"] == "FAILED_VERIFY"
    assert "HISTORICAL_PUBLICATION_MISSING" in result["failures"]


def test_digest_mismatch_fails_closed():
    evidence = _evidence()
    evidence["latest"]["body_sha256"] = "b" * 64
    result = classify_occurrence(evidence)
    assert result["terminality"] == "FAILED_VERIFY"
    assert "BODY_DIGEST_MISMATCH" in result["failures"]


def test_governed_stage3_degradation_does_not_fail_report_delivery():
    evidence = _evidence()
    evidence["serving"]["runner_status"] = "PARTIAL"
    evidence["delivery"] = {"delivery_status": "READY_DEGRADED", "root_failure": "ANALYTICS_INCOMPLETE"}
    evidence["stage3"] = {"validation": "DEGRADED", "action": "WAIT", "engineering_closure_blocks_report": False}
    evidence["degradation"] = {"governed": True, "attributable": True, "reason": "ANALYTICS_INCOMPLETE"}
    result = classify_occurrence(evidence)
    assert result["terminality"] == "READY_DEGRADED"
    assert result["engineering_status"] == "DEGRADED"


def test_personal_or_privacy_boundary_never_degrades_to_ready():
    for key in ("personal_authority_violation", "privacy_violation", "fabricated_evidence", "mandatory_math_failure"):
        evidence = _evidence()
        evidence[key] = True
        result = classify_occurrence(evidence)
        assert result["terminality"] == "FAILED_VERIFY"
