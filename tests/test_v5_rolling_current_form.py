import json

from src.v5.intelligence.rolling_form import build_rolling_form


def _write_artifact(tmp_path, gw, rows):
    path = tmp_path / f"playermatchstats_gw{gw}.json"
    path.write_text(
        json.dumps(
            {
                "source": "FPL-Core-Insights",
                "dataset": "playermatchstats",
                "gw": gw,
                "fetched_at": f"2026-08-{20 + gw:02d}T00:00:00+00:00",
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    return path


def _row(player_id, minutes, xg, xa, shots=1, box=2, chances=1):
    return {
        "player_id": str(player_id),
        "minutes_played": str(minutes),
        "xg": str(xg),
        "xa": str(xa),
        "total_shots": str(shots),
        "shots_on_target": "1",
        "touches_opposition_box": str(box),
        "chances_created": str(chances),
    }


def _cfg(tmp_path):
    return {
        "model": "recency_weighted_playermatchstats_v1",
        "artifact_path_template": str(tmp_path / "playermatchstats_gw{gw}.json"),
        "expected_completed_gw_offset_from_planning_gw": -1,
        "window_gameweeks": 4,
        "minimum_completed_gameweeks": 2,
        "minimum_player_gameweeks_with_minutes": 2,
        "minimum_evidence_minutes": 90.0,
        "decay_per_gw": 0.5,
    }


def test_single_completed_gw_is_developing_and_non_authoritative(tmp_path):
    _write_artifact(tmp_path, 1, [_row(10, 90, 0.4, 0.2)])
    result = build_rolling_form(planning_gw=2, config=_cfg(tmp_path))
    assert result["status"] == "DEVELOPING_WINDOW"
    assert result["valid_gws"] == [1]
    assert result["latest_completed_gw_available"] is True
    assert result["authoritative_eligible"] is False
    assert result["players"]["10"]["authoritative_eligible"] is False


def test_two_gw_window_becomes_authoritative_and_recency_weighted(tmp_path):
    _write_artifact(tmp_path, 1, [_row(10, 90, 0.9, 0.0)])
    _write_artifact(tmp_path, 2, [_row(10, 90, 0.0, 0.6)])
    result = build_rolling_form(planning_gw=3, config=_cfg(tmp_path))
    player = result["players"]["10"]
    assert result["status"] == "ACTIVE"
    assert result["valid_gws"] == [1, 2]
    assert result["authoritative_eligible"] is True
    assert player["authoritative_eligible"] is True
    assert player["gameweeks_with_minutes"] == [1, 2]
    # GW1 gets 0.5 weight, GW2 gets 1.0. Weighted minutes = 135.
    assert player["weighted_minutes"] == 135.0
    assert player["weighted_xg"] == 0.45
    assert player["weighted_xa"] == 0.6
    assert player["xg90"] == 0.3
    assert player["xa90"] == 0.4


def test_latest_completed_gw_missing_blocks_authoritative_use(tmp_path):
    _write_artifact(tmp_path, 1, [_row(10, 90, 0.4, 0.2)])
    _write_artifact(tmp_path, 2, [_row(10, 90, 0.3, 0.2)])
    result = build_rolling_form(planning_gw=4, config=_cfg(tmp_path))
    assert result["expected_completed_gw"] == 3
    assert result["valid_gws"] == [1, 2]
    assert result["latest_completed_gw_available"] is False
    assert result["status"] == "DEGRADED_LATEST_GW_MISSING"
    assert result["authoritative_eligible"] is False
    assert result["players"]["10"]["authoritative_eligible"] is False


def test_future_artifact_is_never_requested_or_loaded(tmp_path):
    _write_artifact(tmp_path, 1, [_row(10, 90, 0.2, 0.1)])
    _write_artifact(tmp_path, 2, [_row(10, 90, 0.2, 0.1)])
    _write_artifact(tmp_path, 3, [_row(10, 90, 9.0, 9.0)])
    result = build_rolling_form(planning_gw=3, config=_cfg(tmp_path))
    assert result["expected_completed_gw"] == 2
    assert result["requested_gws"] == [1, 2]
    assert result["valid_gws"] == [1, 2]
    assert all(row["gw"] <= 2 for row in result["artifact_status"])
    assert result["players"]["10"]["xg90"] < 1.0
