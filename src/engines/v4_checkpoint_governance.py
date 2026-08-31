from __future__ import annotations

import argparse
import copy
import json

from src.engines.v4_decision_arbitration import SEVERITY, validate_resolution
from src.engines.v4_freshness import evaluate_freshness
from src.engines.v4_serving_contract import write_serving_payload
from src.utils import CONFIG, DATA, atomic_json, parse_dt, read_json, utcnow

OUTFILE=DATA/"checkpoint_decision_v4.json";LANGUAGE_POLICY=CONFIG/"report_language_policy.json"


def _planning_authority(locked,scorecard):
    planning=scorecard.get("planning_gw") or {};basis=planning.get("squad_basis") or {}
    if basis.get("effective_authority"):
        expected=str(basis["effective_authority"]);override_applied=bool(basis.get("override_applied"));target_gw=basis.get("override_target_gw");source=basis.get("authority_source");baseline_gw=basis.get("baseline_gw");planning_gw=basis.get("planning_gw")
    else:
        override_applied=bool(locked.get("wildcard_active"));expected="LOCKED_PRE_DEADLINE" if override_applied else "OFFICIAL_SUBMITTED";target_gw=locked.get("target_gw");source=locked.get("authority_source") if override_applied else "OFFICIAL_FPL_PICKS";baseline_gw=None;planning_gw=None
    active_chip=str(planning.get("active_chip") or "NONE").upper();wildcard_for_planning=active_chip=="WILDCARD" or (override_applied and bool(locked.get("wildcard_active")))
    return {"expected_authority":expected,"override_applied":override_applied,"override_target_gw":target_gw,"authority_source":source,"baseline_gw":baseline_gw,"planning_gw":planning_gw,"wildcard_active":wildcard_for_planning}


def _emission_contract(context):
    if context.get("post_final_emergency_only") is True:raise RuntimeError("checkpoint policy is the sole timing authority; legacy post_final_emergency_only is forbidden")
    authorized=bool(context.get("visible_output_authorized"));policy_id=str(context.get("policy_id") or "INTERNAL_HOURLY_SILENT");full_required=bool(context.get("full_visible_report_required"));no_change_required=bool(context.get("no_material_change_must_still_report"))
    if context.get("duplicate_report_forbidden") is False:raise RuntimeError("checkpoint policy must forbid duplicate visible reports")
    if policy_id in {"DEADLINE_MONITOR","FINAL_DEADLINE_REVIEW"} and (not authorized or not full_required or not no_change_required):raise RuntimeError(f"deadline report contract incomplete for {policy_id}")
    return {"status":"VISIBLE_AUTHORIZED" if authorized else "SILENT","authorized":authorized,"visible_report_count":1 if authorized else 0,"max_visible_reports":1,"single_consolidated_report":True,"duplicate_reports_forbidden":True,"policy_id":policy_id,"collision_merged":bool(context.get("collision_merged")),"absorbed_policy_ids":list(context.get("absorbed_policy_ids") or []),"full_report_required":full_required,"must_report_when_no_material_change":no_change_required,"fresh_source_sweep_required":bool(context.get("fresh_source_sweep_required")),"price_radar_required":bool(context.get("price_radar_required")),"report_scope":list(dict.fromkeys(context.get("report_scope") or [])),"suppression_allowed":not(authorized and no_change_required)}


def _downgrade_for_execution_gate(canonical,blockers):
    out=copy.deepcopy(canonical)
    if not blockers:return out
    dimensions=out.get("dimensions") or {}
    for row in dimensions.values():
        if isinstance(row,dict) and row.get("action")=="CHANGE":row["action"]="REVIEW";row.setdefault("blocking_reasons",[]).extend(blockers)
    actions=[str((dimensions.get(name) or {}).get("action") or "HOLD") for name in ("squad","transfer","xi","captaincy","chip","price")];overall=max(actions,key=lambda action:SEVERITY.get(action,-1));out["overall_action"]=overall;out["headline"]=f"{overall} | Squad {(dimensions.get('squad') or {}).get('action','HOLD')} | XI {(dimensions.get('xi') or {}).get('action','HOLD')} | C/VC {(dimensions.get('captaincy') or {}).get('action','HOLD')} | Chip {(dimensions.get('chip') or {}).get('action','HOLD')} | Price {(dimensions.get('price') or {}).get('action','HOLD')}";out["summary"]={"HOLD":"No actionable change now.","REVIEW":"Review required before any execution.","CHANGE":"Executable change is supported now."}[overall];out["execution_gate_blockers"]=blockers;validate_resolution(out);return out


