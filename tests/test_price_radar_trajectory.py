from datetime import datetime, timezone

from src.engines.price_radar import (
    _official_projection_health,
    _price_row,
    _risk_direction,
    _trajectory_eta,
    build_trajectory,
)


def _player(**overrides):
    payload = {
        "id": 8,
        "first_name": "Riccardo",
        "second_name": "Calafiori",
        "web_name": "Calafiori",
        "team": 1,
        "element_type": 2,
        "now_cost": 55,
        "selected_by_percent": "40.5",
        "transfers_in": 200000,
        "transfers_in_event": 134949,
        "transfers_out": 30000,
        "transfers_out_event": 12325,
        "price_change_percent": 65.0,
        "price_change_hourly_rate": 804,
        "price_change_projections": [
            {"offset": 0, "projected_percent": "65.0", "likelihood": 3},
            {"offset": 1, "projected_percent": "108.0", "likelihood": 5},
            {"offset": 2, "projected_percent": "120.0", "likelihood": 5},
        ],
        "price_change_locked_until": None,
        "price_change_calibrating": False,
    }
    payload.update(overrides)
    return payload


def test_official_price_fields_preserve_raw_likelihood_without_invented_wording():
    row = _price_row(_player())
    assert row["current_progress_percent"] == 65.0
    assert row["price_change_hourly_rate"] == 804.0
    assert row["official_hourly_rate_pct"] == 8.04  # compatibility alias only
    assert row["projection_offset_0_likelihood"] == 3
    assert row["projection_offset_1_likelihood"] == 5
    assert "likelihood_label" not in row["official_projections"][0]
    assert row["official_likelihood_raw"] == {"offset_0": 3, "offset_1": 5, "offset_2": 5}


def test_projection_health_does_not_invent_static_projection_failure_semantics():
    health = _official_projection_health(
        65.0,
        8.04,
        [{"offset": 0, "projected_percent": 65.0, "likelihood": 3}],
        12.0,
    )
    assert health == "COMPLETE"


def test_near_fall_threshold_does_not_fabricate_crossing_time():
    now = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc)
    assert _risk_direction(-90.5, 0.02) == "FALL"
    eta, deadline = _trajectory_eta(now, -90.5, 0.02)
    assert eta is None
    assert deadline is None


def test_trajectory_retains_observed_velocity_but_never_generates_change_eta():
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    row = _price_row(_player(price_change_percent=70.0, price_change_hourly_rate=400))
    previous = {"players": {"8": {
        "timestamp": "2026-08-25T10:00:00+00:00",
        "official_progress_pct": 62.0,
        "official_hourly_rate_pct": 2.0,
        "net_transfers": 100000,
        "now_cost": 55,
    }}}
    enriched, state = build_trajectory([row], previous, now)
    item = enriched[0]
    assert item["observed_progress_velocity_pct_per_hour"] == 4.0
    assert item["acceleration_pct_per_hour2"] == 1.0
    assert item["trajectory"] == "ACCELERATING"
    assert item["trajectory_eta_hours"] is None
    assert item["trajectory_predicted_change_deadline"] is None
    assert item["predicted_change_cycle"] in {"NEXT_UPDATE", "PLUS_1_UPDATE", "PLUS_2_UPDATE", "NONE"}
    assert state["players"]["8"]["official_progress_pct"] == 70.0
