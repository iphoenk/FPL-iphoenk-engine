from __future__ import annotations

from pathlib import Path

from src.runtime_v6.domains.report_plane.human_presentation_qa import validate_human_presentation_surface
from src.engines.v12_report_orchestration import (
    materialize_deadline_final_report,
    render_deep_text,
    render_match_text,
)

CANONICAL = Path(__file__).resolve().parents[1] / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"


def _section(sid: str, content: dict, state: str = "COMPLETE") -> dict:
    return {"section_id": sid, "label": sid, "state": state, "content": content}


def test_match_locked_renderer_exact_human_tables_and_no_internal_ids():
    team_rows = [
        {"name": f"P{i}", "position": "GK" if i <= 2 else "MID", "team": "ABC", "fixture_status": "LIVE"}
        for i in range(1, 16)
    ]
    points = [
        {"player": f"P{i}", "state": "LIVE", "minutes": 60, "raw_points": i, "multiplier": 1, "effective_points": i}
        for i in range(1, 16)
    ]
    report = {
        "report_mode": "MATCH",
        "sections": [
            _section("MATCH1", {"scoring_gw": 7, "fixtures_live": 2, "fixtures_ft": 3, "fixtures_not_started": 5, "timestamp": "2026-10-03T08:00:00+07:00", "lifecycle_mode": "MATCH"}),
            _section("MATCH2", {"rows": team_rows, "xi": [f"P{i}" for i in range(1,12)], "bench": [f"P{i}" for i in range(12,16)], "authority": "LOCKED_SUBMITTED_PICKS"}),
            _section("MATCH3", {"rows": [{"player": "P1", "personal_state": "LIVE_APPEARANCE", "fixture_status": "LIVE", "minutes": 60, "raw_points": 2, "multiplier": 1, "effective_points": 2}]}),
            _section("MATCH4", {"bench_gk": {"name": "P12"}, "outfield_autosub_priority": [{"name":"P13"},{"name":"P14"},{"name":"P15"}], "status": "PROVISIONAL", "potential_out": [], "bench_candidates": [], "official_finalization_authoritative": True}),
            _section("MATCH5", {"captain":{"name":"P7","raw_points":8,"multiplier":2,"effective_points":16,"appearance_state":"APPEARED"}, "vice":{"name":"P8","raw_points":5,"multiplier":1,"effective_points":5,"appearance_state":"APPEARED"}, "vice_takeover_state":"BLOCKED_BY_CAPTAIN_APPEARANCE", "final_consequence":"PENDING_OFFICIAL_FINALIZATION"}),
            _section("MATCH6", {"rows": points}),
            _section("MATCH7", {"status":"PROVISIONAL","rows":[{"player":"P7","bonus":3,"bps":40}]}),
            _section("MATCH8", {"rows":[{"player":"P3","event":"YELLOW_CARD","detail":"Booked","match_status":"LIVE","decision_implication":"Observe"}]}),
            _section("MATCH9", {"rows":[{"player":"X","club":"ABC","signal":"Role","evidence":"Live role","sustainable_noisy":"SUSTAINABLE","our15_next_opponent_implication":"Watch"}]}),
            _section("MATCH10", {"league_name":"ICON+","submitted_picks_exposure":{"state":"COMPLETE","available_count":58,"expected_count":58},"live_standings_rank":{"state":"DEGRADED"},"current_live_rank":7,"current_live_points":351,"material_player_exposure":[{"player":"P7","owned":17,"starter":16,"captain":5,"vice":3,"eo":82,"denominator":58,"live_consequence":"Shield"}],"direct_rival_live_consequence":[{"manager":"Rival","live_points":360,"gap":9,"captain":"P7","key_threat":"X","key_shield":"P7"}]}),
            _section("MATCH11", {"rows":[{"player_team":"P9","learning":"More advanced","evidence":"Role","next_gw_implication":"Reassess","action_state":"REASSESS"}]}),
            _section("MATCH12", {"observation":"P9 full-time role","why_it_matters":"Clarifies minutes and role","when_to_reassess":"After FT"}),
            _section("MATCH13", {"generated_at":"2026-10-03T08:00:00+07:00","event_live":"AVAILABLE","submitted_picks":"AVAILABLE","prediction_snapshot":"AVAILABLE","mini_league_submitted_picks":"AVAILABLE","live_standings":"DEGRADED","match_evidence_feed":"AVAILABLE"}),
        ],
    }
    body = render_match_text(report)
    assert body.count("## MATCH ") == 13
    assert "| Player | Pos | Club | Match status |" in body
    assert "| Slot | Player |" in body
    assert "| Role | Player | Raw pts | Multiplier | Effective pts | Appearance |" in body
    assert "| Player | Event | Detail | Match status | Decision implication |" in body
    assert "| Player | Club | Signal | Evidence | Sustainable / noisy | OUR15 / next-opponent implication |" in body
    assert "| Player / Team | Learning | Evidence | Next-GW implication | Action state |" in body
    assert "| P7 | 17/58 (29.3%) | 16/58 (27.6%) | 5/58 (8.6%) | 3/58 (5.2%) | 82/58 (141.4%) | Shield |" in body
    assert "element_id" not in body
    assert "LOCKED_SUBMITTED_PICKS" not in body
    assert "BLOCKED_BY_CAPTAIN_APPEARANCE" not in body
    assert "PENDING_OFFICIAL_FINALIZATION" not in body


