from src.engines.v4_backtest_store import actual_by_element


def test_actual_by_element_maps_live_stats():
    live={'elements':[{'id':9,'stats':{'total_points':7,'minutes':90}},{'id':10,'stats':{'total_points':1,'minutes':20}}]}
    out=actual_by_element(live)
    assert out[9]['total_points']==7
    assert out[9]['minutes']==90
    assert out[9]['started'] is True
    assert out[10]['started'] is False
