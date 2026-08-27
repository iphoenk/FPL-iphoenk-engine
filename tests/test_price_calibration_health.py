import json
from datetime import datetime, timedelta, timezone

from src.engines import price_calibration as pc


def _cfg():
    return {
        "calibration": {
            "max_events": 3,
            "miss_grace_hours": 6,
            "minimum_samples_for_calibrated_health": 2,
            "healthy_direction_accuracy": 0.7,
            "warning_direction_accuracy": 0.5,
            "suspect_static_ratio_warning": 0.5,
            "timing_error_warning_hours": 24,
        }
    }


def test_realized_direction_is_scored_from_prior_prediction():
    now = datetime.now(timezone.utc)
    prior = {
        "now_cost": 55,
        "prediction": {
            "risk_direction": "RISE",
            "predicted_change_deadline": (now - timedelta(hours=1)).isoformat(),
            "prediction_source": "TRAJECTORY_RATE",
            "official_projection_health": "SUSPECT_STATIC_OFFSET0",
        },
    }
    event = pc._event_for_change(1, prior, {"now_cost": 56}, now)
    assert event["realized_direction"] == "RISE"
    assert event["direction_correct"] is True
    assert event["timing_error_hours_observation_bound"] == 1.0
    assert "not the exact" in event["note"]


def test_miss_requires_deadline_grace_and_is_not_duplicate():
    now = datetime.now(timezone.utc)
    deadline = (now - timedelta(hours=8)).isoformat()
    prior = {
        "now_cost": 55,
        "prediction": {"risk_direction": "RISE", "predicted_change_deadline": deadline},
        "calibration": {},
    }
    assert pc._miss_event(1, prior, {"now_cost": 55}, now, 6) is not None
    prior["calibration"]["last_miss_deadline"] = deadline
    assert pc._miss_event(1, prior, {"now_cost": 55}, now, 6) is None


def test_summary_stays_warmup_before_minimum_sample_and_tracks_static_fallback():
    rows = [
        {"official_projections": [{}], "official_projection_health": "SUSPECT_STATIC_OFFSET0", "prediction_source": "TRAJECTORY_RATE"},
        {"official_projections": [{}], "official_projection_health": "LIVE", "prediction_source": "OFFICIAL_PROJECTION"},
    ]
    events = [{"realized_direction": "RISE", "direction_correct": True, "prediction_source": "TRAJECTORY_RATE"}]
    summary = pc._summary(events, rows, _cfg()["calibration"])
    assert summary["status"] == "WARMUP"
    assert summary["direction_accuracy"] == 1.0
    assert summary["current_official_static_suspect_ratio"] == 0.5
    assert summary["trajectory_fallback_operational"] is True


def test_patch_persists_bounded_events_and_latest_health(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "_config", _cfg)
    now = datetime.now(timezone.utc)
    previous = {
        "players": {
            "1": {
                "now_cost": 55,
                "prediction": {
                    "risk_direction": "RISE",
                    "predicted_change_deadline": (now - timedelta(hours=1)).isoformat(),
                    "prediction_source": "TRAJECTORY_RATE",
                    "official_projection_health": "SUSPECT_STATIC_OFFSET0",
                },
            }
        },
        "calibration": {
            "events": [
                {"realized_direction": "RISE", "direction_correct": True},
                {"realized_direction": "FALL", "direction_correct": False},
                {"event": "PREDICTED_WINDOW_MISSED"},
            ]
        },
    }
    (tmp_path / "price_trajectory.json").write_text(json.dumps({"players": {"1": {"now_cost": 56}}}))
    (tmp_path / "prices.json").write_text(json.dumps({
        "players": [{
            "element": 1,
            "now_cost": 56,
            "risk_direction": "RISE",
            "predicted_change_deadline": (now + timedelta(hours=2)).isoformat(),
            "prediction_source": "TRAJECTORY_RATE",
            "official_projection_health": "SUSPECT_STATIC_OFFSET0",
            "official_projections": [{}],
            "urgency": "HIGH",
            "official_progress_pct": 80,
        }]
    }))
    (tmp_path / "latest.json").write_text(json.dumps({}))

    summary = pc.patch_files(tmp_path, previous)
    state = json.loads((tmp_path / "price_trajectory.json").read_text())
    latest = json.loads((tmp_path / "latest.json").read_text())

    assert len(state["calibration"]["events"]) == 3
    assert state["players"]["1"]["prediction"]["prediction_source"] == "TRAJECTORY_RATE"
    assert latest["price_model_health"] == summary
    assert summary["realized_change_samples"] >= 1
