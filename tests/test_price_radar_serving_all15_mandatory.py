from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.report_enrichment import _hydrate_price_radar, _source_availability


def _price_row(element: int, *, direction: str = "STABLE", urgency: str = "LOW") -> dict:
    return {
        "element_id": element,
        "player_name": f"P{element}",
        "team_id": 1,
        "position": "DEF",
        "current_price": 4.5,
        "ownership_percent": 1.0,
        "confirmed_price_change": None,
        "direction": direction,
        "current_progress_percent": 20.0,
        "trajectory": "FLAT",
        "price_change_hourly_rate": 0.0,
        "projection_offset_0_percent": 20.0,
        "projection_offset_1_percent": 25.0,
        "projection_offset_2_percent": 30.0,
        "predicted_change_cycle": "NONE",
        "predicted_change_at": None,
        "next_official_price_update_at": "2026-09-01T06:00:00+07:00",
        "eta_human": "sekitar 8 jam",
        "model_urgency": urgency,
        "confidence": "HIGH",
        "source": "OFFICIAL_FPL",
        "observed_at": "2026-08-31T14:00:00+00:00",
        "freshness_seconds": 60,
        "evidence_state": "AVAILABLE",
        "narrative": "test",
    }


def _team() -> dict:
    return {"team_value_ledger": [{"element": element} for element in range(1, 16)]}


def test_price_radar_serves_predictor_detail_for_all_15_owned() -> None:
    user = {"price_radar": {}}
    prices = {"players": [_price_row(element) for element in range(1, 16)]}
    coverage = _hydrate_price_radar(user, _team(), prices, {}, {"positions": {}}, {})

    radar = user["price_radar"]
    assert coverage["owned_complete"] is True
    assert radar["owned_count"] == 15
    assert len(radar["owned"]) == 15
    assert {row["element"] for row in radar["owned"]} == set(range(1, 16))
    assert all("progress_pct" in row for row in radar["owned"])
    assert all("next_official_price_update_at" in row for row in radar["owned"])
    assert all(row["threshold_crossing_is_not_confirmation"] is True for row in radar["owned"])


def test_market_urgent_non_owned_candidate_is_mandatory_even_outside_visible_watchlist() -> None:
    challenger = _price_row(99, direction="RISE", urgency="HIGH")
    user = {"price_radar": {}}
    prices = {"players": [_price_row(element) for element in range(1, 16)] + [challenger]}
    price_alerts = {"market_watch_candidates": [challenger]}

    _hydrate_price_radar(user, _team(), prices, price_alerts, {"positions": {}}, {})

    rows = user["price_radar"]["mandatory_high_value_challengers"]
    assert len(rows) == 1
    assert rows[0]["element"] == 99
    assert rows[0]["mandatory_challenger_reason"] == "MARKET_URGENT_SCREEN_REQUIRED"
    assert rows[0]["action"] == "REVIEW_NOW"
    assert rows[0]["predicted_change_at"] is None
    assert rows[0]["next_official_price_update_at"] == "2026-09-01T06:00:00+07:00"


def test_governed_material_challenger_gets_price_detail_without_price_alert_threshold() -> None:
    challenger = _price_row(88, direction="STABLE", urgency="LOW")
    user = {"price_radar": {}}
    prices = {"players": [_price_row(element) for element in range(1, 16)] + [challenger]}
    comparator = {
        "top_comparisons": [
            {
                "player_in": {"element": 88, "name": "P88"},
                "state": "REVIEW",
                "challenger_type": "EMERGING_CHALLENGER",
                "actionability": {"level": "MATERIAL_UPGRADE"},
            }
        ]
    }

    _hydrate_price_radar(user, _team(), prices, {}, {"positions": {}}, comparator)

    rows = user["price_radar"]["mandatory_high_value_challengers"]
    assert len(rows) == 1
    assert rows[0]["element"] == 88
    assert rows[0]["mandatory_challenger_reason"] == "GOVERNED_CHALLENGER"
    assert rows[0]["action"] == "WATCH"


def test_owned_price_coverage_fails_closed_when_predictor_row_is_missing() -> None:
    user = {"price_radar": {}}
    prices = {"players": [_price_row(element) for element in range(1, 15)]}
    with pytest.raises(RuntimeError, match="coverage missing"):
        _hydrate_price_radar(user, _team(), prices, {}, {"positions": {}}, {})


def test_livefpl_is_retired_from_v3_source_serving() -> None:
    block = _source_availability({"sources": [{"id": "livefpl", "name": "LiveFPL", "reachable": True}]})
    serialized = str(block).lower()
    assert "livefpl" not in serialized


def test_p0_artifact_contract_budgets_governed_all15_and_mandatory_price_detail() -> None:
    registry = json.loads(Path("config/report_artifact_registry.json").read_text())
    consumer = registry["consumer_contract"]
    artifacts = registry["artifacts"]
    governance = registry["governance"]

    assert consumer["price_radar_requires_all15_predictor_detail"] is True
    assert consumer["price_radar_requires_mandatory_challenger_detail"] is True
    assert governance["p0_payload_budget_expanded_for_governed_all15_and_mandatory_challenger_price_evidence"] is True
    assert artifacts["decision_brief"]["max_bytes"] >= 100_000
    assert artifacts["deep_review_payload"]["max_bytes"] >= 300_000
    assert artifacts["user_report"]["max_bytes"] >= 300_000
