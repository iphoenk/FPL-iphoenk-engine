from src.engines.v12_rotation_risk import (
    build_competitive_window,
    canonical_conditional_minutes_support,
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



def test_canonical_xmins_state_support_is_conditional_and_source_bound():
    names = ("START_FULL", "START_SUBBED", "EARLY_SUB", "CAMEO", "LATE_CAMEO", "DNP")
    values = (85, 68, 42, 19, 7, 0)
    probabilities = (0.35, 0.25, 0.15, 0.12, 0.05, 0.08)
    rows = [
        {"state": name, "probability": probability, "minutes_mean": mean,
         "minutes_std": 0 if name == "DNP" else 5,
         "timing_evidence": "MATCH_MINUTES_DERIVED"}
        for name, probability, mean in zip(names, probabilities, values)
    ]
    projections = {"players": [
        {"element": 411, "xmins": {"xmins_distribution": {"states": rows}}},
        {"element": 42, "xmins": {"xmins_distribution": {"states": rows}}},
    ]}
    support = canonical_conditional_minutes_support(projections, player_id=411)
    assert [row["state"] for row in support] == ["STARTER", "CAMEO", "DNP"]
    assert [len(row["components"]) for row in support] == [3, 2, 1]
    assert support[0]["components"][0]["minutes_mean"] == 85
    assert support[1]["components"][1]["minutes_mean"] == 7
    assert support[2]["components"][0]["minutes_mean"] == 0
    assert all(row["post_news_probability_calibrated"] is False for row in support)
    model = build_minutes_scenarios(
        player_id=411, existing_state_support=support, calibration_status="NOT_VERIFIED"
    )
    assert model["publication_mode"] == "CONDITIONAL_ONLY"
    assert model["weights"] is None


def test_canonical_minutes_support_rejects_missing_or_wrong_identity():
    assert canonical_conditional_minutes_support({"players": []}, player_id=411) == []
    assert canonical_conditional_minutes_support(
        {"players": [{"element": 42, "xmins": {}}]}, player_id=411
    ) == []
    assert canonical_conditional_minutes_support(
        {"players": [{"element": 411, "xmins": {"xmins_distribution": {
            "states": [{"state": "START_FULL", "minutes_mean": 90,
                        "minutes_std": 8, "probability": 1.0}]
        }}}]}, player_id=411
    ) == []
