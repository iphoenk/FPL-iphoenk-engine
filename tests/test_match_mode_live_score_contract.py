from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines import live_state_service as service
from src.engines.v12_report_orchestration import materialize_match_report, render_match_text
from src.runtime_v6.domains.report_plane.report_qa import (
    _validate_v12_rendered_body,
    validate_v12_visible_content_contract,
)

CANONICAL = Path(__file__).resolve().parents[1] / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"


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


def test_incomplete_available_submitted_picks_fail_closed_during_match_mode(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="ALL15 submitted-pick coverage required"):
        _run(tmp_path, monkeypatch, _snapshot(picks_count=14))


def test_match_mode_uses_fixture_state_not_phase_flag_for_activation(tmp_path, monkeypatch):
    snapshot = _snapshot(live=False)
    result = _run(tmp_path, monkeypatch, snapshot)
    assert result["match_mode_active"] is False
    assert {row["fixture_status"] for row in result["players"]} == {"FT"}
    assert result["status"] == "POST_ALL_MATCH"
    assert result["lifecycle"]["primary_mode"] == "POST_ALL_MATCH"


def test_match_lifecycle_gap_after_completed_fixture_stays_in_match():
    fixtures = [
        {"id": 101, "event": 3, "started": True, "finished": True},
        {"id": 102, "event": 3, "started": False, "finished": False},
    ]
    lifecycle = service.classify_scoring_gw_lifecycle(
        fixtures,
        3,
        previous_completed_fixture_ids=[],
    )
    assert lifecycle["primary_mode"] == "MATCH"
    assert lifecycle["fixtures_live"] == 0
    assert lifecycle["fixtures_ft"] == 1
    assert lifecycle["fixtures_not_started"] == 1
    assert lifecycle["incremental_post_match_due"] is True
    assert lifecycle["transition"] == "POST_MATCH_THEN_MATCH"
    assert lifecycle["post_match_return_mode"] == "MATCH"

    repeated = service.classify_scoring_gw_lifecycle(
        fixtures,
        3,
        previous_completed_fixture_ids=[101],
    )
    assert repeated["primary_mode"] == "MATCH"
    assert repeated["incremental_post_match_due"] is False
    assert repeated["transition"] == "MATCH"


def test_match_lifecycle_last_completion_transitions_to_post_all_match():
    fixtures = [
        {"id": 101, "event": 3, "started": True, "finished": True},
        {"id": 102, "event": 3, "started": True, "finished": True},
    ]
    lifecycle = service.classify_scoring_gw_lifecycle(
        fixtures,
        3,
        previous_completed_fixture_ids=[101],
    )
    assert lifecycle["primary_mode"] == "POST_ALL_MATCH"
    assert lifecycle["completed_since_previous"] == [102]
    assert lifecycle["incremental_post_match_due"] is True
    assert lifecycle["transition"] == "POST_MATCH_THEN_POST_ALL_MATCH"
    assert lifecycle["post_match_return_mode"] == "POST_ALL_MATCH"


def test_match_surface_separates_bench_captain_and_provisional_bonus(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, _snapshot())
    bench = result["bench_presentation"]
    assert bench["bench_gk"]["element"] == 15
    assert [row["element"] for row in bench["outfield_autosub_priority"]] == [12, 13, 14]
    assert bench["autosub_state"] == "PROVISIONAL"

    consequence = result["captain_vice_consequence"]
    assert consequence["captain"]["element"] == 7
    assert consequence["captain"]["appearance_state"] == "APPEARED"
    assert consequence["vice"]["element"] == 8
    assert consequence["vice_takeover_state"] == "BLOCKED_BY_CAPTAIN_APPEARANCE"
    assert consequence["final_consequence"] == "PENDING_OFFICIAL_FINALIZATION"

    assert result["bonus_bps"]["provisional"] is True
    assert result["bonus_bps"]["status"] == "PROVISIONAL"
    assert result["match_checkpoint"]["fixtures_live"] == 1
    assert result["match_checkpoint"]["fixtures_ft"] == 0
    assert result["match_checkpoint"]["fixtures_not_started"] == 0


def test_match13_materializes_from_locked_submitted_picks_and_passes_semantics(tmp_path, monkeypatch):
    live = _run(tmp_path, monkeypatch, _snapshot())
    report = materialize_match_report(
        canonical_text=CANONICAL.read_text(encoding="utf-8"),
        live_payload=live,
        next_critical_observation="fixture 101 full-time",
    )
    assert [row["section_id"] for row in report["sections"]] == [
        f"MATCH{index}" for index in range(1, 14)
    ]
    assert report["exact_canonical_order"] is True

    body = render_match_text(report)
    assert body.count("## MATCH ") == 13
    assert "SCORING AUTHORITY: LOCKED_SUBMITTED_PICKS" in body
    assert "BENCH GK: P15" in body
    assert "OUTFIELD AUTOSUB PRIORITY: 1 P12, 2 P13, 3 P14" in body
    assert "BONUS/BPS STATUS: PROVISIONAL" in body
    assert "NEXT CRITICAL OBSERVATION: fixture 101 full-time" in body

    content_contract = report["content_contract"]
    semantic = validate_v12_visible_content_contract(
        report_mode="MATCH",
        content_contract=content_contract,
    )
    assert semantic["status"] == "PASS"
    rendered_failures = _validate_v12_rendered_body(
        report_mode="MATCH",
        rendered_body=body,
        content_contract=content_contract,
    )
    assert rendered_failures == []


def test_match13_refuses_planning_or_incomplete_team_as_scoring_authority():
    with pytest.raises(
        Exception,
        match="requires exact15 locked submitted picks",
    ):
        materialize_match_report(
            canonical_text=CANONICAL.read_text(encoding="utf-8"),
            live_payload={
                "submitted_picks_status": "UNAVAILABLE",
                "players": [{"element": 1, "name": "planning-only"}],
            },
        )
