"""E04: temporal and coverage honesty of model evidence (audit 2026-10-25).

Reuses the fixtures of test_model_evidence_calibration so there is one canonical example.
"""
from __future__ import annotations

import pytest

from src.engines.v12_model_evidence import ModelEvidenceError, prediction_calibration_metrics
from tests.test_model_evidence_calibration import _actual_rows, _binding, _forecast_rows


def test_calibration_cutoff_after_generation_time_is_rejected():
    # A calibration fitted on data newer than the run it is attached to is hindsight, not calibration.
    with pytest.raises(ModelEvidenceError):
        _binding(calibration_cutoff="2026-09-19T11:46:00Z", generated_at="2026-09-19T11:45:00Z")


def test_calibration_cutoff_at_or_before_generation_time_is_accepted():
    assert _binding(calibration_cutoff="2026-09-19T11:45:00Z", generated_at="2026-09-19T11:45:00Z")["calibration_cutoff"]
    assert _binding()["calibration_cutoff"] < _binding()["generated_at"]


def test_configured_production_cutoffs_precede_any_run_generated_now():
    import json
    from pathlib import Path

    for name in ("v12_monte_carlo", "v12_package_utility", "v12_mini_league_overlay", "v12_lineup_optimizer"):
        cfg = json.loads(Path(f"config/intelligence/{name}.json").read_text(encoding="utf-8"))
        # Guard against enabling the new rule while a shipped config would fail closed.
        assert cfg["calibration_cutoff"] < "2026-10-01T00:00:00Z", name


def test_forecast_without_settled_actual_is_counted_not_silently_dropped():
    forecasts = _forecast_rows() + [{**_forecast_rows()[0], "element": 3}]
    out = prediction_calibration_metrics(forecasts, _actual_rows())
    assert out["overall"]["sample_size"] == 2
    cov = out["coverage"]
    assert cov["forecast_count"] == 3
    assert cov["settled_count"] == 2
    assert cov["unsettled_count"] == 1
    assert cov["unsettled_elements"] == [3]


def test_full_settlement_reports_complete_coverage():
    cov = prediction_calibration_metrics(_forecast_rows(), _actual_rows())["coverage"]
    assert (cov["forecast_count"], cov["settled_count"], cov["unsettled_count"]) == (2, 2, 0)
    assert cov["unsettled_elements"] == []
