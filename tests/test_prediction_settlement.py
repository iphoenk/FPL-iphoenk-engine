from __future__ import annotations

from datetime import datetime, timezone

from src.engines.prediction_evaluation import (
    _decision_validation,
    _metrics,
    _position_drift,
    _promote_overdue_predeadline_forecasts,
)


def test_overdue_record_promotes_last_predeadline_snapshot() -> None:
    now = datetime(2026, 8, 29, 7, 0, tzinfo=timezone.utc)
    candidate = {
        "generated_at": "2026-08-28T16:40:29+00:00",
        "players": [{"element": 1, "xpts": 4.2}],
    }
    records = {
        "2": {
            "gw": 2,
            "status": "COLLECTING",
            "deadline_time": "2026-08-28T17:30:00Z",
            "latest_pre_deadline_forecast": candidate,
        }
    }

    result = _promote_overdue_predeadline_forecasts(records, now)

    assert result == {"promoted": 1, "missed": 0}
    record = records["2"]
    assert record["status"] == "FROZEN_AWAITING_SETTLEMENT"
    assert record["frozen_forecast"] is candidate
    assert record["frozen_at"] == now.isoformat()
    assert record["freeze_transition"] == "PROMOTED_LAST_PREDEADLINE_SNAPSHOT"


def test_postdeadline_candidate_is_never_frozen() -> None:
    now = datetime(2026, 8, 29, 7, 0, tzinfo=timezone.utc)
    records = {
        "2": {
            "gw": 2,
            "status": "COLLECTING",
            "deadline_time": "2026-08-28T17:30:00Z",
            "latest_pre_deadline_forecast": {
                "generated_at": "2026-08-28T17:31:00+00:00",
                "players": [{"element": 1}],
            },
        }
    }

    result = _promote_overdue_predeadline_forecasts(records, now)

    assert result == {"promoted": 0, "missed": 1}
    assert records["2"]["status"] == "MISSED_PRE_DEADLINE_FREEZE"
    assert "frozen_forecast" not in records["2"]


def test_future_deadline_stays_collecting() -> None:
    now = datetime(2026, 8, 29, 7, 0, tzinfo=timezone.utc)
    records = {
        "3": {
            "gw": 3,
            "status": "COLLECTING",
            "deadline_time": "2026-09-04T17:30:00Z",
            "latest_pre_deadline_forecast": {
                "generated_at": "2026-08-29T06:39:00+00:00",
                "players": [{"element": 411}],
            },
        }
    }

    result = _promote_overdue_predeadline_forecasts(records, now)

    assert result == {"promoted": 0, "missed": 0}
    assert records["3"]["status"] == "COLLECTING"
    assert "frozen_forecast" not in records["3"]


def test_dnp_probability_is_scored_only_from_frozen_forecast() -> None:
    pairs = [
        {
            "forecast": {
                "position": "MID",
                "xpts": 4.0,
                "xmins": 60.0,
                "start_probability": 0.8,
                "dnp_probability": 0.2,
                "clean_sheet_probability": 0.1,
            },
            "actual": {"points": 0.0, "minutes": 0.0, "started": 0, "dnp": 1, "clean_sheet": 0},
        },
        {
            "forecast": {
                "position": "FWD",
                "xpts": 5.0,
                "xmins": 80.0,
                "start_probability": 0.9,
                "dnp_probability": 0.1,
                "clean_sheet_probability": 0.0,
            },
            "actual": {"points": 6.0, "minutes": 90.0, "started": 1, "dnp": 0, "clean_sheet": 0},
        },
    ]

    result = _metrics(pairs)

    assert result["dnp_sample_size"] == 2
    assert result["dnp_brier"] == 0.025
    assert result["status"] == "SETTLED"


def test_future_snapshot_can_settle_vice_and_first_bench_regret() -> None:
    snapshot = {
        "lineup": {
            "captain": 1,
            "vice_captain": 2,
            "captain_candidates": [1, 2, 3],
            "starting_xi": [],
            "owned_squad": [],
            "bench_order": [4, 5, 6],
        },
        "comparator": {"comparisons": []},
    }
    actual = [
        {"element": 1, "points": 8.0},
        {"element": 2, "points": 3.0},
        {"element": 3, "points": 7.0},
        {"element": 4, "points": 2.0},
        {"element": 5, "points": 6.0},
        {"element": 6, "points": 1.0},
    ]

    result = _decision_validation(snapshot, actual)

    assert result["vice_regret"]["status"] == "SETTLED"
    assert result["vice_regret"]["value"] == 4.0
    assert result["bench_first_regret"]["status"] == "SETTLED"
    assert result["bench_first_regret"]["value"] == 4.0


def test_legacy_snapshot_does_not_fabricate_vice_or_bench_outcomes() -> None:
    snapshot = {
        "lineup": {
            "captain": 1,
            "captain_candidates": [1, 2],
            "starting_xi": [],
            "owned_squad": [],
        },
        "comparator": {"comparisons": []},
    }
    actual = [{"element": 1, "points": 5.0}, {"element": 2, "points": 7.0}]

    result = _decision_validation(snapshot, actual)

    assert result["vice_regret"]["status"] == "NO_GENUINE_PREDEADLINE_SAMPLE"
    assert result["bench_first_regret"]["status"] == "NO_GENUINE_PREDEADLINE_SAMPLE"


def test_position_drift_alert_requires_minimum_sample_and_material_excess() -> None:
    by_position = {
        "DEF": {"sample_size": 10, "points_mae": 2.0},
        "MID": {"sample_size": 10, "points_mae": 0.9},
        "FWD": {"sample_size": 3, "points_mae": 3.0},
    }
    overall = {"sample_size": 23, "points_mae": 1.0}
    cfg = {"position_drift_alert": {"minimum_samples_per_position": 8, "mae_excess_threshold": 0.75}}

    result = _position_drift(by_position, overall, cfg)

    assert result["status"] == "ALERT"
    assert [row["position"] for row in result["alerts"]] == ["DEF"]
