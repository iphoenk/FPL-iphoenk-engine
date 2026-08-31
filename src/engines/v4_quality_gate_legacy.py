from __future__ import annotations

"""Compatibility shim for historical V4 quality-gate imports.

The baseline implementation lives in ``v4_quality_gate_core``. This module owns
no assertions. It only preserves the old monkey-patch contract while callers are
migrated off the historical module name.
"""

from src.engines import v4_quality_gate_core as core

RELEASE_VERSION = core.RELEASE_VERSION
_load = core._load
_assert_version = core._assert_version
_assert_framework_health = core._assert_framework_health
_assert_orchestration = core._assert_orchestration
_assert_prediction_and_validation = core._assert_prediction_and_validation
_assert_engine_advisory = core._assert_engine_advisory
_assert_effective_plan = core._assert_effective_plan
_assert_scorecard_and_report = core._assert_scorecard_and_report


def run() -> dict:
    """Run the core gate while honoring historical assertion overrides."""
    original = (
        core._assert_framework_health,
        core._assert_orchestration,
        core._assert_prediction_and_validation,
    )
    core._assert_framework_health = _assert_framework_health
    core._assert_orchestration = _assert_orchestration
    core._assert_prediction_and_validation = _assert_prediction_and_validation
    try:
        return core.run()
    finally:
        (
            core._assert_framework_health,
            core._assert_orchestration,
            core._assert_prediction_and_validation,
        ) = original


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
