"""E04: temporal and coverage honesty of model evidence (audit 2026-10-25).

Reuses the fixtures of test_model_evidence_calibration so there is one canonical example.
"""
from __future__ import annotations

import pytest

from src.engines.v12_model_evidence import ModelEvidenceError, prediction_calibration_metrics
from tests.test_model_evidence_calibration import _actual_rows, _binding, _forecast_rows


def test_calibration_cutoff_after_generation_time_is_currently_accepted_known_gap():
    # NOT_FIXED by design: a hard guard (cutoff <= generated_at) fail-closed 34 mini-league overlay replay tests,
    # because shipped config cutoffs (2026-09-20) postdate the fixture run times (2026-09-19). Historical replays
    # legitimately bind a later configured cutoff. Enforcing this needs a replay-aware design, not a blanket guard.
    # This test pins today's behaviour so the gap stays visible and any change is deliberate.
    b = _binding(calibration_cutoff="2026-09-19T11:46:00Z", generated_at="2026-09-19T11:45:00Z")
    assert b["calibration_cutoff"] > b["generated_at"]


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
