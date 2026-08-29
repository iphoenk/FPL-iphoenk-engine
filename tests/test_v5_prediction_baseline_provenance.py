import json
from pathlib import Path

from src.v5.evaluation.baseline_provenance import build_baseline_candidate, validate_baseline_registry


def _registry(baseline=None):
    return {
        "state": "PENDING_NO_SETTLED_PRODUCTION_EVIDENCE",
        "source_requirements": {
            "source_branch": "main",
            "artifact_branch": "runtime-data",
            "production_model": "prediction_evaluation_v1",
            "minimum_settled_gameweeks": 4,
            "minimum_player_gw_samples": 1000,
            "minimum_starter_samples": 750,
            "minimum_clean_sheet_samples": 300,
            "required_metrics": ["points_mae", "xmins_mae", "starter_brier", "clean_sheet_brier", "spearman"],
        },
        "frozen_baseline": baseline,
    }


def _valid_baseline():
    return {
        "status": "FROZEN_ACCEPTED",
        "provenance": {
            "source_branch": "main",
            "artifact_branch": "runtime-data",
            "model": "prediction_evaluation_v1",
            "source_main_sha": "abc123",
            "runtime_engine_version": "3.39.0",
            "retrospective_proxy": False,
            "counts_toward_predictive_accuracy": True,
            "posthoc_reconstruction": False,
        },
        "settled_gameweeks": [2, 3, 4, 5],
        "samples": {"player_gw": 1200, "starter": 900, "clean_sheet": 400},
        "metrics": {
            "points_mae": 2.1,
            "xmins_mae": 15.0,
            "starter_brier": 0.12,
            "clean_sheet_brier": 0.15,
            "spearman": 0.48,
        },
    }


def test_missing_baseline_stays_pending_and_cannot_prove_non_regression():
    result = validate_baseline_registry(_registry(), expected_production_sha="abc123", expected_runtime_engine_version="3.39.0")
    assert result["eligible"] is False
    assert result["status"] == "PENDING_NO_FROZEN_BASELINE"
    assert result["metrics"] is None


def test_manual_or_proxy_baseline_is_rejected_fail_closed():
    baseline = _valid_baseline()
    baseline["provenance"]["retrospective_proxy"] = True
    baseline["provenance"]["source_main_sha"] = "wrong"
    result = validate_baseline_registry(_registry(baseline), expected_production_sha="abc123", expected_runtime_engine_version="3.39.0")
    assert result["eligible"] is False
    assert result["checks"]["not_retrospective_proxy"] is False
    assert result["checks"]["source_sha_matches"] is False
    assert result["metrics"] is None


def test_complete_settled_production_baseline_passes_provenance():
    result = validate_baseline_registry(_registry(_valid_baseline()), expected_production_sha="abc123", expected_runtime_engine_version="3.39.0")
    assert result["eligible"] is True
    assert result["status"] == "PASS"
    assert result["metrics"]["points_mae"] == 2.1


def test_candidate_builder_preserves_zero_sample_as_pending_evidence():
    accuracy = {
        "generated_at": "2026-08-29T08:19:01Z",
        "model": "prediction_evaluation_v1",
        "overall": {"sample_size": 0, "status": "NO_SETTLED_SAMPLE"},
        "settled_gameweeks": [],
    }
    manifest = {
        "source_commit": "abc123",
        "engine_version": "3.39.0",
        "schema_version": 49,
        "published_at": "2026-08-29T08:19:02Z",
    }
    candidate = build_baseline_candidate(accuracy, manifest, accepted_production_sha="abc123")
    result = validate_baseline_registry(_registry(candidate), expected_production_sha="abc123", expected_runtime_engine_version="3.39.0")
    assert candidate["samples"]["player_gw"] == 0
    assert candidate["settled_gameweeks"] == []
    assert result["eligible"] is False
    assert result["checks"]["player_gw_samples"] is False


def test_live_config_cannot_contain_unproven_frozen_metrics():
    eval_cfg = json.loads(Path("config/intelligence/prediction_evaluation.json").read_text(encoding="utf-8"))
    registry = json.loads(Path(eval_cfg["baseline_provenance_registry"]).read_text(encoding="utf-8"))
    baseline = registry.get("frozen_baseline")
    metrics = eval_cfg.get("frozen_baseline_metrics")
    if metrics is not None:
        assert baseline is not None, "frozen metrics may not exist without a provenance record"
        expected_sha = json.loads(Path("config/v5_convergence_manifest.json").read_text(encoding="utf-8"))["baselines"]["production_main_sha"]
        result = validate_baseline_registry(registry, expected_production_sha=expected_sha)
        assert result["eligible"] is True, "frozen metrics require provenance PASS"
        assert metrics == result["metrics"], "evaluation baseline metrics must exactly match accepted provenance metrics"
