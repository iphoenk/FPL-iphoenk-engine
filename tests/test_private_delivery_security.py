from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v12_delivery_security import (
    DeliverySecurityError,
    assert_no_pull_request_target,
    build_public_issue_proof,
    cache_security_manifest,
    scan_public_text,
    validate_public_proof,
)


def _safe_proof() -> dict:
    return {
        "report_mode": "DEEP",
        "report_slot": "2026-09-26T12:30:00+07:00",
        "run_id": "synthetic",
        "analytics_status": "PASS",
        "pre_render_status": "PASS",
        "post_render_status": "PASS",
        "human_facing_status": "PASS",
        "stage3_validation_status": "PASS",
        "model_sha": "a" * 40,
        "runtime_sha": "b" * 40,
        "safe_fingerprints": {"canonical": "c" * 64},
        "private_delivery_status": "PASS",
        "private_receipt_hash": "d" * 64,
        "timing": {"elapsed_seconds": 1.25},
        "profile_mode": "OFF",
    }


def test_public_proof_allowlist_accepts_safe_operational_metadata():
    assert validate_public_proof(_safe_proof()) == _safe_proof()


@pytest.mark.parametrize(
    "key,value",
    [
        ("action", "WAIT"),
        ("stage3_action", "WAIT"),
        ("selected_route", "R1"),
        ("starting_xi", [1] * 11),
        ("captain", 1),
        ("bank", 10),
        ("pending_transfer", {"out": 1, "in": 2}),
    ],
)
def test_public_proof_rejects_sensitive_or_non_allowlisted_fields(key, value):
    proof = _safe_proof()
    proof[key] = value
    with pytest.raises(DeliverySecurityError):
        validate_public_proof(proof)


def test_public_proof_rejects_sensitive_nested_key_even_inside_allowed_container():
    proof = _safe_proof()
    proof["safe_fingerprints"] = {"selected_route": "not-safe"}
    with pytest.raises(DeliverySecurityError):
        validate_public_proof(proof)


def test_issue_proof_never_contains_stage3_action_or_decision_enum_field():
    line = build_public_issue_proof(
        analytics_status="PASS",
        report_mode="DEEP",
        report_slot="2026-09-26T12:30:00+07:00",
        run_id=123,
        stage3_validation="PASS",
        private_delivery_status="PASS",
        private_receipt_hash="abc",
    )
    assert "STAGE3_ACTION" not in line
    assert "action=" not in line.lower()
    assert "selected_route" not in line.lower()


def test_actual_log_guard_detects_known_regression_shape():
    text = "safe line\n  STAGE3_ACTION: WAIT\nother line\n"
    findings = scan_public_text(text)
    assert any(item.category == "PRIVATE_DECISION" for item in findings)


def test_masked_github_checkout_authorization_is_not_secret_leak():
    text = "extraheader AUTHORIZATION: basic ***"
    assert not [item for item in scan_public_text(text) if item.category == "SECRET"]


def test_cache_classification_is_frozen_by_evidence():
    assert cache_security_manifest() == {
        "stage2_derived": "PUBLIC_SAFE",
        "p17_decision_core": "PRIVATE_REQUIRED",
        "mc_simulation_summary": "PRIVATE_REQUIRED",
    }


def test_repository_has_no_pull_request_target_workflow():
    assert_no_pull_request_target()


def test_contract_classes_are_complete():
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (root / "config/security/v12_delivery_classification.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(contract["classes"]) == {
        "PUBLIC_FACT",
        "PUBLIC_OPERATIONAL_PROOF",
        "PRIVATE_PERSONAL",
        "PRIVATE_DECISION",
        "SECRET",
    }
