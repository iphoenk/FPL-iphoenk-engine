from __future__ import annotations

from pathlib import Path

from src.engines.price_radar import MODEL_THRESHOLD
from src.engines.v12_report_orchestration import (
    build_actionable_price_radar,
    build_price20,
    weather_report_time_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"


def _row(element_id: int, projected: float, *, likelihood: int = 3, offset1: float | None = None, offset2: float | None = None) -> dict:
    p1 = projected if offset1 is None else offset1
    p2 = projected if offset2 is None else offset2
    return {
        "id": element_id,
        "web_name": f"P{element_id}",
        "team": ((element_id - 1) % 20) + 1,
        "element_type": ((element_id - 1) % 4) + 1,
        "now_cost": 50 + (element_id % 20),
        "selected_by_percent": "1.0",
        "transfers_in_event": 1000 + element_id,
        "transfers_out_event": 500 + element_id,
        "price_change_percent": f"{projected:.1f}",
        "price_change_hourly_rate": 10 if projected > 0 else -10 if projected < 0 else 0,
        "price_change_projections": [
            {"offset": 0, "projected_percent": projected, "likelihood": likelihood},
            {"offset": 1, "projected_percent": p1, "likelihood": likelihood},
            {"offset": 2, "projected_percent": p2, "likelihood": likelihood},
        ],
        "price_change_locked_until": None,
        "price_change_calibrating": False,
    }


def _artifact(rows: list[dict], *, checked_at: str = "2026-09-20T10:28:23.609531+00:00") -> dict:
    return {"health": "GREEN", "checked_at": checked_at, "data": {"players": rows}}


def _crossing_artifact() -> dict:
    rows = []
    for index in range(25):
        rows.append(_row(1000 + index, 130.0 - index))
    for index in range(25):
        rows.append(_row(2000 + index, -130.0 + index))
    return _artifact(rows)


def _owned15() -> list[dict]:
    return [
        {
            "element_id": 1000 + index,
            "name": f"Owned-{index}",
            "current_price": 55 + index,
            "selling_price": 54 + index,
        }
        for index in range(15)
    ]


# PRICE 1
def test_positive_projected_percent_maps_to_rise() -> None:
    result = build_price20(predictor_artifact=_artifact([_row(i, 120 + i) for i in range(1, 25)]), direction="RISE")
    assert result["rows"][0]["direction"] == "RISE"


# PRICE 2
def test_negative_projected_percent_maps_to_fall() -> None:
    result = build_price20(predictor_artifact=_artifact([_row(i, -120 - i) for i in range(1, 25)]), direction="FALL")
    assert result["rows"][0]["direction"] == "FALL"


# PRICE 3
def test_zero_projected_percent_maps_to_neutral() -> None:
    result = build_price20(predictor_artifact=_artifact([_row(i, 0.0) for i in range(1, 25)]), direction="RISE")
    assert all(row["direction"] == "NEUTRAL" for row in result["rows"])


# PRICE 4
def test_rise_sort_desc_then_element_id_asc() -> None:
    rows = [_row(i, 110.0) for i in range(1, 25)]
    rows[0]["id"], rows[1]["id"] = 99, 98
    result = build_price20(predictor_artifact=_artifact(rows), direction="RISE")
    assert [row["element_id"] for row in result["rows"][:2]] == [98, 99]


# PRICE 5
def test_fall_sort_asc_then_element_id_asc() -> None:
    rows = [_row(i, -110.0) for i in range(1, 25)]
    rows[0]["id"], rows[1]["id"] = 99, 98
    result = build_price20(predictor_artifact=_artifact(rows), direction="FALL")
    assert [row["element_id"] for row in result["rows"][:2]] == [98, 99]


# PRICE 6
def test_current_price_is_fact() -> None:
    row = build_price20(predictor_artifact=_crossing_artifact(), direction="RISE")["rows"][0]
    assert row["price_fact"] == "FACT"
    assert isinstance(row["current_price"], float)


# PRICE 7
def test_predictor_is_model() -> None:
    row = build_price20(predictor_artifact=_crossing_artifact(), direction="RISE")["rows"][0]
    assert row["predictor_classification"] == "MODEL"


# PRICE 8
def test_official_price_cycle_is_london_midnight() -> None:
    row = build_price20(predictor_artifact=_crossing_artifact(), direction="RISE")["rows"][0]
    assert "T00:00:00+01:00" in row["next_official_price_cycle_uk"]


# PRICE 9
def test_bst_cycle_converts_to_0600_wib() -> None:
    row = build_price20(predictor_artifact=_crossing_artifact(), direction="RISE")["rows"][0]
    assert "T06:00:00+07:00" in row["next_official_price_cycle_wib"]


# PRICE 10
def test_gmt_cycle_converts_to_0700_wib() -> None:
    art = _artifact(_crossing_artifact()["data"]["players"], checked_at="2026-12-20T10:00:00+00:00")
    row = build_price20(predictor_artifact=art, direction="RISE")["rows"][0]
    assert "T07:00:00+07:00" in row["next_official_price_cycle_wib"]


# PRICE 11
def test_wib_cycle_is_not_permanently_hardcoded_to_0600() -> None:
    bst = build_price20(predictor_artifact=_crossing_artifact(), direction="RISE")["rows"][0]
    gmt_art = _artifact(_crossing_artifact()["data"]["players"], checked_at="2026-12-20T10:00:00+00:00")
    gmt = build_price20(predictor_artifact=gmt_art, direction="RISE")["rows"][0]
    assert bst["next_official_price_cycle_wib"] != gmt["next_official_price_cycle_wib"]


# PRICE 12
def test_predictor_observation_is_separate_from_official_execution_cycle() -> None:
    row = build_price20(predictor_artifact=_crossing_artifact(), direction="RISE")["rows"][0]
    assert row["evidence_timestamp"] == "2026-09-20T10:28:23.609531+00:00"
    assert row["next_official_price_cycle_uk"] != row["evidence_timestamp"]


# PRICE 13
def test_unsupported_eta_remains_unavailable() -> None:
    art = _artifact([_row(i, 50.0, offset1=60.0, offset2=70.0) for i in range(1, 25)])
    result = build_price20(predictor_artifact=art, direction="RISE")
    assert result["state"] == "DEGRADED"
    assert all(row["estimated_change_window"] == "UNAVAILABLE" for row in result["rows"])
    assert all(row["eta_reason"] for row in result["rows"])


# PRICE 14
def test_eta_uses_existing_governed_threshold_not_new_threshold() -> None:
    assert MODEL_THRESHOLD == 100.0
    art = _artifact([_row(i, 99.9, offset1=99.9, offset2=99.9) for i in range(1, 25)])
    row = build_price20(predictor_artifact=art, direction="RISE")["rows"][0]
    assert row["governed_threshold_percent"] == MODEL_THRESHOLD
    assert row["estimated_change_window"] == "UNAVAILABLE"


# PRICE 15
def test_complete_rise20_rows_have_full_visible_contract() -> None:
    result = build_price20(predictor_artifact=_crossing_artifact(), direction="RISE")
    assert result["state"] == "COMPLETE"
    assert result["available_count"] == 20
    required = set(result["visible_contract_fields"])
    assert all(required <= set(row) for row in result["rows"])


# PRICE 16
def test_complete_fall20_rows_have_full_visible_contract() -> None:
    result = build_price20(predictor_artifact=_crossing_artifact(), direction="FALL")
    assert result["state"] == "COMPLETE"
    assert result["available_count"] == 20
    required = set(result["visible_contract_fields"])
    assert all(required <= set(row) for row in result["rows"])


# PRICE 17
def test_missing_cycle_timestamp_degrades_even_with_exact20() -> None:
    art = _crossing_artifact()
    art.pop("checked_at")
    result = build_price20(predictor_artifact=art, direction="RISE")
    assert result["available_count"] == 20
    assert result["state"] == "DEGRADED"


# PRICE 18
def test_all15_price_radar_stays_exact15() -> None:
    result = build_actionable_price_radar(owned15=_owned15(), predictor_artifact=_crossing_artifact())
    assert result["available_count"] == 15
    assert result["identity_complete"] is True


# PRICE 19
def test_real_schema_all15_direction_uses_offset_zero() -> None:
    result = build_actionable_price_radar(owned15=_owned15(), predictor_artifact=_crossing_artifact())
    assert all(row["predictor_direction"] == "RISE" for row in result["rows"])


# PRICE 20
def test_price_movement_alone_cannot_create_act() -> None:
    result = build_actionable_price_radar(owned15=_owned15(), predictor_artifact=_crossing_artifact())
    assert result["price_alone_may_create_act"] is False
    assert all("ACT" not in str(row["decision_implication"]) for row in result["rows"])


def _weather_payload(impact: str = "NORMAL") -> dict:
    return {
        "fixture": "AAA-BBB",
        "condition": "Cloudy",
        "temperature_c": 17,
        "precipitation_chance_pct": 20,
        "wind_kmh": 14,
        "fpl_impact": impact,
        "weather_evidence_timestamp": "2026-09-20T10:30:00+00:00",
    }


# WEATHER 21
def test_weather_is_report_time_not_v6() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=_weather_payload(),
        lookup_accessible=True,
    )
    assert result["source_layer"] == "REPORT_TIME"
    assert result["v6_weather_required"] is False


