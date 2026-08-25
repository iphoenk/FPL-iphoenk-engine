from src.engines.official_expansion import _compact_element_summary, _fixture_stats, _live_rich


def test_compact_element_summary_preserves_official_sections():
    p={"fixtures":[{"id":1}],"history":[{"round":1}],"history_past":[{"season_name":"2025/26"}],"ignored":1}
    out=_compact_element_summary(p)
    assert set(out)=={"fixtures","history","history_past"}
    assert out["history"][0]["round"]==1


def test_fixture_stats_keeps_current_and_previous_window():
    rows=[{"id":1,"event":1,"stats":[{"identifier":"goals_scored"}]},{"id":2,"event":2,"stats":[]},{"id":3,"event":3,"stats":[]}]
    out=_fixture_stats(rows,2)
    assert [x["id"] for x in out]==[1,2]
    assert out[0]["stats"][0]["identifier"]=="goals_scored"


def test_live_rich_keeps_dc_bps_and_official_points():
    live={"elements":[{"id":9,"stats":{"minutes":90,"bps":25,"bonus":2,"total_points":8,"defensive_contribution":12,"foo":99},"explain":[]} ]}
    out=_live_rich(live)["elements"][0]
    assert out["id"]==9
    assert out["bps"]==25
    assert out["bonus"]==2
    assert out["total_points"]==8
    assert out["defensive_contribution"]==12
    assert "foo" not in out
