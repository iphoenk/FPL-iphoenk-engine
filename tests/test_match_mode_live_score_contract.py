from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines import live_state_service as service
from src.engines.v12_final_delivery_barrier import validate_final_delivery_barrier
from src.engines.visible_mode_presentation_locks import validate_match_presentation_lock
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
    assert "Submitted FPL picks locked at deadline." in body
    assert "| GK | P15 |" in body
    assert "| 1 | P12 |" in body and "| 2 | P13 |" in body and "| 3 | P14 |" in body
    assert "## MATCH 7 — BONUS / BPS" in body
    assert "Status: Provisional" in body
    assert "Next critical observation\nfixture 101 full-time" in body
    assert "element_id" not in body
    assert "LOCKED_SUBMITTED_PICKS" not in body

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


def test_stage_f_match_final_barrier_requires_single_report_and_incremental_obligation(tmp_path, monkeypatch):
    live = _run(tmp_path, monkeypatch, _snapshot())
    report = materialize_match_report(
        canonical_text=CANONICAL.read_text(encoding="utf-8"),
        live_payload=live,
        next_critical_observation="fixture 101 full-time",
    )
    body = render_match_text(report)
    finalization = {
        "final_report_due": True,
        "visible_report_count": 1,
        "combined_report": False,
        "dynamic_lifecycle_event": "POST_MATCH",
        "final_mode": "MATCH",
        "embedded_obligations": ["POST_MATCH_INCREMENTAL"],
    }
    result = validate_final_delivery_barrier(
        report_mode="MATCH",
        report=report,
        body=body,
        finalization=finalization,
    )
    assert result["status"] == "PASS", result["failures"]
    assert result["can_emit"] is True

    broken = dict(finalization)
    broken["embedded_obligations"] = []
    failed = validate_final_delivery_barrier(
        report_mode="MATCH",
        report=report,
        body=body,
        finalization=broken,
    )
    assert "POST_MATCH_INCREMENTAL_OBLIGATION_MISSING" in failed["failures"]

    duplicate = dict(report)
    duplicate["sections"] = list(report["sections"]) + [dict(report["sections"][-1])]
    duplicate_result = validate_final_delivery_barrier(
        report_mode="MATCH",
        report=duplicate,
        body=body,
        finalization=finalization,
    )
    assert duplicate_result["status"] == "FAIL"
    assert "MATCH_DUPLICATE_SECTION" in duplicate_result["failures"]


def test_locked_match_golden_surface_runs_in_required_lifecycle_ci(tmp_path, monkeypatch):
    assert validate_match_presentation_lock() == []
    live = _run(tmp_path, monkeypatch, _snapshot())
    report = materialize_match_report(
        canonical_text=CANONICAL.read_text(encoding="utf-8"),
        live_payload=live,
        next_critical_observation="fixture 101 full-time",
        next_critical_reason="clarifies autosub and role consequence",
        next_reassess_at="after fixture 101 FT",
    )
    body = render_match_text(report)
    assert body.count("## MATCH ") == 13
    assert "| Player | Pos | Club | Match status |" in body
    assert "| Slot | Player |" in body
    assert "| Role | Player | Raw pts | Multiplier | Effective pts | Appearance |" in body
    assert "| Player | Match status | Minutes | Raw pts | Multiplier | Effective pts |" in body
    assert "| Player | Bonus | BPS |" in body
    assert "Bench GK:" in body
    assert "Outfield autosub priority:" in body
    assert "Next critical observation\nfixture 101 full-time" in body
    assert "Why it matters\nclarifies autosub and role consequence" in body
    assert "When to reassess\nafter fixture 101 FT" in body
    assert "element_id" not in body
    assert "LOCKED_SUBMITTED_PICKS" not in body


# Public-first MATCH V6 binding and independent-auth regression acceptance.
from src.engines.v12_match_occurrence import PublicMatchError, build_public_match
from src.engines.v12_delivery_reliability import write_serving_artifacts
from src.engines.v12_report_production_gate import evaluate_report_production_gate

SLOT = "2026-10-10T20:57:00+07:00"

