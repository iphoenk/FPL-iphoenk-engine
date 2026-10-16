from src.engines.v12_rotation_risk import (
    build_competitive_window,
    build_minutes_scenarios,
    build_verified_rotation_event,
    resolve_captain_vice,
    validate_rotation_events,
)


def _event():
    return build_verified_rotation_event(
        source_url="https://example.test/club/news",
        published_at="2026-10-16T08:00:00+00:00",
        observed_at="2026-10-16T09:00:00+00:00",
        player_id=411,
        quote="Player is in the squad; no starter confirmation.",
        evidence_strength="HIGH",
        as_of_cutoff="2026-10-16T12:00:00+00:00",
    )


def test_rotation_event_is_source_verified_and_as_of_valid():
    result = validate_rotation_events(
        [_event()], as_of_cutoff="2026-10-16T12:00:00+00:00", player_id=411
    )
    assert result["status"] == "SOURCE_VERIFIED"
    assert result["no_duplicates"] is True
    assert result["as_of_valid"] is True
    assert result["events"][0]["is_injury_flag"] is False


def test_duplicate_rotation_event_is_not_admitted():
    event = _event()
    result = validate_rotation_events(
        [event, event], as_of_cutoff="2026-10-16T12:00:00+00:00", player_id=411
    )
    assert result["no_duplicates"] is False


def test_uncalibrated_news_remains_conditional_and_does_not_change_start_probability():
    result = build_minutes_scenarios(
        player_id=411,
        existing_state_support=[{"state": "START", "probability": 0.8}],
        calibration_status="NOT_VERIFIED",
    )
    assert result["states"] == ["STARTER", "CAMEO", "DNP"]
    assert result["publication_mode"] == "CONDITIONAL_ONLY"
    assert result["weights"] is None
    assert result["p_start_is_not_arbitrarily_reduced"] is True


def test_cameo_keeps_captain_but_dnp_activates_vice():
    assert resolve_captain_vice(8, 90) == "CAPTAIN"
    assert resolve_captain_vice(0, 90) == "VICE"
    assert resolve_captain_vice(0, 0) == "NO_ACTIVE_ARMBAND"


def test_competitive_window_fails_closed_without_nine_eo_rows():
    result = build_competitive_window(rivals=[], player_id=411)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["required_rivals"] == 9

