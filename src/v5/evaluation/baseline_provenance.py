from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

BASELINE_CONFIG = "config/v5_prediction_baseline_provenance.json"
MANIFEST_CONFIG = "config/v5_convergence_manifest.json"


def _i(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def validate_baseline_registry(
    registry: dict[str, Any],
    *,
    expected_production_sha: str,
    expected_runtime_engine_version: str | None = None,
) -> dict[str, Any]:
    requirements = registry.get("source_requirements") if isinstance(registry.get("source_requirements"), dict) else {}
    baseline = registry.get("frozen_baseline") if isinstance(registry.get("frozen_baseline"), dict) else None
    checks: dict[str, bool] = {}
    if baseline is None:
        return {
            "status": "PENDING_NO_FROZEN_BASELINE",
            "eligible": False,
            "checks": checks,
            "metrics": None,
            "state": registry.get("state"),
        }

    provenance = baseline.get("provenance") if isinstance(baseline.get("provenance"), dict) else {}
    samples = baseline.get("samples") if isinstance(baseline.get("samples"), dict) else {}
    metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
    settled = baseline.get("settled_gameweeks") if isinstance(baseline.get("settled_gameweeks"), list) else []

    checks["frozen_status"] = baseline.get("status") == "FROZEN_ACCEPTED"
    checks["source_branch"] = provenance.get("source_branch") == requirements.get("source_branch", "main")
    checks["artifact_branch"] = provenance.get("artifact_branch") == requirements.get("artifact_branch", "runtime-data")
    checks["production_model"] = provenance.get("model") == requirements.get("production_model")
    checks["source_sha_matches"] = str(provenance.get("source_main_sha") or "") == str(expected_production_sha or "")
    checks["runtime_engine_version"] = bool(provenance.get("runtime_engine_version"))
    if expected_runtime_engine_version:
        checks["runtime_engine_version_matches"] = str(provenance.get("runtime_engine_version")) == str(expected_runtime_engine_version)
    checks["not_retrospective_proxy"] = provenance.get("retrospective_proxy") is False
    checks["counts_toward_predictive_accuracy"] = provenance.get("counts_toward_predictive_accuracy") is True
    checks["posthoc_reconstruction_forbidden"] = provenance.get("posthoc_reconstruction") is False
    checks["settled_gameweeks"] = len({int(x) for x in settled}) >= _i(requirements.get("minimum_settled_gameweeks"))
    checks["player_gw_samples"] = _i(samples.get("player_gw")) >= _i(requirements.get("minimum_player_gw_samples"))
    checks["starter_samples"] = _i(samples.get("starter")) >= _i(requirements.get("minimum_starter_samples"))
    checks["clean_sheet_samples"] = _i(samples.get("clean_sheet")) >= _i(requirements.get("minimum_clean_sheet_samples"))
    required_metrics = [str(x) for x in requirements.get("required_metrics") or []]
    checks["required_metrics_present"] = bool(required_metrics) and all(metrics.get(name) is not None for name in required_metrics)

    eligible = bool(checks) and all(checks.values())
    return {
        "status": "PASS" if eligible else "INVALID_OR_INSUFFICIENT_BASELINE_PROVENANCE",
        "eligible": eligible,
        "checks": checks,
        "metrics": metrics if eligible else None,
        "state": registry.get("state"),
        "provenance": provenance,
        "samples": samples,
        "settled_gameweeks": sorted({int(x) for x in settled}),
    }


def validate_configured_baseline() -> dict[str, Any]:
    registry = load_json_config(BASELINE_CONFIG)
    manifest = load_json_config(MANIFEST_CONFIG)
    baselines = manifest.get("baselines") if isinstance(manifest.get("baselines"), dict) else {}
    expected_sha = str(baselines.get("production_main_sha") or "")
    expected_runtime = str(baselines.get("production_runtime_engine_version") or "") or None
    return validate_baseline_registry(
        registry,
        expected_production_sha=expected_sha,
        expected_runtime_engine_version=expected_runtime,
    )


def build_baseline_candidate(
    production_accuracy: dict[str, Any],
    runtime_manifest: dict[str, Any],
    *,
    accepted_production_sha: str,
) -> dict[str, Any]:
    overall = production_accuracy.get("overall") if isinstance(production_accuracy.get("overall"), dict) else {}
    settled = production_accuracy.get("settled_gameweeks") if isinstance(production_accuracy.get("settled_gameweeks"), list) else []
    return {
        "status": "CANDIDATE_UNVALIDATED",
        "provenance": {
            "source_branch": "main",
            "artifact_branch": "runtime-data",
            "model": production_accuracy.get("model"),
            "source_main_sha": runtime_manifest.get("source_commit"),
            "runtime_engine_version": runtime_manifest.get("engine_version"),
            "runtime_schema_version": runtime_manifest.get("schema_version"),
            "retrospective_proxy": False,
            "counts_toward_predictive_accuracy": True,
            "posthoc_reconstruction": False,
            "accepted_production_sha_at_candidate_build": accepted_production_sha,
            "accuracy_generated_at": production_accuracy.get("generated_at"),
            "runtime_published_at": runtime_manifest.get("published_at"),
        },
        "settled_gameweeks": sorted({int(x) for x in settled}),
        "samples": {
            "player_gw": _i(overall.get("sample_size")),
            "starter": _i(overall.get("starter_sample_size")),
            "clean_sheet": _i(overall.get("clean_sheet_sample_size")),
        },
        "metrics": {
            "points_mae": overall.get("points_mae"),
            "xmins_mae": overall.get("xmins_mae"),
            "starter_brier": overall.get("starter_brier"),
            "clean_sheet_brier": overall.get("clean_sheet_brier"),
            "spearman": overall.get("spearman"),
        },
    }
