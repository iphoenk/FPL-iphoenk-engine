from datetime import datetime, timezone

from src.v5.evaluation.prediction_settlement import recover_overdue_predeadline_freezes
from src.v5.evaluation.temporal_backtest import validate_frozen_ledger


def test_overdue_freeze_recovers_only_genuine_predeadline_snapshot():
    ledger = {
        "records": {
            "2": {
                "gw": 2,
                "deadline_time": "2026-08-28T17:30:00Z",
                "latest_pre_deadline_forecast": {
                    "generated_at": "2026-08-28T17:00:00Z",
                    "players": [{"element": 1, "xpts": 5.1}],
                },
            }
        }
    }

    result = recover_overdue_predeadline_freezes(
        ledger,
        now=datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc),
    )

    assert result["promoted_gameweeks"] == [2]
    record = ledger["records"]["2"]
    assert record["frozen_forecast"]["generated_at"] == "2026-08-28T17:00:00Z"
    assert record["freeze_recovery"]["retroactive_reconstruction"] is False
    assert validate_frozen_ledger(ledger)["status"] == "PASS"


def test_overdue_freeze_refuses_postdeadline_candidate():
    ledger = {
        "records": {
            "2": {
                "gw": 2,
                "deadline_time": "2026-08-28T17:30:00Z",
                "latest_pre_deadline_forecast": {
                    "generated_at": "2026-08-28T18:00:00Z",
                    "players": [{"element": 1, "xpts": 99.0}],
                },
            }
        }
    }

    result = recover_overdue_predeadline_freezes(
        ledger,
        now=datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc),
    )

    assert result["promoted_count"] == 0
    assert result["missed_gameweeks"] == [2]
    assert "frozen_forecast" not in ledger["records"]["2"]
    assert ledger["records"]["2"]["freeze_recovery"]["state"] == "MISSED_NO_VALID_PREDEADLINE_SNAPSHOT"
