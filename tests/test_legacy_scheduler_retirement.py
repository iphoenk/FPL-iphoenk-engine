from __future__ import annotations

from pathlib import Path

import pytest

from src import engine
from src.runtime_v3 import domain_orchestrator, orchestrator

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


def test_compatibility_facade_delegates_to_canonical_domain_runtime(monkeypatch):
    calls: list[dict] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"status": "SUCCESS", "runtime": "canonical-domain"}

    monkeypatch.setattr(domain_orchestrator, "run", fake_run)
    result = engine.run(mode="live", sync_stats=False, deep_stats=True)

    assert result == {"status": "SUCCESS", "runtime": "canonical-domain"}
    assert calls == [{"mode": "live", "stats": False, "deep_stats": True}]

    source = Path(engine.__file__).read_text(encoding="utf-8")
    assert "src.runtime_v3.domain_orchestrator" in source
    assert "src.runtime_v3.orchestrator" not in source


def test_supported_root_and_docker_surfaces_use_repaired_compatibility_facade():
    export_master = (ROOT / "export_master.py").read_text(encoding="utf-8")
    daily_tasks = (ROOT / "fpl_daily_tasks.py").read_text(encoding="utf-8")
    live_service = (ROOT / "live_service.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "from src.engine import run" in export_master
    assert "from src.engine import cli" in daily_tasks
    assert "from src.engine import run" in live_service
    assert "uvicorn\",\"live_service:app" in dockerfile

    assert '_logger.exception("V3 live refresh failed")' in live_service
    assert "except Exception:\n            pass" not in live_service


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
