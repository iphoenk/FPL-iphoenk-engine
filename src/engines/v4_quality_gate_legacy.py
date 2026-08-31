from __future__ import annotations

"""Compatibility shim for historical V4 quality-gate imports.

The baseline implementation lives in ``v4_quality_gate_core`` and execution is
owned by ``v4_quality_gate_runner``. This module owns no assertion semantics and
exists only for compatibility while callers migrate off the historical name.
"""

from src.engines import v4_quality_gate_core as core
from src.engines.v4_quality_gate_runner import run as _run_gate
from src.release import RELEASE_VERSION

_load = core._load
_assert_version = core._assert_version
_assert_framework_health = core._assert_framework_health
_assert_orchestration = core._assert_orchestration
_assert_prediction_and_validation = core._assert_prediction_and_validation
_assert_engine_advisory = core._assert_engine_advisory
_assert_effective_plan = core._assert_effective_plan
_assert_scorecard_and_report = core._assert_scorecard_and_report


def run() -> dict:
    """Run using explicit dependencies, never by mutating another module."""
    return _run_gate(
        assert_framework_health=_assert_framework_health,
        assert_orchestration=_assert_orchestration,
        assert_prediction_and_validation=_assert_prediction_and_validation,
    )


__all__ = [
    "RELEASE_VERSION",
    "_load",
    "_assert_version",
    "_assert_framework_health",
    "_assert_orchestration",
    "_assert_prediction_and_validation",
    "_assert_engine_advisory",
    "_assert_effective_plan",
    "_assert_scorecard_and_report",
    "run",
]


if __name__ == "__main__":
    run()