def _plain_reasoning(canonical,freshness,lineup):
    overall=canonical.get("overall_action");transfer=((canonical.get("dimensions") or {}).get("transfer") or {});reasons=[]
    if overall=="HOLD":reasons.append("Struktur tim saat ini masih layak dipertahankan dan belum ada perubahan yang cukup kuat untuk dijalankan.")
    elif overall=="REVIEW":reasons.append("Struktur tim belum perlu diubah sekarang karena ada keputusan yang masih harus ditinjau sebelum eksekusi.")
    else:reasons.append("Bukti saat ini mendukung perubahan struktur tim yang sudah memenuhi syarat eksekusi.")
    if transfer.get("candidate_state")=="MATERIAL_UPGRADE_NON_ACTIONABLE":reasons.append("Ada challenger material, tetapi bukti, timing, atau kesiapan eksekusinya belum lengkap.")
    if freshness.get("freshness_state")=="STALE":reasons.append("Data terakhir sudah terlalu lama untuk dipakai sebagai dasar keputusan final dan perlu diperbarui.")
    elif freshness.get("freshness_state")!="FRESH":reasons.append("Data terbaru belum berada pada kondisi terbaik untuk keputusan final.")
    if str(lineup.get("formation_state") or "")=="OPEN":reasons.append("Formasi masih merupakan close call dan tetap terbuka untuk final review.")
    return reasons


def _plain_actions(canonical):
    overall=canonical.get("overall_action");transfer=((canonical.get("dimensions") or {}).get("transfer") or {})
    if overall=="CHANGE":return ["Konfirmasi user final lock sebelum menjalankan rekomendasi.","Pastikan tidak ada team news baru sebelum deadline."]
    if overall=="REVIEW":return ["Jangan eksekusi perubahan dulu.","Tutup alasan penahan dan close call pada final review."]
    actions=["Pertahankan struktur saat ini.","Pantau team news, risiko harga, dan challenger sampai checkpoint berikutnya."]
    if transfer.get("candidate_state")=="MATERIAL_UPGRADE_NON_ACTIONABLE":actions.append("Simpan challenger material untuk review, bukan sebagai instruksi transfer.")
    return actions


def _validate_plain_language(reasoning,actions,policy):
    combined=" ".join([*reasoning,*actions]).lower();forbidden=[str(value).lower() for value in policy.get("technical_terms_forbidden_in_primary_reasoning") or []];leaking=[value for value in forbidden if value and value in combined]
    if leaking:raise RuntimeError(f"technical language leaked into primary report reasoning: {leaking}")


