from __future__ import annotations

from pathlib import Path

import pytest

from src.runtime_v3 import orchestrator

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_service_scheduler_entry_fails_closed():
    with pytest.raises(RuntimeError, match="RETIRED_V3_SERVICE_SCHEDULER"):
        orchestrator.run(mode="daily", stats=True, deep_stats=False, profile="fast_decision")


def test_canonical_runtime_does_not_schedule_legacy_entry():
    runtime_workflow = (ROOT / ".github/workflows/v3-runtime.yml").read_text(encoding="utf-8")
    assert "python -m src.runtime_v3.domain_orchestrator" in runtime_workflow
    assert "python -m src.runtime_v3.orchestrator" not in runtime_workflow


def test_release_acceptance_does_not_reactivate_legacy_scheduler():
    equivalence = (ROOT / "src/runtime_v3/equivalence_acceptance.py").read_text(encoding="utf-8")
    assert 'RUNTIME_MODULE = "src.runtime_v3.domain_orchestrator"' in equivalence
    assert '"src.runtime_v3.orchestrator"' not in equivalence
    assert '"legacy_scheduler_executed": False' in equivalence


def test_shared_primitives_remain_available_for_canonical_runtime():
    required = (
        "_load_profiles",
        "_default_profile",
        "_reuse_service",
        "_run_service",
        "_validate_service_outputs",
        "_clear_failed_service_outputs",
        "_cleanup_ephemeral",
        "_write_runtime_metadata",
    )
    for name in required:
        assert callable(getattr(orchestrator, name))
