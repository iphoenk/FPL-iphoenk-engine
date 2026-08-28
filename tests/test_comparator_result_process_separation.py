from __future__ import annotations

from src.engines import owned_challenger_comparator as comparator


def test_performance_signal_separates_result_from_process():
    proj = {
        "position": "MID", "status": "a", "now_cost": 60,
        "xmins": {"expected_minutes": 75, "start_probability": 0.8, "dnp_probability": 0.05},
        "rates": {"xg90": 0.1, "xa90": 0.1},
        "xpts_by_gw": [{"gw": 2+i, "mean": 3.0, "std": 1.0, "fixtures": []} for i in range(5)],
    }
    result_only = comparator._emerging_signal(proj, {"goals": 2, "assists": 0, "xg": 0.05, "xa": 0, "shots": 1, "box_touches": 1, "chances_created": 0})
    process = comparator._emerging_signal(proj, {"goals": 0, "assists": 0, "xg": 0.9, "xa": 0.2, "shots": 5, "box_touches": 10, "chances_created": 5})
    assert result_only[0] == "INTERESTING"
    assert process[0] == "SUSTAINABLE_CANDIDATE"
