from src.rules import (
    GOAL_POINTS, CLEAN_SHEET_POINTS, defensive_contribution_points,
    score_from_official_stats, build_chip_ledger, CHIP_RULES, BPS_2026_27,
)


def test_basic_scoring_constants():
    assert GOAL_POINTS == {1: 10, 2: 6, 3: 5, 4: 4}
    assert CLEAN_SHEET_POINTS == {1: 4, 2: 4, 3: 1, 4: 0}


def test_dc_thresholds_and_cap():
    assert defensive_contribution_points(2, 9) == 0
    assert defensive_contribution_points(2, 10) == 2
    assert defensive_contribution_points(2, 20) == 2
    assert defensive_contribution_points(3, 11) == 0
    assert defensive_contribution_points(3, 12) == 2
    assert defensive_contribution_points(4, 12) == 2
    assert defensive_contribution_points(1, 99) == 0


def test_match_scoring_reconstruction_goalkeeper():
    stats = {
        "minutes": 90, "goals_scored": 1, "assists": 0, "clean_sheets": 1,
        "goals_conceded": 0, "saves": 6, "penalties_saved": 1,
        "penalties_missed": 0, "yellow_cards": 0, "red_cards": 0,
        "own_goals": 0, "bonus": 3,
    }
    result = score_from_official_stats(stats, 1)
    assert result["complete"] is True
    assert result["points"] == 24  # 2 appearance +10 goal +4 CS +2 saves +5 pen save +3 bonus


def test_match_scoring_reconstruction_defender_dc():
    stats = {
        "minutes": 90, "goals_scored": 0, "assists": 1, "clean_sheets": 1,
        "goals_conceded": 0, "penalties_saved": 0, "penalties_missed": 0,
        "yellow_cards": 0, "red_cards": 0, "own_goals": 0, "bonus": 2,
        "defensive_contribution": 10,
    }
    result = score_from_official_stats(stats, 2)
    assert result["complete"] is True
    assert result["points"] == 13  # 2 +3 +4 +2 bonus +2 DC


def test_chip_ledger_two_halves_and_used_chip():
    ledger = build_chip_ledger([{"name": "bboost", "event": 1, "time": "x"}], 2)
    assert ledger["current_half"] == 1
    assert "bench_boost" in ledger["halves"]["1"]["used"]
    assert "bench_boost" not in ledger["halves"]["1"]["available"]
    assert "bench_boost" in ledger["halves"]["2"]["available"]
    assert CHIP_RULES["one_chip_per_gameweek"] is True
    assert CHIP_RULES["free_hit_gw1_allowed"] is False
    assert CHIP_RULES["free_hit_gw19_to_gw20_consecutive_allowed"] is False


def test_bps_2026_27_deltas_recorded():
    assert BPS_2026_27["tackled_penalty_removed"] is True
    assert BPS_2026_27["penalty_save_bps"] == 7
    assert "3 CBI" in BPS_2026_27["cbi_bps"]