# WEATHER 22
def test_canonical_requires_simple_visible_weather_block() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")
    assert "Minimum visible WEATHER row" in canonical
    assert "DEEP / Deadline / Final Review" in canonical


# WEATHER 23
def test_normal_weather_remains_normal_context() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=_weather_payload("NORMAL"),
        lookup_accessible=True,
    )
    assert result["visible_row"]["fpl_impact"] == "NORMAL"


# WEATHER 24
def test_missing_weather_source_degrades_weather_only() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=None,
        lookup_accessible=False,
        failure_reason="source inaccessible",
    )
    assert result["state"] == "UNAVAILABLE"
    assert result["degradation_reason"] == "source inaccessible"


# WEATHER 25
def test_weather_failure_does_not_become_report_or_v6_failure() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=None,
        lookup_accessible=False,
    )
    assert result["v6_weather_required"] is False
    assert result["weather_may_independently_create_action"] is False
    assert "must not collapse" in CANONICAL.read_text(encoding="utf-8")


# WEATHER 26
def test_weather_does_not_mutate_xpts() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB", venue="Example Ground", kickoff="K", weather=_weather_payload(), lookup_accessible=True
    )
    assert result["weather_adjusted_xpts"] is False


# WEATHER 27
def test_weather_does_not_mutate_pstart_or_xmins() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB", venue="Example Ground", kickoff="K", weather=_weather_payload(), lookup_accessible=True
    )
    assert result["weather_mutates_p_start"] is False
    assert result["weather_mutates_xmins"] is False


# WEATHER 28
def test_visible_weather_contract_creates_no_new_weather_model_owner() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB", venue="Example Ground", kickoff="K", weather=_weather_payload(), lookup_accessible=True
    )
    assert result["new_weather_model_created"] is False


# WEATHER 29
def test_visible_weather_row_has_required_fields() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=_weather_payload(),
        lookup_accessible=True,
    )
    required = {
        "fixture",
        "venue",
        "kickoff",
        "condition",
        "temperature_c",
        "precipitation_chance_pct",
        "wind_kmh",
        "fpl_impact",
    }
    assert required <= set(result["visible_row"])
    assert result["state"] == "COMPLETE"


# WEATHER 30
def test_visible_weather_row_hides_raw_provider_plumbing() -> None:
    payload = {**_weather_payload(), "provider": "example", "latitude": 1.2, "longitude": 3.4, "raw": {"x": 1}}
    result = weather_report_time_evidence(
        fixture="AAA-BBB", venue="Example Ground", kickoff="K", weather=payload, lookup_accessible=True
    )
    visible = result["visible_row"]
    assert result["raw_provider_plumbing_visible"] is False
    assert {"provider", "latitude", "longitude", "raw"}.isdisjoint(visible)
