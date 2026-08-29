from __future__ import annotations

from datetime import datetime, timezone

from src.engines.prediction_evaluation import _promote_overdue_predeadline_forecasts


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
