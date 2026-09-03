from __future__ import annotations

from src.engines import prediction_service


def test_fast_prediction_prefers_exact_attested_full_optimizer(monkeypatch):
    full = {
        "status": "READY",
        "search_diagnostics": {
            "search_authority": "FULL",
            "lossy_pruning": False,
            "all_step_legal_packages_scored": True,
        },
        "governance": {},
    }
    monkeypatch.setenv("FPL_EXECUTION_PROFILE", "fast_decision")
    monkeypatch.setattr(prediction_service, "reusable_full_optimizer", lambda: full)
    monkeypatch.setattr(
        prediction_service,
        "build_package_optimizer",
        lambda projections, team: (_ for _ in ()).throw(AssertionError("PARTIAL optimizer must not run on exact FULL reuse")),
    )
    result = prediction_service._build_packages({"planning_gw": 3, "players": []}, {})
    assert result is full
    assert result["governance"]["full_authority_exact_input_reuse"] is True
    assert result["governance"]["authority_execution_profile"] == "exhaustive_precompute"
    assert result["governance"]["runtime_reuse_profile"] == "fast_decision"


def test_fast_prediction_recomputes_when_full_authority_fingerprint_is_not_reusable(monkeypatch):
    partial = {"status": "READY", "governance": {}}
    monkeypatch.setenv("FPL_EXECUTION_PROFILE", "fast_decision")
    monkeypatch.setattr(prediction_service, "reusable_full_optimizer", lambda: None)
    monkeypatch.setattr(prediction_service, "build_package_optimizer", lambda projections, team: partial)
    result = prediction_service._build_packages({"planning_gw": 3, "players": []}, {})
    assert result is partial
    assert result["governance"]["full_authority_exact_input_reuse"] is False
    assert result["governance"]["authority_execution_profile"] == "fast_decision"
