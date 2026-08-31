from __future__ import annotations

"""Compatibility shim for historical imports.

Production V4 quality-gate ownership lives in ``v4_quality_gate`` with shared
baseline assertions in ``v4_quality_gate_core``. New production code must not
import this module.
"""

from src.engines.v4_quality_gate_core import (  # noqa: F401
    RELEASE_VERSION,
    _assert_engine_advisory,
    _assert_effective_plan,
    _assert_framework_health,
    _assert_orchestration,
    _assert_prediction_and_validation,
    _assert_scorecard_and_report,
    _assert_version,
    _load,
    run,
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
