from __future__ import annotations

import json
import math

from src.engines.player_features import _aggregate_advanced
from src.models.historical_projection import _defensive_contribution_model
from src.models.projection_components import expected_defensive_contribution_points
from src.rules import POSITION_TO_ELEMENT_TYPE
from src.utils import ROOT


def _policy() -> dict:
    payload = json.loads((ROOT / "config" / "intelligence" / "player_features.json").read_text(encoding="utf-8"))
    return payload["defensive_contribution"]


def _full_90() -> dict:
    return {
        "start_probability": 1.0,
        "bench_probability": 0.0,
        "starter_minutes_if_start": 90.0,
        "bench_minutes_if_used": 18.0,
    }


def test_position_fallback_reproduces_legacy_expected_points_at_90():
    references = _policy()["legacy_expected_points90_reference"]
    for position in ("DEF", "MID", "FWD"):
        model = _defensive_contribution_model(
            POSITION_TO_ELEMENT_TYPE[position], position, {}, _policy()
        )
        points, probability = expected_defensive_contribution_points(_full_90(), model)
        assert probability > 0
        assert math.isclose(points, float(references[position]), rel_tol=0.0, abs_tol=1e-6)
        assert model["source"] == "position_count_rate_prior_fallback"


def test_player_defensive_evidence_moves_projection_above_position_fallback():
    position = "DEF"
    fallback = _defensive_contribution_model(
        POSITION_TO_ELEMENT_TYPE[position], position, {}, _policy()
    )
    evidence = {
        "advanced_current": {
            "minutes": 900.0,
            "dc_reconstructed_per90": 12.0,
            "sample_quality": "ESTABLISHED",
            "dc_threshold_hits": 7,
            "dc_threshold_hit_rate": 0.7,
        }
    }
    player_model = _defensive_contribution_model(
        POSITION_TO_ELEMENT_TYPE[position], position, evidence, _policy()
    )
    fallback_points, _ = expected_defensive_contribution_points(_full_90(), fallback)
    player_points, _ = expected_defensive_contribution_points(_full_90(), player_model)
    assert player_model["count_rate90"] > fallback["count_rate90"]
    assert player_points > fallback_points
    assert player_model["source"] == "player_feature_shrunk_to_position_prior"
    assert player_model["observed_threshold_hits"] == 7


def test_threshold_probability_is_not_linear_minutes_scaling():
    position = "DEF"
    model = _defensive_contribution_model(
        POSITION_TO_ELEMENT_TYPE[position], position, {}, _policy()
    )
    full_points, _ = expected_defensive_contribution_points(_full_90(), model)
    half_minutes = {
        "start_probability": 1.0,
        "bench_probability": 0.0,
        "starter_minutes_if_start": 45.0,
        "bench_minutes_if_used": 18.0,
    }
    half_points, _ = expected_defensive_contribution_points(half_minutes, model)
    assert half_points < full_points
    assert not math.isclose(half_points, full_points * 0.5, rel_tol=0.05, abs_tol=0.01)


def test_goalkeeper_is_ineligible_for_defensive_contribution_points():
    model = _defensive_contribution_model(POSITION_TO_ELEMENT_TYPE["GK"], "GK", {}, _policy())
    points, probability = expected_defensive_contribution_points(_full_90(), model)
    assert model["eligible"] is False
    assert points == 0.0
    assert probability == 0.0


def test_player_feature_aggregation_records_threshold_hit_evidence():
    rows = [
        {"minutes_played": 90, "start_min": 0, "clearances": 5, "blocks": 2, "interceptions": 2, "tackles": 2, "recoveries": 1},
        {"minutes_played": 90, "start_min": 0, "clearances": 2, "blocks": 1, "interceptions": 1, "tackles": 1, "recoveries": 5},
    ]
    out = _aggregate_advanced(rows, "DEF")
    assert out["dc_threshold"] == 10
    assert out["dc_threshold_hits"] == 1
    assert out["dc_threshold_hit_rate"] == 0.5
    assert out["dc_reconstructed_total"] == 16.0
