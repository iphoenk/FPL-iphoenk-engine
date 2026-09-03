from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.engines import prediction_service
from src.runtime_v3 import domain_orchestrator, precompute_checkpoint
from src.runtime_v3.execution_profile_resolver import resolve_execution_profile
from src.runtime_v3.publication_verify import _verify_exhaustive_precompute_contract

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_exhaustive_snapshot(data_dir: Path) -> None:
    hold = {"id": "HOLD", "legal": True, "score": {"valid": True}}
    _write(data_dir / "package_optimizer.json", {
        "status": "READY",
        "hold": hold,
        "packages": [],
        "search_diagnostics": {
            "search_authority": "FULL",
            "lossy_pruning": False,
            "candidate_pruning_applied": False,
            "single_budget_applied": False,
            "pair_budget_applied": False,
            "exact_package_limit_applied": False,
            "all_step_legal_packages_scored": True,
            "watchlist_used_as_optimizer_input": False,
        },
    })
    _write(data_dir / "package_decision.json", {
        "selected_package_id": "HOLD",
        "current_squad_legal": True,
        "gate0_revalidated": True,
    })
    _write(data_dir / "framework_health.json", {
        "overall": "GREEN",
        "decision_engine": "HEALTHY",
        "gate0": {"pass": True, "counts": {"PASS": 16}},
    })
    _write(data_dir / "team.json", {
        "squad": [{"element": element} for element in range(1, 16)],
    })
    positions = {}
    next_element = 100
    for position in ("GK", "DEF", "MID", "FWD"):
        positions[position] = [{"element": next_element + offset} for offset in range(5)]
        next_element += 10
    _write(data_dir / "dss_watchlist.json", {"status": "READY", "positions": positions})
    _write(data_dir / "latest.json", {
        "decision_intelligence": {
            "package_optimizer_search_authority": "FULL",
            "package_optimizer_execution_profile": "exhaustive_precompute",
        },
        "package_decision_summary": {
            "selected_package_id": "HOLD",
            "gate0_revalidated": True,
        },
    })


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


def test_exhaustive_publication_assurance_requires_same_snapshot_full_chain(tmp_path):
    _valid_exhaustive_snapshot(tmp_path)
    result = _verify_exhaustive_precompute_contract(tmp_path)
    assert result["search_authority"] == "FULL"
    assert result["gate0_pass"] == 16
    assert result["framework"] == "GREEN"
    assert result["decision_engine"] == "HEALTHY"
    assert result["watchlist_counts"] == {position: 5 for position in ("GK", "DEF", "MID", "FWD")}
    assert result["watchlist_non_owned_unique"] is True


def test_exhaustive_publication_assurance_fails_closed_on_partial_optimizer(tmp_path):
    _valid_exhaustive_snapshot(tmp_path)
    optimizer = json.loads((tmp_path / "package_optimizer.json").read_text(encoding="utf-8"))
    optimizer["search_diagnostics"]["search_authority"] = "PARTIAL"
    _write(tmp_path / "package_optimizer.json", optimizer)
    with pytest.raises(RuntimeError, match="not FULL authority"):
        _verify_exhaustive_precompute_contract(tmp_path)


def test_exhaustive_publication_assurance_fails_closed_on_incomplete_watchlist(tmp_path):
    _valid_exhaustive_snapshot(tmp_path)
    watchlist = json.loads((tmp_path / "dss_watchlist.json").read_text(encoding="utf-8"))
    watchlist["positions"]["GK"].pop()
    _write(tmp_path / "dss_watchlist.json", watchlist)
    with pytest.raises(RuntimeError, match="not exact 5x4"):
        _verify_exhaustive_precompute_contract(tmp_path)


def test_exhaustive_publication_required_artifacts_are_whitelisted():
    publish_paths = set(_json("config/runtime/runtime_publish_registry.json")["publish_paths"])
    assert {
        "latest.json",
        "team.json",
        "package_optimizer.json",
        "package_decision.json",
        "framework_health.json",
        "dss_watchlist.json",
    } <= publish_paths


def test_ci_deployment_exhaustive_refresh_is_not_checkpoint_authority(monkeypatch):
    target = datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(precompute_checkpoint, "_precompute_decision", lambda now: {
        "should_collect": True,
        "reason": "precompute_next_checkpoint",
        "visible_mode": "EXHAUSTIVE_PRECOMPUTE",
        "snapshot_role": precompute_checkpoint.PRECOMPUTE_ROLE,
        "visible_report": False,
        "target_checkpoint_utc": target.isoformat(),
    })
    result = precompute_checkpoint._ci_deployment_decision(datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc))
    assert result["visible_mode"] == "EXHAUSTIVE_PRECOMPUTE"
    assert result["snapshot_role"] == precompute_checkpoint.CI_DEPLOYMENT_ROLE
    assert result["snapshot_role"] != precompute_checkpoint.PRECOMPUTE_ROLE
    assert result["reason"] == "post_ci_exhaustive_deployment_refresh"

    manifest = {
        "generated_at": "2026-09-03T10:00:00+00:00",
        "source_commit": "abc",
        "checkpoint": {
            "snapshot_role": precompute_checkpoint.CI_DEPLOYMENT_ROLE,
            "target_checkpoint": target.isoformat(),
            "materialization_complete": True,
        },
    }
    assert precompute_checkpoint._manifest_precompute_valid(
        manifest,
        target_utc=target,
        source_commit="abc",
    ) is False
