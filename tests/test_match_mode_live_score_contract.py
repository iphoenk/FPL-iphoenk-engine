from __future__ import annotations

import json
from pathlib import Path

from src.engines import live_state_service as service


def _bootstrap() -> dict:
    return {
        "teams": [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "elements": [
            {"id": eid, "web_name": f"P{eid}", "team": 1 if eid <= 8 else 2, "element_type": 1 if eid in {1, 15} else (2 if eid <= 6 else (3 if eid <= 11 else 4))}
            for eid in range(1, 16)
        ],
    }


def _snapshot(*, picks_count: int = 15, live: bool = True) -> dict:
    picks = []
    for eid in range(1, picks_count + 1):
        position = eid
        multiplier = 1 if position <= 11 else 0
        if eid == 7:
            multiplier = 2
        picks.append({
            "element": eid,
            "position": position,
            "multiplier": multiplier,
            "is_captain": eid == 7,
            "is_vice_captain": eid == 8,
        })
    return {
        "bootstrap": _bootstrap(),
        "phase": {"scoring_gw": 3, "is_live_event": live},
        "fixtures": [
            {"event": 3, "team_h": 1, "team_a": 2, "started": live, "finished": False if live else True},
        ],
        "picks": {"picks": picks, "entry_history": {"event_transfers_cost": 4}},
        "event_live": {
            "elements": [
                {
                    "id": eid,
                    "stats": {
                        "minutes": 60 if live else 90,
                        "goals_scored": 1 if eid == 7 else 0,
                        "assists": 1 if eid == 8 else 0,
                        "clean_sheets": 1 if eid <= 6 else 0,
                        "goals_conceded": 0,
                        "own_goals": 0,
                        "penalties_saved": 0,
                        "penalties_missed": 0,
                        "yellow_cards": 0,
                        "red_cards": 0,
                        "saves": 2 if eid == 1 else 0,
                        "bonus": 3 if eid == 7 else 0,
                        "bps": 40 if eid == 7 else 10,
                        "total_points": eid,
                    },
                    "explain": [],
                }
                for eid in range(1, 16)
            ]
        },
    }


def _ledger() -> dict:
    return {
        "records": {
            "3": {
                "latest_pre_deadline_forecast": {
                    "generated_at": "2026-09-04T16:00:00+00:00",
                    "players": [
                        {"element": eid, "xpts": float(eid) - 0.5, "xmins": 80.0, "start_probability": 0.9, "projection_confidence": "MEDIUM"}
                        for eid in range(1, 16)
                    ],
                }
            }
        }
    }


def _run(tmp_path: Path, monkeypatch, snapshot: dict) -> dict:
    official = tmp_path / "official_snapshot.json"
    ledger = tmp_path / "prediction_ledger.json"
    out = tmp_path / "live.json"
    official.write_text(json.dumps(snapshot), encoding="utf-8")
    ledger.write_text(json.dumps(_ledger()), encoding="utf-8")
    monkeypatch.setattr(service, "OFFICIAL", official)
    monkeypatch.setattr(service, "PREDICTION_LEDGER", ledger)
    monkeypatch.setattr(service, "OUT", out)
    return service.run()


def test_match_mode_serves_all15_and_personalized_score(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, _snapshot())
    assert result["contract"] == "MATCH_MODE_LIVE_SCORE_V1"
    assert result["match_mode_active"] is True
    assert result["coverage"] == {"owned": 15, "expected_owned": 15, "complete": True}
    assert len(result["players"]) == 15
    assert {row["fixture_status"] for row in result["players"]} == {"LIVE"}
    captain = next(row for row in result["players"] if row["captain"])
    assert captain["multiplier"] == 2
    assert captain["effective_points"] == captain["total_points"] * 2
    assert captain["pre_match_prediction"]["xpts"] == 6.5
    assert captain["actual_vs_predicted"]["raw_points_minus_xpts"] == 0.5
    score = result["personalized_live_score"]
    assert score["captain_raw_points"] == 7
    assert score["captain_effective_contribution"] == 14
    assert score["players_live"] == 15
    assert score["players_ft"] == 0
    assert score["players_not_started"] == 0
    assert score["provisional_bonus_total"] == 3
    assert score["autosub_implications"]["status"] == "PROVISIONAL"
    assert result["governance"]["planning_xi_cannot_replace_submitted_picks"] is True
    assert result["governance"]["single_match_performance_cannot_authorize_transfer"] is True


def test_match_mode_keeps_bench_points_separate_and_does_not_apply_autosub(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, _snapshot())
    bench_raw = sum(row["total_points"] for row in result["players"] if row["multiplier"] == 0)
    assert result["personalized_live_score"]["bench_points"] == bench_raw
    assert result["personalized_live_score"]["current_effective_total"] == result["gross_points"]
    assert result["personalized_live_score"]["current_net_total"] == result["gross_points"] - 4


def test_missing_submitted_picks_never_infers_personalized_total(tmp_path, monkeypatch):
    snapshot = _snapshot(picks_count=0)
    result = _run(tmp_path, monkeypatch, snapshot)
    assert result["submitted_picks_status"] == "SUBMITTED PICKS UNAVAILABLE"
    assert result["personalized_live_score"] is None
    assert result["players"] == []


def test_match_mode_uses_fixture_state_not_phase_flag_for_activation(tmp_path, monkeypatch):
    snapshot = _snapshot(live=False)
    result = _run(tmp_path, monkeypatch, snapshot)
    assert result["match_mode_active"] is False
    assert {row["fixture_status"] for row in result["players"]} == {"FT"}
    assert result["status"] == "RECONCILED_OR_IDLE"