def _put(root: Path, name: str, value: dict) -> None:
    path = root / "data/v6" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _runtime(tmp_path: Path, *, invalid_count: bool = False, gw: int = 6) -> Path:
    manager_picks = []
    for element in range(1, 16):
        manager_picks.append({
            "element_id": element,
            "squad_position": element,
            "multiplier": 2 if element == 7 else (1 if element <= 11 else 0),
            "captain": element == 7,
            "vice_captain": element == 8,
            "bench_order": element - 11 if element > 11 else None,
        })
    entries = {
        str(1000 + i): {
            "status": "AVAILABLE",
            "picks": manager_picks,
            "checked_at": "2026-10-10T13:57:00+00:00",
        }
        for i in range(57)
    }
    entries["3462711"] = {
        "status": "AVAILABLE",
        "picks": manager_picks[:14] if invalid_count else manager_picks,
        "checked_at": "2026-10-10T13:57:00+00:00",
    }
    _put(tmp_path, "report_prefetch/occurrences/match_mode__20261010_205700_plus_0700.json", {
        "report_kind": "match_mode",
        "target_logical_report_slot": SLOT,
        "gw": gw,
        "entry_id": 3462711,
        "priority_league_id": 9477,
        "public_core_complete": True,
        "mini_league_status": "AVAILABLE",
        "live_status": "AVAILABLE",
        "expected_manager_count": 58,
        "report_prefetch_run_id": "test-bound",
    })
    _put(tmp_path, "mini_leagues/9477/gw_6_manager_picks.json", {
        "gw": 6, "complete": True, "submitted_picks_missing_count": 0,
        "generated_at": "2026-10-10T13:57:00+00:00", "entries": entries,
    })
    _put(tmp_path, "mini_leagues/9477/live_state.json", {
        "gw": 6, "status": "AVAILABLE", "checked_at": "2026-10-10T13:57:00+00:00",
        "elements": [
            {"element_id": i, "total_points": i, "minutes": 75, "bonus": 0, "bps": i}
            for i in range(1, 16)
        ],
    })
    _put(tmp_path, "mini_leagues/9477/standings.json", {
        "league_name": "ICON+ League", "complete": True,
        "generated_at": "2026-10-10T13:57:00+00:00",
        "managers": [
            {"entry_id": 1000 + i, "league_rank": i + 1}
            for i in range(57)
        ] + [{"entry_id": 3462711, "league_rank": 7}],
    })
    _put(tmp_path, "normalized/canonical_players.json", {
        "players": [
            {"official_fpl_element_id": i, "web_name": f"P{i}", "team_id": 1,
             "element_type": 1 if i in {1, 15} else (2 if i <= 6 else (3 if i <= 11 else 4))}
            for i in range(1, 16)
        ]
    })
    _put(tmp_path, "normalized/canonical_fixtures.json", {
        "fixtures": [{"event": 6, "team_h": 1, "team_a": 2,
                      "started": True, "finished": False}]
    })
    _put(tmp_path, "normalized/canonical_teams.json", {
        "teams": [
            {"official_fpl_team_id": 1, "name": "Alpha"},
            {"official_fpl_team_id": 2, "name": "Beta"},
        ]
    })
    return tmp_path


def test_match_public_without_auth_is_13_section_degraded_and_real_exposure(tmp_path):
    root = _runtime(tmp_path)
    bundle = build_public_match(
        runtime_data_root=root, report_slot=SLOT,
        canonical_text=CANONICAL.read_text(encoding="utf-8"),
    )
    ids = [row["section_id"] for row in bundle["report"]["sections"]]
    assert ids == [f"MATCH{i}" for i in range(1, 14)]
    assert bundle["report_mode"] == "MATCH"
    assert bundle["runner_status"] == "DEGRADED"
    assert bundle["execution_proof"]["source_evidence"]["auth_required"] is False
    assert bundle["report"]["sections"][9]["state"] == "DEGRADED"
    assert "P7" in bundle["visible_body"]
    assert "Coverage: 58/58" in bundle["visible_body"]
    assert "## MATCH 13" in bundle["visible_body"]
    assert "AUTH_AVAILABLE" not in bundle["visible_body"]
    out = tmp_path / "out"
    snapshot = write_serving_artifacts(bundle=bundle, output_dir=out)
    assert list(snapshot["sections"]) == ids
    assert snapshot["delivery_status"] == "READY_DEGRADED"
    verdict = evaluate_report_production_gate(
        bundle, serving_snapshot=snapshot, visible_body_non_empty=True,
    )
    assert verdict["status"] == "PASS", verdict


def test_match_rejects_incomplete_official_15(tmp_path):
    root = _runtime(tmp_path, invalid_count=True)
    with pytest.raises(PublicMatchError, match="MATCH_LOCKED_XI_INCOMPLETE"):
        build_public_match(
            runtime_data_root=root, report_slot=SLOT,
            canonical_text=CANONICAL.read_text(encoding="utf-8"),
        )


def test_match_rejects_wrong_gw_or_stale_prefetch(tmp_path):
    root = _runtime(tmp_path, gw=5)
    with pytest.raises(PublicMatchError, match="PUBLIC_FACT_MISSING_OR_INVALID:gw_5_manager_picks"):
        build_public_match(
            runtime_data_root=root, report_slot=SLOT,
            canonical_text=CANONICAL.read_text(encoding="utf-8"),
        )
    with pytest.raises(PublicMatchError, match="PUBLIC_FACT_MISSING_OR_INVALID:match_mode__20261010_205900"):
        build_public_match(
            runtime_data_root=root, report_slot="2026-10-10T20:59:00+07:00",
            canonical_text=CANONICAL.read_text(encoding="utf-8"),
        )
