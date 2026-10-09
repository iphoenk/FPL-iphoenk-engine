from src.engines.v12_captain_shared_world import (
    MC_PATHS,
    simulate_shared_world_cvc,
    validate_goalkeeper_event_calibration,
)


def calibration():
    return {
        "clean_sheet_probability": 0.55,
        "conceded_goals": {"0": 0.55, "1": 0.25, "2": 0.15, "3_plus": 0.05},
        "saves": {"0": 0.2, "1": 0.4, "2": 0.3, "3_plus": 0.1},
        "bonus_probability": 0.35,
        "penalty_save_probability": 0.04,
        "appearance_probability": 0.96,
        "provenance": {
            "source_id": "official-match-events",
            "dataset_id": "gk-calibration-2026-27-gw6",
            "calibration_version": "gk-events-v1",
            "evidence_cutoff_at": "2026-10-09T02:00:00Z",
        },
    }


def candidate(element_id, position, pmf, *, p_dnp=0.05):
    return {
        "element_id": element_id,
        "position": position,
        "p_dnp": p_dnp,
        "point_distribution": {
            "probabilities": {str(points): probability for points, probability in pmf.items()}
        },
        **({"goalkeeper_event_calibration": calibration()} if position == "GK" else {}),
    }


def test_goalkeeper_calibration_requires_provenance_and_normalized_events():
    result = validate_goalkeeper_event_calibration(calibration())
    assert result["available"] is True

    invalid = calibration()
    invalid["conceded_goals"]["0"] = 0.54
    result = validate_goalkeeper_event_calibration(invalid)
    assert result["available"] is False
    assert "CLEAN_SHEET_MUST_MATCH_CONCEDED_ZERO" in result["errors"]


def test_shared_world_uses_exact_mc500k_and_is_deterministic():
    rows = [
        candidate(1, "GK", {2: 0.25, 6: 0.55, 10: 0.20}),
        candidate(2, "MID", {2: 0.30, 6: 0.40, 12: 0.30}),
        candidate(3, "FWD", {2: 0.35, 8: 0.35, 15: 0.30}),
    ]
    first = simulate_shared_world_cvc(rows, captain_id=1, vice_captain_id=2)
    second = simulate_shared_world_cvc(rows, captain_id=1, vice_captain_id=2)
    assert first["status"] == "AVAILABLE"
    assert first["paths"] == MC_PATHS == 500_000
    assert first["shared_world"] is True
    assert first["winner_probability"] == second["winner_probability"]
    assert first["cvc_distribution"] == second["cvc_distribution"]
    assert first["convergence"]["status"] == "AVAILABLE_FOR_EXISTING_GATE"


def test_missing_gk_calibration_is_unavailable_not_defaulted():
    rows = [candidate(1, "GK", {2: 0.5, 6: 0.5}), candidate(2, "FWD", {2: 0.5, 10: 0.5})]
    rows[0].pop("goalkeeper_event_calibration")
    result = simulate_shared_world_cvc(rows, captain_id=1, vice_captain_id=2)
    assert result["status"] == "UNAVAILABLE"
    assert "GK_MISSING_CLEAN_SHEET_PROBABILITY_1" in result["errors"]


def test_shared_world_mini_league_rank_simulation_uses_same_world():
    rows = [
        candidate(1, "GK", {2: 0.5, 8: 0.5}),
        candidate(2, "MID", {2: 0.5, 12: 0.5}),
    ]
    entries = [
        {"team_id": "focal", "base_points": 100, "captain_id": 1, "vice_captain_id": 2},
        {"team_id": "rival", "base_points": 100, "captain_id": 2, "vice_captain_id": 1},
    ]
    result = simulate_shared_world_cvc(
        rows, captain_id=1, vice_captain_id=2, mini_league_entries=entries
    )
    assert result["mini_league"]["status"] == "AVAILABLE"
    assert result["mini_league"]["shared_world"] is True
    assert result["mini_league"]["teams"] == 2
