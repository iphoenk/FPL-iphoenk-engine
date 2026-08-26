from datetime import datetime, timezone

from src.engines.price_radar import (
    _official_projection_health,
    _price_row,
    build_trajectory,
)


def test_official_price_fields_are_normalised():
    player = {
        "id": 8,
        "web_name": "Calafiori",
        "team": 1,
        "element_type": 2,
        "now_cost": 55,
        "selected_by_percent": "40.5",
        "transfers_in_event": 134949,
        "transfers_out_event": 12325,
        "price_change_percent": 65.0,
        "price_change_hourly_rate": 804,
        "price_change_projections": [
            {"offset": 0, "projected_percent": "65.0", "likelihood": 3},
            {"offset": 1, "projected_percent": "79.5", "likelihood": 3},
        ],
    }
    row = _price_row(player, 10_000_000)
    assert row["official_progress_pct"] == 65.0
    assert row["official_hourly_rate_pct"] == 8.04
    assert row["official_projections"][0]["likelihood_label"] == "VERY_LIKELY_RISE"


def test_static_offset_zero_projection_is_guarded():
    health = _official_projection_health(
        65.0,
        8.04,
        [{"offset": 0, "projected_percent": 65.0, "likelihood": 3}],
        12.0,
    )
    assert health == "SUSPECT_STATIC_OFFSET0"


def test_trajectory_calculates_velocity_acceleration_and_change_date():
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    rows = [{
        "element": 8,
        "name": "Calafiori",
        "team_id": 1,
        "element_type": 2,
        "now_cost": 55,
        "ownership_pct": 40.5,
        "net_transfers": 120000,
        "momentum": 0.03,
        "official_progress_pct": 70.0,
        "official_hourly_rate_raw": 400,
        "official_hourly_rate_pct": 4.0,
        "official_projections": [{"offset": 0, "projected_percent": 70.0, "likelihood": 3}],
        "official_locked_until": None,
        "official_calibrating": False,
    }]
    previous = {"players": {"8": {
        "timestamp": "2026-08-25T10:00:00+00:00",
        "official_progress_pct": 62.0,
        "official_hourly_rate_pct": 2.0,
        "net_transfers": 100000,
        "now_cost": 55,
    }}}
    enriched, state = build_trajectory(rows, previous, now)
    item = enriched[0]
    assert item["observed_progress_velocity_pct_per_hour"] == 4.0
    assert item["acceleration_pct_per_hour2"] == 1.0
    assert item["trajectory"] == "ACCELERATING"
    assert item["trajectory_eta_hours"] == 7.5
    assert item["predicted_change_deadline"] is not None
    assert item["prediction_source"] == "TRAJECTORY_RATE"
    assert state["players"]["8"]["official_progress_pct"] == 70.0
