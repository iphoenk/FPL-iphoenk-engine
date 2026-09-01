from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.match_mode_live_score import build_match_mode_scorecard


def _bootstrap() -> dict:
    return {
        "teams": [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}],
        "elements": [
            {
                "id": eid,
                "web_name": f"P{eid}",
                "team": 1 if eid <= 8 else 2,
                "element_type": 1 if eid in {1, 15} else (2 if eid <= 6 else (3 if eid <= 11 else 4)),
            }
            for eid in range(1, 16)
        ],
    }


def _raw(*, pick_count: int = 15, active: bool = True, include_event_live: bool = True) -> dict:
    picks = []
    for eid in range(1, pick_count + 1):
        multiplier = 1 if eid <= 11 else 0
        if eid == 7:
            multiplier = 2
        picks.append({
            "element": eid,
            "position": eid,
            "multiplier": multiplier,
            "is_captain": eid == 7,
            "is_vice_captain": eid == 8,
        })
    event_live = {
        "elements": [
            {
                "id": eid,
                "stats": {
                    "minutes": 60,
                    "total_points": eid,
                    "goals_scored": 1 if eid == 7 else 0,
                    "assists": 1 if eid == 8 else 0,
                    "clean_sheets": 1 if eid <= 6 else 0,
                    "saves": 2 if eid == 1 else 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "bonus": 3 if eid == 7 else 0,
                    "bps": 40 if eid == 7 else 10,
                },
            }
            for eid in range(1, 16)
        ]
    } if include_event_live else {}
    return {
        "schema": "snapshot.v1",
        "phase": {"scoring_gw": 3, "is_live_match": active},
        "official": {
            "bootstrap": _bootstrap(),
            "fixtures": [{"event": 3, "team_h": 1, "team_a": 2, "started": active, "finished": False}],
            "picks": {"picks": picks, "entry_history": {"event_transfers_cost": 4}},
            "event_live": event_live,
        },
    }


def _deadline(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "gw03.json").write_text(json.dumps({
        "kind": "deadline_prediction_snapshot",
        "gw": 3,
        "immutable": True,
        "prediction_generated_at": "2026-09-04T16:00:00+00:00",
        "players": [
            {
                "element": eid,
                "fixtures": [{
                    "event": 3,
                    "xpts": float(eid) - 0.5,
                    "xmins": {"expected_minutes": 80.0, "start_probability": 0.9},
                }],
            }
            for eid in range(1, 16)
        ],
    }), encoding="utf-8")


def test_v4_match_mode_serves_all15_and_personalized_live_score(tmp_path: Path) -> None:
    deadline = tmp_path / "deadline"
    _deadline(deadline)
    result = build_match_mode_scorecard(_raw(), deadline_root=deadline)
    assert result["contract"] == "MATCH_MODE_LIVE_SCORE_V1"
    assert result["status"] == "PROVISIONAL"
    assert result["coverage"] == {"owned": 15, "expected_owned": 15, "complete": True}
    assert len(result["players"]) == 15
    captain = next(row for row in result["players"] if row["captain"])
    assert captain["raw_points"] == 7
    assert captain["multiplier"] == 2
    assert captain["effective_points"] == 14
    assert captain["pre_match_prediction"]["xpts"] == 6.5
    assert captain["actual_vs_predicted"]["raw_points_minus_xpts"] == 0.5
    score = result["personalized_live_score"]
    assert score["captain_raw_points"] == 7
    assert score["captain_effective_contribution"] == 14
    assert score["players_live"] == 15
    assert score["provisional_bonus_total"] == 3
    assert score["autosub_implications"]["status"] == "PROVISIONAL"
    assert result["guardrails"]["planning_xi_cannot_replace_submitted_picks"] is True


def test_v4_match_mode_keeps_bench_points_separate(tmp_path: Path) -> None:
    deadline = tmp_path / "deadline"
    _deadline(deadline)
    result = build_match_mode_scorecard(_raw(), deadline_root=deadline)
    bench_raw = sum(row["raw_points"] for row in result["players"] if row["multiplier"] == 0)
    assert result["personalized_live_score"]["bench_points"] == bench_raw
    assert result["personalized_live_score"]["current_net_total"] == result["personalized_live_score"]["effective_xi_points"] - 4


def test_v4_match_mode_missing_picks_never_infers_total(tmp_path: Path) -> None:
    result = build_match_mode_scorecard(_raw(pick_count=0), deadline_root=tmp_path)
    assert result["status"] == "PARTIAL"
    assert result["submitted_picks_status"] == "SUBMITTED PICKS UNAVAILABLE"
    assert result["players"] == []
    assert result["personalized_live_score"] is None


def test_v4_match_mode_missing_event_live_never_fabricates(tmp_path: Path) -> None:
    result = build_match_mode_scorecard(_raw(include_event_live=False), deadline_root=tmp_path)
    assert result["status"] == "PARTIAL"
    assert result["event_live_status"] == "UNAVAILABLE"
    assert result["players"] == []


def test_v4_match_mode_incomplete_available_picks_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="ALL15 submitted-pick coverage required"):
        build_match_mode_scorecard(_raw(pick_count=14), deadline_root=tmp_path)


def test_v4_non_live_checkpoint_is_idle(tmp_path: Path) -> None:
    result = build_match_mode_scorecard(_raw(active=False), deadline_root=tmp_path)
    assert result["status"] == "IDLE"
    assert result["match_mode_active"] is False


def test_service_registry_preserves_eight_boundaries_and_uses_live_overlays() -> None:
    registry = json.loads(Path("config/service_registry.json").read_text(encoding="utf-8"))
    services = registry["services"]
    assert len(services) == 8
    by_id = {row["id"]: row for row in services}
    assert by_id["personal_gw_scorecard"]["module"] == "src.services.gw_scorecard_live_overlay"
    assert by_id["governance"]["module"] == "src.services.governance_live_overlay"