def test_deadline_overlay_exact_tables_are_additive_not_deep_replacement():
    report = {
        "report_mode":"DEADLINE",
        "deadline_presentation":{
            "official_deadline":"03 Oct 2026, 17:00 WIB",
            "countdown":"T-30m",
            "checkpoint":"FINAL REVIEW",
            "decision_state":"WAIT",
            "S01":{"transfer_legality":"LEGAL","execution_readiness":"READY","unresolved_blocker":"None"},
            "S03":{"change_since_previous_checkpoint":"No material change","what_changed":"Fresh team news","what_did_not_change":"Football frontier","decision_change":"WAIT"},
            "S05":{"late_news_rows":[{"player":"P1","news":"Available","availability_impact":"No downgrade","evidence_tier":"OFFICIAL","as_of":"16:20 WIB","decision_impact":"No change"}],"predicted_xi_rows":[{"player":"P1","predicted_status":"START","evidence_tier":"RELIABLE_REPORTER","confidence":"HIGH","decision_consequence":"No change"}]},
            "S08":{"captain_rows":[{"role":"Captain","player":"P7","state":"LOCKED","reversal_trigger":"Official absence"},{"role":"Vice","player":"P8","state":"LOCKED","reversal_trigger":"Captain reversal"}]},
            "S14":{"route_rows":[{"route":"HOLD","legal":True,"affordable":True,"1gw":0.0,"3gw":0.0,"5gw":0.0,"p_hold":1.0,"value_of_waiting":"High","reversal_abort":"New material evidence","action":"WAIT"}]},
            "S18":{"action_board":{"NOW":"WAIT","NEXT":"Check late news","TRIGGER TO ACT":"Material edge","LATEST SAFE DECISION POINT":"T-5m","COST OF WAITING":"Low","ABORT / REVERSAL":"New negative evidence","BEST ALTERNATIVE":"HOLD"}},
        },
        "sections":[
            _section("S01",{"decision_dashboard":{}}),
            _section("S03",{"true_decision_delta":"No change"}),
            _section("S05",{"fixtures":[]}),
            _section("S08",{"captain_frontier":[]}),
            _section("S14",{"frontier":[]},state="DEGRADED"),
            _section("S18",{"action_board":{}}),
        ],
    }
    report["sections"][4]["degradation_reason"]="No optimizer rows in controlled presentation fixture"
    body=render_deep_text(report)
    assert body.startswith("FPL MASTER V12 — DEADLINE REPORT")
    assert "Official deadline: 03 Oct 2026, 17:00 WIB" in body
    assert "Countdown: T-30m" in body
    assert "| Player | News | Availability impact | Evidence tier | As of | Decision impact |" in body
    assert "| Player | Predicted status | Evidence tier | Confidence | Decision consequence |" in body
    assert "| Role | Player | State | Reversal trigger |" in body
    assert "| Route | Legal | Affordable | 1GW | 3GW | 5GW | P>HOLD | Value of waiting | Reversal / Abort | Action |" in body
    assert "| Field | Current call |" in body
    assert body.index("### Deadline state") > body.index("## 1.")


