from datetime import datetime, timedelta, timezone

from src.v5 import price_calibration as pc
from src.v5.price_service import build_price_snapshot


def _bootstrap(*, now_cost: int = 56) -> dict:
    return {
        "total_players": 1_000_000,
        "elements": [
            {
                "id": 1,
                "web_name": "Player",
                "team": 1,
                "element_type": 3,
                "now_cost": now_cost,
                "selected_by_percent": "10.0",
                "transfers_in_event": 20_000,
                "transfers_out_event": 1_000,
                "price_change_percent": 90.0,
                "price_change_hourly_rate": 100.0,
                "price_change_projections": [],
                "price_change_locked_until": None,
                "price_change_calibrating": False,
            }
        ],
    }


def test_realized_direction_and_timing_use_prior_prediction():
    now = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    prior = {
        "now_cost": 55,
        "prediction": {
            "risk_direction": "RISE",
            "predicted_change_deadline": (now - timedelta(hours=1)).isoformat(),
            "prediction_source": "TRAJECTORY_RATE",
            "official_projection_health": "PROGRESS_ONLY",
        },
    }
    event = pc._event_for_change(1, prior, {"now_cost": 56}, now)
    assert event is not None
    assert event["realized_direction"] == "RISE"
    assert event["direction_correct"] is True
    assert event["timing_error_hours_observation_bound"] == 1.0
    assert "not claimed as the exact" in event["note"]


def test_missed_window_requires_grace_and_deduplicates_same_deadline():
    now = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    deadline = (now - timedelta(hours=13)).isoformat()
    prior = {
        "now_cost": 55,
        "prediction": {"risk_direction": "RISE", "predicted_change_deadline": deadline},
        "calibration": {},
    }
    assert pc._miss_event(1, prior, {"now_cost": 55}, now, 12.0) is not None
    prior["calibration"]["last_miss_deadline"] = deadline
    assert pc._miss_event(1, prior, {"now_cost": 55}, now, 12.0) is None


def test_summary_stays_warmup_before_minimum_sample():
    rows = [
        {
            "official_projections": [{}],
            "official_projection_health": "SUSPECT_STATIC_OFFSET0",
            "prediction_source": "TRAJECTORY_RATE",
        }
    ]
    events = [
        {
            "event": "REALIZED_PRICE_CHANGE",
            "realized_direction": "RISE",
            "direction_correct": True,
            "prediction_source": "TRAJECTORY_RATE",
        }
    ]
    summary = pc._summary(
        events,
        rows,
        {
            "minimum_samples_for_calibrated_health": 20,
            "healthy_direction_accuracy": 0.70,
            "warning_direction_accuracy": 0.55,
            "suspect_static_ratio_warning": 0.50,
            "timing_error_warning_hours": 24.0,
        },
    )
    assert summary["status"] == "WARMUP"
    assert summary["direction_accuracy"] == 1.0
    assert summary["governance"]["no_accuracy_claim_before_minimum_sample"] is True


def test_price_service_persists_prediction_and_calibration_state():
    now = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    previous = {
        "players": {
            "1": {
                "timestamp": (now - timedelta(hours=1)).isoformat(),
                "now_cost": 55,
                "official_progress_pct": 80.0,
                "official_hourly_rate_pct": 0.5,
                "prediction": {
                    "risk_direction": "RISE",
                    "predicted_change_deadline": (now - timedelta(hours=1)).isoformat(),
                    "prediction_source": "TRAJECTORY_RATE",
                    "official_projection_health": "PROGRESS_ONLY",
                },
                "calibration": {},
            }
        },
        "calibration": {"events": []},
    }
    result = build_price_snapshot(_bootstrap(now_cost=56), previous_state=previous, now=now)
    state = result["trajectory_state"]
    assert state["players"]["1"]["prediction"]["risk_direction"] == "RISE"
    assert state["calibration"]["owner"] == "price"
    assert state["calibration"]["summary"]["realized_change_samples"] == 1
    assert result["prices"]["model_health"] == state["calibration"]["summary"]
    assert result["calibration"] == state["calibration"]
