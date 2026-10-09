from __future__ import annotations

import json

import pytest

from src.engines.v12_stage3_upstream_diagnostics import blocked_stage3_payload


def test_genuine_upstream_guard_failure_remains_degraded() -> None:
    payload = blocked_stage3_payload(
        {
            "stage3_guard_failures": ["MC_CANONICAL_PASS", "MC_CONVERGENCE_PASS"],
            "monte_carlo": {
                "actual_paths": 500_000,
                "canonical_pass": True,
                "convergence": {
                    "status": "INSUFFICIENT_STABILITY",
                    "acceptance": {
                        "mean_delta_stable": True,
                        "outperform_probability_stable": True,
                        "median_delta_stable": False,
                    },
                },
            },
        },
        "PARTIAL",
    )
    assert payload["status"] == "DEGRADED"
    assert payload["reason"] == "BLOCKED_UPSTREAM"
    assert payload["upstream_guard_failures"] == [
        "MC_CANONICAL_PASS",
        "MC_CONVERGENCE_PASS",
    ]
    assert payload["stage3_executed"] is False
    assert payload["stage3_pass_claimed"] is False
    assert payload["mc_pass_claimed"] is False
    assert payload["upstream_monte_carlo"]["actual_paths"] == 500_000
    assert payload["upstream_monte_carlo"]["convergence_status"] == "INSUFFICIENT_STABILITY"
    assert payload["upstream_monte_carlo"]["median_delta_stable"] is False


def test_stage3_not_executed_cannot_claim_pass() -> None:
    with pytest.raises(ValueError, match="Stage3 must execute"):
        blocked_stage3_payload({}, "PASS")


def test_monte_carlo_failure_cannot_be_silently_bypassed() -> None:
    payload = blocked_stage3_payload(
        {
            "stage3_guard_failures": ["MC_CONVERGENCE_PASS"],
            "monte_carlo": {
                "actual_paths": 500_000,
                "canonical_pass": True,
                "convergence": {
                    "status": "INSUFFICIENT_STABILITY",
                    "acceptance": {"median_delta_stable": False},
                },
            },
        },
        "PARTIAL",
    )
    assert payload["status"] == "DEGRADED"
    assert payload["mc_pass_claimed"] is False
    assert payload["upstream_monte_carlo"]["convergence_status"] == "INSUFFICIENT_STABILITY"
    assert payload["upstream_guard_failures"] == ["MC_CONVERGENCE_PASS"]


def test_successful_stage3_is_not_routed_through_blocked_payload() -> None:
    # PASS must continue through the normal Stage3 acceptance validator.
    with pytest.raises(ValueError):
        blocked_stage3_payload({"stage3_internal_pass": True}, "PASS")


def test_sensitive_personal_fields_are_excluded_from_public_diagnostics() -> None:
    secret_marker = "PERSONAL_FINANCE_MUST_NOT_ESCAPE"
    payload = blocked_stage3_payload(
        {
            "stage3_guard_failures": ["MC_CONVERGENCE_PASS", secret_marker],
            "personal_economics_authority": {
                "bank": secret_marker,
                "purchase_price": secret_marker,
                "token": secret_marker,
            },
            "monte_carlo": {
                "actual_paths": 500_000,
                "convergence": {
                    "status": "INSUFFICIENT_STABILITY",
                    "acceptance": {"median_delta_stable": False},
                },
            },
        },
        "PARTIAL",
    )
    encoded = json.dumps(payload, sort_keys=True)
    assert secret_marker not in encoded
    assert "personal_economics_authority" not in encoded
