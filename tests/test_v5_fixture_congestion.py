from src.v5.intelligence.fixture_congestion import fixture_rest_context, resolve_fixture_congestion


def _official():
    return [
        {"event": 1, "team_h": 10, "team_a": 20, "kickoff_time": "2026-09-05T18:00:00Z"},
        {"event": 2, "team_h": 30, "team_a": 10, "kickoff_time": "2026-09-10T18:00:00Z"},
        {"event": 3, "team_h": 10, "team_a": 40, "kickoff_time": "2026-09-17T18:00:00Z"},
    ]


def _schedule():
    return {
        "cross_competition_fixtures": [
            {
                "fpl_team_id": 10,
                "kickoff_time": "2026-09-12T18:00:00Z",
                "competition_class": "EUROPE",
                "source": "api_football",
                "fixture_id": 999,
            },
            {
                "fpl_team_id": 10,
                "kickoff_time": "2026-12-01T18:00:00Z",
                "competition_class": "DOMESTIC_CUP",
                "source": "api_football",
                "fixture_id": 1000,
            },
        ],
        "cross_competition_rest_days": {
            "10": {"minimum_cross_competition_rest_days": 1.0}
        },
    }


def test_fixture_rest_context_is_relative_to_target_not_global_calendar_minimum():
    context = fixture_rest_context(
        _official(),
        _schedule(),
        10,
        "2026-09-10T18:00:00Z",
    )
    assert context["status"] == "ACTIVE"
    assert context["rest_days_before"] == 5.0
    assert context["rest_days_after"] == 2.0
    assert context["minimum_adjacent_rest_days"] == 2.0
    assert context["next_event_class"] == "EUROPE"
    assert context["global_calendar_minimum_used"] is False


def test_congestion_factor_is_conservative_role_weighted_and_registry_owned():
    resolved = resolve_fixture_congestion(
        _official(),
        _schedule(),
        10,
        "2026-09-10T18:00:00Z",
        rotation_risk=0.5,
    )
    assert resolved["enabled"] is True
    assert resolved["applied"] is True
    assert resolved["severity"] == "SEVERE"
    assert resolved["factor"] == 0.96
    assert resolved["calibration_status"] == "PROVISIONAL_STRUCTURAL_PRIOR"
    assert resolved["promotion_requires_settled_backtest"] is True


def test_missing_adjacent_fixture_evidence_is_neutral_not_fabricated():
    resolved = resolve_fixture_congestion([], {}, 10, "2026-09-10T18:00:00Z", rotation_risk=0.8)
    assert resolved["factor"] == 1.0
    assert resolved["applied"] is False
    assert resolved["rest_context"]["status"] == "UNAVAILABLE"
