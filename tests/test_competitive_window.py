from src.engines.v12_competitive_window import resolve_competitive_window


def test_rank_1_of_58_top10_window():
    got = resolve_competitive_window(1, 58)
    assert got["window_mode"] == "TOP10"
    assert got["above_count"] == 0
    assert got["below_count"] == 9
    assert got["rival_count"] == 9
    assert got["ranks"] == list(range(2, 11))


def test_rank_7_of_58_top10_window():
    got = resolve_competitive_window(7, 58)
    assert got["above_count"] == 6
    assert got["below_count"] == 3
    assert got["rival_count"] == 9
    assert got["ranks"] == [1, 2, 3, 4, 5, 6, 8, 9, 10]


def test_rank_9_of_58_top10_window():
    got = resolve_competitive_window(9, 58)
    assert got["above_count"] == 8
    assert got["below_count"] == 1
    assert got["rival_count"] == 9


def test_rank_10_uses_transition_window():
    got = resolve_competitive_window(10, 58)
    assert got["window_mode"] == "NINE_ABOVE_FIVE_BELOW"
    assert got["above_count"] == 9
    assert got["below_count"] == 5
    assert got["rival_count"] == 14
    assert got["ranks"] == [1,2,3,4,5,6,7,8,9,11,12,13,14,15]


def test_rank_18_of_58():
    got = resolve_competitive_window(18, 58)
    assert got["above_count"] == 9
    assert got["below_count"] == 5
    assert got["rival_count"] == 14
    assert got["ranks"] == [9,10,11,12,13,14,15,16,17,19,20,21,22,23]


def test_rank_55_boundary():
    got = resolve_competitive_window(55, 58)
    assert got["above_count"] == 9
    assert got["below_count"] == 3
    assert got["rival_count"] == 12


def test_rank_58_boundary():
    got = resolve_competitive_window(58, 58)
    assert got["above_count"] == 9
    assert got["below_count"] == 0
    assert got["rival_count"] == 9
    assert got["ranks"] == list(range(49, 58))
