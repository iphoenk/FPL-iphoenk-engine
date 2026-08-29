from __future__ import annotations

from datetime import datetime, timezone

from src.engines.v4_decision_arbitration import resolve_decision, validate_resolution
from src.engines.v4_freshness import evaluate_freshness
from src.engines.v4_lineup_optimizer import optimize_lineup
from src.engines.v4_tactical_serving import build_tactical_serving
from src.engines.v4_validation import validate_rows
from src.services.prediction_service import _chip_state_summary
from src.services.raw_snapshot_service import _projection_baseline_authority, detect_phase


def _fixture(xpts, start=.9, dnp=.05, event=3):
    return {"event":event,"xpts":xpts,"lower80":max(0,xpts-1.5),"upper80":xpts+1.7,"xmins":{"start_probability":start,"start_probability_confidence":.8,"bench_probability":max(0,1-start-dnp),"dnp_probability":dnp,"expected_minutes":start*80,"p60":start*.9},"components":{"appearance":1.5,"attack":max(0,xpts-2),"clean_sheet":.2,"saves":0,"defcon":.1,"bonus":.2,"tactical_adjustment":0}}


def _prediction(element, position, xpts, team="T", start=.9):
    return {"element":element,"name":f"P{element}","position":position,"team":team,"fixtures":[_fixture(xpts,start,1-start-.03)],"xpts_3":xpts*3,"xpts_5":xpts*5,"xpts_10":xpts*10,"xpts_15":xpts*15,"uncertainty":.2,"priors":{"tactical_role":position.lower(),"tactical_role_source":"test"},"value":{"xpts5_per_million":xpts*.7}}


def _universe(element, position, team="T"):
    return {"element":element,"name":f"P{element}","position":position,"team":team}


def test_chip_phase_history_and_planning_are_separate():
    history={"chips":[{"name":"bboost","event":1},{"name":"wildcard","event":2}]}
    state=_chip_state_summary({"picks":{"active_chip":None},"history":history},{"submitted_gw":2,"planning_gw":3})
    assert state["historical_used_chips"]==["BBOOST","WILDCARD"]
    assert state["planning_chip"]=="NONE"
    assert state["submitted_chip"]=="NONE"


def test_stale_manual_wildcard_override_cannot_leak_to_new_gw():
    result=_projection_baseline_authority({"wildcard_active":True,"target_gw":2,"authority_source":"USER"},{"planning_gw":3,"submitted_gw":2})
    assert result["override_applied"] is False
    assert result["effective_authority"]=="OFFICIAL_SUBMITTED"
    assert result["stale_override_rejected"] is True


def test_match_day_and_live_match_are_distinct():
    bootstrap={"events":[{"id":2,"is_current":True,"is_next":False,"finished":False,"deadline_time":"2026-08-28T17:30:00+00:00"},{"id":3,"is_current":False,"is_next":True,"finished":False,"deadline_time":"2026-09-04T17:30:00+00:00"}]}
    fixtures=[{"id":11,"event":2,"kickoff_time":"2026-08-29T11:30:00+00:00","started":False,"finished":False,"finished_provisional":False}]
    before=detect_phase(bootstrap,fixtures,datetime(2026,8,29,9,0,tzinfo=timezone.utc))
    assert before["match_day_active"] is True and before["is_live_match"] is False
    fixtures[0]["started"]=True
    during=detect_phase(bootstrap,fixtures,datetime(2026,8,29,12,0,tzinfo=timezone.utc))
    assert during["match_day_active"] is True and during["is_live_match"] is True


def test_freshness_thresholds_and_non_master_minute():
    latest={"generated_at":"2026-08-29T09:00:00+00:00","official_snapshot_at":"2026-08-29T09:00:00+00:00","phase":{"is_live_match":True},"checkpoint_context":{"policy_id":"MATCH_MODE","is_master_hourly_checkpoint":False}}
    fresh=evaluate_freshness(latest,now="2026-08-29T09:05:00+00:00")
    stale=evaluate_freshness(latest,now="2026-08-29T09:11:00+00:00")
    assert fresh["freshness_state"]=="FRESH" and fresh["max_source_age_minutes"]==10
    assert stale["freshness_state"]=="STALE"
    assert fresh["checkpoint_slot_state"]=="NON_MASTER_EVALUATION"
    assert fresh["authoritative_master_checkpoint"] is False


def _serving_fixture_set():
    owned_positions=["GK","GK","DEF","DEF","DEF","DEF","DEF","MID","MID","MID","MID","MID","FWD","FWD","FWD"]
    owned=[];pred=[];uni=[]
    for i,pos in enumerate(owned_positions,1):
        owned.append({"element":i,"name":f"P{i}","position":pos});pred.append(_prediction(i,pos,4.0+i*.01,team=f"T{i%5}"));uni.append(_universe(i,pos,team=f"T{i%5}"))
    element=100
    for pos in ("GK","DEF","MID","FWD"):
        for j in range(7):
            pred.append(_prediction(element,pos,3.5+j*.2,team=f"X{j%5}"));uni.append(_universe(element,pos,team=f"X{j%5}"));element+=1
    return {"players":pred},{"players":uni},{"squad":owned}


