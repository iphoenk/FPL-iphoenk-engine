from __future__ import annotations

import pytest

from src.engines.v4_quality_gate import _assert_capability_lifecycle_state


def _health(**overrides):
    out = {
        "critical_partial": [],
        "critical_warmup": ["DSS-44", "DSS-X12"],
        "capability_coverage": {
            "active": 72,
            "warmup": 2,
            "partial": 0,
            "failed": 0,
            "declared": 74,
            "active_ratio": 0.973,
        },
        "capability_maturity": "WARMUP",
        "decision_engine": "PROVISIONAL",
        "go_allowed": False,
    }
    out.update(overrides)
    return out


def test_quality_gate_accepts_governed_warmup_state():
    _assert_capability_lifecycle_state(_health())


def test_quality_gate_accepts_evidence_backed_mature_state():
    _assert_capability_lifecycle_state(
        _health(
            critical_warmup=[],
            capability_coverage={
                "active": 74,
                "warmup": 0,
                "partial": 0,
                "failed": 0,
                "declared": 74,
                "active_ratio": 1.0,
            },
            capability_maturity="MATURE",
            decision_engine="HEALTHY",
            go_allowed=True,
        )
    )


def test_quality_gate_rejects_unproven_mature_claim():
    with pytest.raises(AssertionError):
        _assert_capability_lifecycle_state(
            _health(
                critical_warmup=[],
                capability_maturity="MATURE",
                decision_engine="HEALTHY",
                go_allowed=True,
            )
        )
