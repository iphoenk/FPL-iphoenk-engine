from tools.gw10_owner_export import aggregate, aware


def test_actual_metric_aggregation_preserves_missing_instead_of_zero_or_partial_sum():
    rows = [
        {"minutes": 90, "total_points": 6, "goals_prevented": None},
        {"minutes": 90, "total_points": 2},
    ]
    out = aggregate(rows)
    assert out["minutes"] == 180
    assert out["total_points"] == 8
    assert out["goals_prevented"] is None


def test_occurrence_timestamps_must_be_timezone_aware():
    assert aware("2026-11-06T23:17:00+07:00") is not None
    assert aware("2026-11-06T23:17:00") is None
    assert aware(None) is None