def govern_checkpoint(latest,health,sanity,lineup,locked,scorecard=None,now=None,actions=None,canonical=None,effective_plan=None,team=None,tactical=None,prices=None,competitive=None):
    evaluated_at=parse_dt(now) if isinstance(now,str) else now;evaluated_at=evaluated_at or utcnow()
    if evaluated_at.tzinfo is None:raise RuntimeError("checkpoint governance now must be timezone-aware")
    scorecard=scorecard or {};context=dict(latest.get("checkpoint_context") or {});emission=_emission_contract(context);freshness=evaluate_freshness(latest,now=evaluated_at);authority=_planning_authority(locked,scorecard);expected_authority=authority["expected_authority"];authority_ok=latest.get("squad_authority")==expected_authority
    canonical=canonical or read_json(DATA/"decision_arbitration_v4.json",{})
    if not canonical.get("resolution_id"):
        raise RuntimeError("report governance requires canonical decision_arbitration artifact; report-layer recomputation is forbidden")
    validate_resolution(canonical)
    blockers=[]
    if (health.get("gate0") or {}).get("pass") is not True:blockers.append("GATE0_FAILED")
    if health.get("overall")=="RED":blockers.append("FRAMEWORK_RED")
    if not authority_ok:blockers.append("SQUAD_AUTHORITY_MISMATCH")
    if freshness.get("freshness_state")=="STALE":blockers.append("SNAPSHOT_STALE")
    if context.get("is_simulation") is True:blockers.append("SIMULATED_AS_OF")
    if health.get("critical_partial"):blockers.append("CRITICAL_FRAMEWORK_PARTIAL")
    if health.get("critical_warmup"):blockers.append("CRITICAL_PREDICTION_WARMUP")
    canonical=_downgrade_for_execution_gate(canonical,blockers);overall=canonical.get("overall_action");explicit_lineup_lock=str(lineup.get("status") or "").upper()=="FINAL_LOCKED";final_review=context.get("is_final_review") is True;lineup_state="FINAL_LOCKED" if explicit_lineup_lock else "FINAL_REVIEW_REQUIRED" if final_review else "ADJUSTABLE";execution_authorized=overall=="CHANGE" and explicit_lineup_lock and not blockers
    language_policy=read_json(LANGUAGE_POLICY,{});human_reasoning=_plain_reasoning(canonical,freshness,lineup);human_actions=_plain_actions(canonical);_validate_plain_language(human_reasoning,human_actions,language_policy);recommended=sanity.get("recommended_package") or {};planning_scorecard=scorecard.get("planning_gw") or {}
    out={"schema_version":4962,"engine":"v4.9.5-checkpoint-governance-human-report-v4.9.6-canonical","evaluated_at":evaluated_at.isoformat(),"checkpoint_context":context,"emission":emission,"action_state":overall,"headline":canonical.get("headline"),"summary":canonical.get("summary"),"structure_action":((canonical.get("dimensions") or {}).get("squad") or {}).get("action"),"canonical_resolution":canonical,"execution_gate":{"status":"BLOCKED" if blockers else "PASS","blockers":blockers,"execution_authorized":execution_authorized},"human_report":{"language_policy":language_policy.get("registry"),"audience":language_policy.get("audience","FPL_MANAGER"),"decision":overall,"headline":canonical.get("headline"),"summary":canonical.get("summary"),"why":human_reasoning,"what_to_do":human_actions,"technical_terms_suppressed_from_primary_reasoning":True,"technical_state_location":language_policy.get("technical_state_location")},"squad":{"authority":latest.get("squad_authority"),"expected_authority":expected_authority,"authority_ok":authority_ok,"baseline_gw":authority.get("baseline_gw"),"planning_gw":authority.get("planning_gw"),"planning_override_applied":authority.get("override_applied"),"planning_override_target_gw":authority.get("override_target_gw"),"authority_source":authority.get("authority_source"),"wildcard_active":authority.get("wildcard_active"),"locked_players":len(locked.get("players") or []),"composition_status":"LOCKED_15" if expected_authority=="LOCKED_PRE_DEADLINE" else "SUBMITTED_OR_CURRENT","hit_recommendation":"UNASSESSED"},"decision":{"raw_package_verdict":sanity.get("raw_package_verdict"),"governed_verdict":sanity.get("final_verdict"),"candidate_state":(((canonical.get("dimensions") or {}).get("transfer") or {}).get("candidate_state")),"recommended_replacements":recommended.get("replacements"),"recommended_out":[row.get("name") for row in recommended.get("out",[])],"recommended_in":[row.get("name") for row in recommended.get("in",[])],"material_eligible":recommended.get("material_eligible"),"engine_is_advisory":True,"user_decision_is_final_authority":True,"execution_authorized":execution_authorized},"lineup":{"status":lineup_state,"decision_authority":lineup.get("authority") or lineup.get("decision_authority") or "ENGINE_RECOMMENDATION","formation":lineup.get("formation"),"formation_state":lineup.get("formation_state"),"captain":(lineup.get("captain") or {}).get("name"),"vice_captain":(lineup.get("vice_captain") or {}).get("name"),"active_chip":(lineup.get("chip_context") or {}).get("active_chip"),"gk_selection":lineup.get("gk_selection") or {},"bench_governance":lineup.get("bench_governance") or {},"captaincy_governance":lineup.get("captaincy_governance") or {},"human_override_active":bool(planning_scorecard.get("human_override_active")),"engine_comparison":planning_scorecard.get("engine_comparison") or {},"requires_explicit_final_lock":not explicit_lineup_lock},"freshness":freshness,"readiness":{"critical_partial":list(health.get("critical_partial") or []),"critical_warmup":list(health.get("critical_warmup") or []),"reasons":blockers},"personal_gw_scorecard":{"previous_gw":scorecard.get("previous_gw") or {"status":"UNAVAILABLE"},"planning_gw":scorecard.get("planning_gw") or {"status":"UNAVAILABLE"}},"guardrails":{"primary_report_plain_fpl_language":True,"technical_reason_codes_separate_from_human_reasoning":True,"single_canonical_resolved_decision":True,"material_upgrade_alone_never_implies_change":True,"non_master_checkpoint_cannot_masquerade":True,"user_final_authority":True,"reporting_composition_only":True,"canonical_resolution_artifact_required":True,"arbitration_recomputation_forbidden":True}}
    atomic_json(OUTFILE,out)
    publication_inputs=(effective_plan,team,tactical,prices,competitive)
    if any(value is not None for value in publication_inputs):
        if any(value is None for value in publication_inputs):
            raise RuntimeError("report governance publication dependencies must be supplied together")
        serving=write_serving_payload(canonical,effective_plan,team,tactical,lineup,prices,latest,competitive);out["serving_payload"]={"path":"data/serving_payload_v4.json","canonical_resolution_id":serving.get("canonical_resolution_id"),"quick_serving_ms":serving.get("quick_serving_ms")};atomic_json(OUTFILE,out)
    return out


def run(now=None):return govern_checkpoint(read_json(DATA/"latest.json",{}),read_json(DATA/"framework_health_v4.json",{}),read_json(DATA/"recommendation_sanity_v4.json",{}),read_json(DATA/"lineup_decision_v4.json",{}),read_json(CONFIG/"locked_squad.json",{}),read_json(DATA/"gw_scorecard_v4.json",{}),now=now,canonical=read_json(DATA/"decision_arbitration_v4.json",{}),effective_plan=read_json(DATA/"effective_plan_v4.json",{}),team=read_json(DATA/"team.json",{}),tactical=read_json(DATA/"tactical_serving_v4.json",{}),prices=read_json(DATA/"prices.json",{}),competitive=read_json(DATA/"competitive_load_v4.json",{}))

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--now");args=parser.parse_args();print(json.dumps(run(args.now),ensure_ascii=False,indent=2))

if __name__=="__main__":main()