def test_tactical_serving_is_exact_15_plus_20_and_never_fabricates():
    predictions,universe,team=_serving_fixture_set();out=build_tactical_serving(predictions,universe,team,external={})
    assert out["counts"]["owned"]==15 and out["counts"]["watchlist"]==20
    assert {p:out["counts"][p] for p in ("GK","DEF","MID","FWD")}=={"GK":5,"DEF":5,"MID":5,"FWD":5}
    assert all(row["tactical"]["tactical_delta_applied"]==0 for row in [*out["owned"],*out["watchlist"]])
    assert all(row["tactical"]["evidence_state"] in {"MODEL_ROLE_ONLY","UNAVAILABLE"} for row in [*out["owned"],*out["watchlist"]])


def test_material_upgrade_is_review_when_not_actionable_not_change():
    predictions,universe,team=_serving_fixture_set();tactical=build_tactical_serving(predictions,universe,team,external={});team["free_transfers"]=None
    sanity={"final_verdict":"MATERIAL_UPGRADE","recommended_package":{"replacements":1,"out":[{"element":8,"name":"P8"}],"in":[{"element":100,"name":"P100"}],"sanity_gain_5":3.2,"evidence_confidence":.82}}
    lineup={"formation":"3-4-3","formation_state":"DECIDED","captain":{"element":13,"name":"P13"},"vice_captain":{"element":8,"name":"P8"},"chip_context":{"active_chip":"NONE"},"gk_selection":{"status":"DECIDED"},"bench_governance":{"status":"DECIDED"},"captaincy_governance":{"status":"DECIDED"}}
    latest={"generated_at":"2026-08-29T09:00:00+00:00","official_snapshot_at":"2026-08-29T09:00:00+00:00","phase":{"planning_gw":3,"is_live_match":False},"checkpoint_context":{"policy_id":"INTERNAL_HOURLY_SILENT","is_final_review":False,"deadline_day_active":False}}
    resolution=resolve_decision(sanity,lineup,latest,team,{"confirmed_changes":[]},tactical,predictions,now="2026-08-29T09:05:00+00:00")
    transfer=resolution["dimensions"]["transfer"]
    assert resolution["overall_action"]=="REVIEW"
    assert transfer["candidate_state"]=="MATERIAL_UPGRADE_NON_ACTIONABLE"
    assert transfer["material_challenger_label"]=="NON_ACTIONABLE_MATERIAL_CHALLENGER"
    assert transfer["blocking_reasons"]
    assert transfer["action"]!="CHANGE"
    validate_resolution(resolution)


def test_lineup_exposes_all_legal_formations_risk_gk_bench_and_captain_reasoning():
    predictions,universe,team=_serving_fixture_set();locked={"players":[{"element":row["element"]} for row in team["squad"]],"wildcard_active":False}
    out=optimize_lineup(predictions,universe,locked)
    assert len(out["starting_xi"])==11
    assert len(out["formation_alternatives"])>=3
    assert all("risk_adjusted_score" in row and "uncertainty" in row and "dnp_risk" in row and "structural_correlation_penalty" in row for row in out["formation_alternatives"])
    assert out["gk_selection"]["status"] in {"OPEN","DECIDED"}
    assert out["bench_governance"]["status"] in {"OPEN","DECIDED"}
    assert out["captaincy_governance"]["captain_candidates"][0]["reason"]


def test_validation_has_position_drift_start_dnp_logloss_and_tactical_lift():
    rows=[{"element":1,"position":"MID","predicted":5.0,"predicted_without_tactical":4.5,"actual":6.0,"lower80":2.0,"upper80":8.0,"predicted_minutes":80,"actual_minutes":90,"actual_started":True,"start_probability":.9,"dnp_probability":.03,"p60":.85,"available_at":"2026-08-28T10:00:00+00:00"},{"element":2,"position":"MID","predicted":3.0,"predicted_without_tactical":3.5,"actual":2.0,"lower80":1.0,"upper80":5.0,"predicted_minutes":30,"actual_minutes":0,"actual_started":False,"start_probability":.25,"dnp_probability":.5,"p60":.1,"available_at":"2026-08-28T10:00:00+00:00"}]
    metrics=validate_rows(rows,"2026-08-28T17:30:00+00:00")
    assert metrics["by_position"]["MID"]["bias"] is not None
    assert metrics["minutes"]["start_log_loss"] is not None
    assert metrics["minutes"]["dnp_brier"] is not None and metrics["minutes"]["dnp_log_loss"] is not None
    assert metrics["tactical_ablation"]["status"]=="PASS"
