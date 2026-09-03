from __future__ import annotations

import json
import sys
from pathlib import Path

from src.engines import prediction_service
from src.runtime_v3 import domain_orchestrator
from src.runtime_v3.execution_profile_resolver import resolve_execution_profile

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_exhaustive_precompute_profile_resolves_from_single_policy_authority():
    resolved = resolve_execution_profile(
        visible_mode="EXHAUSTIVE_PRECOMPUTE",
        deadline_intensive=False,
        match_window=False,
        post_deadline_reconciliation=False,
        report_state={},
    )
    assert resolved["profile"] == "exhaustive_precompute"
    assert resolved["mode"] == "daily"


def test_prediction_owner_uses_full_exhaustive_optimizer_only_for_precompute(monkeypatch):
    sentinel = {
        "status": "READY",
        "search_diagnostics": {
            "search_authority": "FULL",
            "lossy_pruning": False,
            "all_step_legal_packages_scored": True,
        },
        "governance": {},
    }
    import src.engines.package_optimizer_exhaustive_accelerated as exhaustive

    monkeypatch.setattr(exhaustive, "build_exhaustive", lambda projections, team: sentinel)
    monkeypatch.setenv("FPL_EXECUTION_PROFILE", "exhaustive_precompute")
    result = prediction_service._build_packages({"planning_gw": 3, "players": []}, {})

    assert result is sentinel
    governance = result["governance"]
    assert governance["production_owner"] == "prediction"
    assert governance["execution_profile"] == "exhaustive_precompute"
    assert governance["package_decision_writer"] == "lineup_governance"
    assert governance["exhaustive_precompute"] is True


def test_prediction_owner_keeps_normal_optimizer_outside_precompute(monkeypatch):
    sentinel = {"status": "READY", "governance": {}}
    monkeypatch.setattr(prediction_service, "build_package_optimizer", lambda projections, team: sentinel)
    monkeypatch.setenv("FPL_EXECUTION_PROFILE", "fast_decision")
    assert prediction_service._build_packages({"planning_gw": 3, "players": []}, {}) is sentinel


def test_domain_orchestrator_cli_accepts_registry_profile(monkeypatch):
    captured = {}

    def fake_run(*, mode, stats, deep_stats, profile):
        captured.update({"mode": mode, "stats": stats, "deep_stats": deep_stats, "profile": profile})
        return {}

    monkeypatch.setattr(domain_orchestrator, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["domain_orchestrator", "--profile", "exhaustive_precompute"])
    assert domain_orchestrator.main() == 0
    assert captured["profile"] == "exhaustive_precompute"


def test_exhaustive_timeout_is_profile_scoped_and_other_slos_unchanged():
    profiles = _json("config/runtime/execution_profiles.json")["profiles"]
    slo = _json("config/runtime/performance_slo.json")["profiles"]
    source = (ROOT / "src/runtime_v3/domain_orchestrator.py").read_text(encoding="utf-8")

    assert profiles["exhaustive_precompute"]["service_timeout_seconds"] == 300
    assert 'profile_cfg.get("service_timeout_seconds")' in source
    assert '["fast_decision", "live", "full_refresh", "deep_stats"]' not in source

    assert slo["fast_decision"]["legacy_ceiling_ms"] == 3000
    assert slo["full_refresh"]["legacy_ceiling_ms"] == 60000
    assert slo["deep_stats"]["legacy_ceiling_ms"] == 90000
    assert slo["exhaustive_precompute"]["legacy_ceiling_ms"] == 300000


def test_registry_preserves_single_prediction_owner_and_downstream_decision_owner():
    registry = _json("config/v3_service_registry.json")["services"]
    assert registry["prediction"]["commands"] == [{"module": "src.engines.prediction_service", "args": []}]
    assert "package_optimizer.json" in registry["prediction"]["artifacts"]
    assert registry["lineup_governance"]["depends_on"] == ["prediction"]
    assert "package_optimizer.json" in registry["lineup_governance"]["inputs"]
    assert "package_decision.json" in registry["lineup_governance"]["artifacts"]