def test_final_gw_lock_package_renders_18_rows_before_alternatives():
    canonical=CANONICAL.read_text(encoding="utf-8")
    lock={
        "target_gw":7,
        "transfers_out":["P1"],
        "transfers_in":["P16"],
        "number_of_moves":1,
        "ft_hit_treatment":"1 FT / no hit",
        "bank_after_if_known":None,
        "formation":"3-5-2",
        "xi_exact11":[f"P{i}" for i in range(2,12)] + ["P16"],
        "bench_gk":"P12",
        "outfield_bench_priority_1_3":["P13","P14","P15"],
        "captain":"P7",
        "vice_captain":"P8",
        "chip":"No chip",
        "primary_action":"ACT",
        "abort_trigger":"Official absence",
        "fallback":"HOLD",
        "evidence_timestamp":"2026-10-03T16:55:00+07:00",
        "canonical_authority_version":"V12",
    }
    report=materialize_deadline_final_report(
        canonical_text=canonical,
        report_mode="FINAL",
        section_payloads={"GW_LOCK_PACKAGE":{"state":"COMPLETE","content":lock}},
        deadline_presentation={"official_deadline":"03 Oct 2026, 17:00 WIB","countdown":"T-5m","checkpoint":"FINAL CONFIRMATION","decision_state":"ACT"},
        s16b_due=False,
    )
    body=render_deep_text(report)
    package=body.split("## GW LOCK PACKAGE",1)[1].split("##",1)[0]
    table_rows=[line for line in package.splitlines() if line.startswith("| ")][2:]
    assert len(table_rows) == 18
    assert "| Bank after | UNKNOWN / UNAVAILABLE |" in package
    assert body.index("## GW LOCK PACKAGE") < body.index("PACKAGE OPTIMIZER / TRANSFER FRONTIER")


def test_common_human_presentation_qa_rejects_machine_leaks_and_allows_fpl_acronyms():
    clean = (
        "EO 82/58 (141.4%) | xPts 7.2 | xMins 88 | BPS 40 | "
        "DNP risk low | FT 1 | GW7 | FPL"
    )
    assert validate_human_presentation_surface(clean, report_mode="MATCH") == []

    leaked = (
        "element_id=123\n"
        "user_summary: {'entry_id': 3462711}\n"
        "actual_paths=500000\n"
        "workflow_id=999\n"
        "fingerprint=abc123\n"
        "CURRENT_VALID\n"
    )
    failures = validate_human_presentation_surface(leaked, report_mode="MATCH")
    assert "HUMAN_PRESENTATION_MACHINE_LANGUAGE_LEAK=element_id" in failures
    assert "HUMAN_PRESENTATION_MACHINE_LANGUAGE_LEAK=entry_id" in failures
    assert "HUMAN_PRESENTATION_MACHINE_LANGUAGE_LEAK=user_summary" in failures
    assert "HUMAN_PRESENTATION_MACHINE_LANGUAGE_LEAK=actual_paths" in failures
    assert "HUMAN_PRESENTATION_MACHINE_LANGUAGE_LEAK=raw_run_or_workflow_id" in failures
    assert "HUMAN_PRESENTATION_MACHINE_LANGUAGE_LEAK=raw_sha_or_fingerprint" in failures
    assert "HUMAN_PRESENTATION_MACHINE_LANGUAGE_LEAK=CURRENT_VALID" in failures
