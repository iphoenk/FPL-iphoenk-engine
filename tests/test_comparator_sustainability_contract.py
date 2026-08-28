from __future__ import annotations

from src.engines import owned_challenger_comparator as comparator


def _proj():
    return {
        "element": 1,
        "position": "MID",
        "status": "a",
        "now_cost": 60,
        "xmins": {"expected_minutes": 75, "start_probability": 0.8, "dnp_probability": 0.05},
        "rates": {"xg90": 0.1, "xa90": 0.1},
        "xpts_by_gw": [{"gw": 2+i, "mean": 3.0, "std": 1.0, "fixtures": []} for i in range(5)],
    }


def test_result_without_process_stays_below_sustainable_candidate():
    signal, triggers, screening = comparator._emerging_signal(_proj(), {"goals": 2, "assists": 0, "xg": 0.05, "xa": 0.0, "shots": 1, "box_touches": 1, "chances_created": 0})
    assert screening["passed"] is True
    assert triggers == ["MULTIPLE_MATCH_RETURNS"]
    assert signal == "INTERESTING"
