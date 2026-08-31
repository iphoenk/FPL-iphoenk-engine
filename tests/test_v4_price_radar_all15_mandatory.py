from __future__ import annotations

import pytest

from src.engines.v4_challenger_serving_composition import _price_radar_payload


def _price(element: int, *, direction: str = "STABLE", urgency: str = "LOW") -> dict:
    return {
        "element_id": element,
        "player_name": f"P{element}",
        "team_id": 1,
        "position": "DEF",
        "current_price": 4.5,
        "ownership_percent": 1.0,
        "confirmed_price_change": None,
        "current_progress_percent": 55.0,
        "price_change_hourly_rate": 2.0,
        "projection_offset_0_percent": 60.0,
        "projection_offset_0_likelihood": 2,
        "projection_offset_0_at": "2026-09-01T06:00:00+07:00",
        "projection_offset_1_percent": 70.0,
        "projection_offset_1_likelihood": 2,
        "projection_offset_1_at": "2026-09-02T06:00:00+07:00",
        "projection_offset_2_percent": 80.0,
        "projection_offset_2_likelihood": 3,
        "projection_offset_2_at": "2026-09-03T06:00:00+07:00",
        "price_change_locked_until": None,
        "price_change_calibrating": False,
        "direction": direction,
        "next_official_price_update_at": "2026-09-01T06:00:00+07:00",
        "eta_to_next_price_update_seconds": 28800,
        "eta_human": "sekitar 8 jam",
        "predicted_change_cycle": "NEXT_CYCLE" if direction != "STABLE" else "NONE",
        "predicted_change_at": None,
        "model_urgency": urgency,
        "source": "OFFICIAL_FPL",
        "provider": "OFFICIAL_FPL_NATIVE",
        "observed_at": "2026-08-31T14:00:00+00:00",
        "fetched_at": "2026-08-31T14:00:00+00:00",
        "fetched_at_distinct": True,
        "age_seconds": 60,
        "freshness_seconds": 60,
        "freshness_state": "FRESH",
        "trajectory_basis": "NATIVE",
        "predictor_serving_state": "AVAILABLE",
        "raw_evidence_state": "AVAILABLE",
        "schema_version": 1,
        "raw_payload_hash": "abc",
        "confidence": "HIGH",
        "fallback_reason": None,
        "evidence_state": "AVAILABLE",
        "narrative": "test",
    }


def _challenger(mandatory: list[int] | None = None) -> dict:
    ids = list(mandatory or [])
    return {
        "owned_screening": [{"element": element, "name": f"P{element}"} for element in range(1, 16)],
        "projected_value_market_discovery": {
            "contract": "V4_PROJECTED_VALUE_MARKET_DISCOVERY_V1",
            "mandatory_candidate_ids": ids,
            "evaluated_mandatory_candidate_ids": ids,
            "mandatory_candidate_coverage_complete": True,
        },
    }


def _prices(extra: list[int] | None = None) -> dict:
    ids = list(range(1, 16)) + list(extra or [])
    return {
        "source": "OFFICIAL_FPL",
        "health": {"status": "PASS"},
        "contract": {"model_id": "official_price_radar_v3"},
        "players": [_price(element) for element in ids],
    }


def test_v4_price_radar_serves_predictor_detail_for_all15_owned() -> None:
    radar = _price_radar_payload(_challenger(), _prices())

    assert radar["owned_count"] == 15
    assert {row["element"] for row in radar["owned"]} == set(range(1, 16))
    assert all("current_progress_percent" in row for row in radar["owned"])
    assert all("next_official_price_update_at" in row for row in radar["owned"])
    assert radar["price_only_execution_authorized"] is False


def test_v4_mandatory_challengers_come_only_from_canonical_discovery_ids() -> None:
    challenger = _challenger([88])
    challenger["comparisons"] = [
        {
            "player_in": {"element": 99, "name": "P99"},
            "decision": "CHANGE",
            "challenger_type": "EMERGING_CHALLENGER",
        }
    ]
    radar = _price_radar_payload(challenger, _prices([88, 99]))

    assert radar["mandatory_candidate_ids"] == [88]
    assert [row["element"] for row in radar["mandatory_high_value_challengers"]] == [88]
    assert radar["candidate_authority"] == "V4_PROJECTED_VALUE_MARKET_DISCOVERY_V1"
    assert radar["mandatory_high_value_challengers"][0]["mandatory_challenger_reason"] == "CANONICAL_PROJECTED_VALUE_MARKET_DISCOVERY"


def test_v4_mandatory_ids_are_deduplicated_without_reselection() -> None:
    challenger = _challenger([88, 88, 89])
    challenger["projected_value_market_discovery"]["evaluated_mandatory_candidate_ids"] = [88, 89]
    radar = _price_radar_payload(challenger, _prices([88, 89]))

    assert radar["mandatory_candidate_ids"] == [88, 89]
    assert [row["element"] for row in radar["mandatory_high_value_challengers"]] == [88, 89]


def test_v4_price_radar_fails_closed_if_owned_predictor_row_missing() -> None:
    prices = _prices()
    prices["players"] = [row for row in prices["players"] if row["element_id"] != 15]

    with pytest.raises(RuntimeError, match="ALL15 predictor coverage incomplete"):
        _price_radar_payload(_challenger(), prices)


def test_v4_price_radar_fails_closed_if_mandatory_predictor_row_missing() -> None:
    with pytest.raises(RuntimeError, match="mandatory challenger predictor coverage incomplete"):
        _price_radar_payload(_challenger([88]), _prices())


def test_v4_price_radar_fails_closed_if_discovery_marks_unevaluated_mandatory() -> None:
    challenger = _challenger([88])
    challenger["projected_value_market_discovery"]["evaluated_mandatory_candidate_ids"] = []

    with pytest.raises(RuntimeError, match="evaluation coverage inconsistent"):
        _price_radar_payload(challenger, _prices([88]))
