from __future__ import annotations

import pytest

from src.engines.v12_stage3_upstream_diagnostics import blocked_stage3_payload


def test_blocked_stage3_payload_preserves_valid_upstream_predicates_only():
    payload = blocked_stage3_payload(
        {
            "stage3_guard_failures": [
                "MC_CANONICAL_PASS",
                "PRIVATE_TOKEN_SHOULD_NOT_ESCAPE",
                "MC_CANONICAL_PASS",
            ],
            "monte_carlo": {
                "actual_paths": 500000,
                "canonical_pass": False,
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
    assert payload["reason"] == "BLOCKED_UPSTREAM"
    assert payload["upstream_guard_failures"] == ["MC_CANONICAL_PASS"]
    assert payload["upstream_monte_carlo"] == {
        "actual_paths": 500000,
        "canonical_pass": False,
        "convergence_status": "INSUFFICIENT_STABILITY",
        "mean_delta_stable": True,
        "outperform_probability_stable": True,
        "median_delta_stable": False,
    }
    assert payload["stage3_executed"] is False
    assert payload["governance"]["upstream_guard_diagnostics_only"] is True


def test_blocked_stage3_payload_rejects_pass_runner():
    with pytest.raises(ValueError, match="must execute"):
        blocked_stage3_payload({}, "PASS")
