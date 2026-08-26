from __future__ import annotations
from collections import Counter
from typing import Any
from src.v5.config_cache import load_json_config
from src.v5.decision.decision_trace import build_trace
from src.v5.decision.dss_evaluator import evaluate_dss
from src.v5.decision.lineup_optimizer import optimize_lineup
from src.v5.decision.package_governance import govern_packages
from src.v5.decision.package_optimizer import build_packages
CONFIG="config/v5_decision_registry.json"
def _cfg()->dict[str,Any]:
    data=load_json_config(CONFIG)
    if not isinstance(data.get("capabilities"),list) or not isinstance(data.get("capability_activation"),dict):raise RuntimeError("invalid V5 decision registry capabilities")
    return data
def _inputs(payload:dict[str,Any])->tuple[dict[str,Any],dict[str,Any],dict[str,Any],dict[str,Any],dict[str,Any]]:
    truth=payload.get("truth") if isinstance(payload.get("truth"),dict) else {}; prediction=payload.get("prediction") if isinstance(payload.get("prediction"),dict) else {}; price=payload.get("price") if isinstance(payload.get("price"),dict) else {}; rules=truth.get("rules") if isinstance(truth.get("rules"),dict) else {}; team=truth.get("team") if isinstance(truth.get("team"),dict) else {}
    if not rules or not team or not prediction:raise ValueError("decision service requires truth rules/team and prediction payload")
    return truth,prediction,price,rules,team
def _apply_team_cluster_penalty(packages:dict[str,Any],prediction:dict[str,Any],team:dict[str,Any])->dict[str,Any]:
    cfg=((_cfg().get("package_selection") or {}).get("team_cluster_penalty") or {})
    if not bool(cfg.get("enabled",True)) or packages.get("status")!="READY":return packages
    soft_limit=int(cfg.get("soft_limit",2)); weight=float(cfg.get("penalty_per_excess_player",0.35))
    pmap={int(p.get("element")):int(p.get("team_id")) for p in prediction.get("players") or [] if isinstance(p,dict) and p.get("element") is not None and p.get("team_id") is not None}
    baseline={int(r.get("element")):int(r.get("team_id")) for r in team.get("squad") or [] if isinstance(r,dict) and r.get("element") is not None and r.get("team_id") is not None}
    if not pmap or not baseline:return packages
    rows=[]
    for raw in packages.get("packages") or []:
        if not isinstance(raw,dict):continue
        row={**raw}; score=dict(row.get("score") or {})
        squad=dict(baseline)
        for out in row.get("outs") or []:
            if isinstance(out,dict) and out.get("element") is not None:squad.pop(int(out["element"]),None)
        for incoming in row.get("ins") or []:
            if isinstance(incoming,dict) and incoming.get("element") is not None:
                eid=int(incoming["element"]); team_id=pmap.get(eid)
                if team_id is not None:squad[eid]=team_id
        counts=Counter(squad.values()); excess=sum(max(0,count-soft_limit) for count in counts.values()); penalty=round(excess*weight,3)
        raw_robust=score.get("robust_score")
        if raw_robust is not None:
            score["raw_robust_score"]=raw_robust; score["team_cluster_penalty"]=penalty; score["robust_score"]=round(float(raw_robust)-penalty,3)
        row["score"]=score; row["team_cluster"]={"soft_limit":soft_limit,"club_counts":dict(counts),"excess_players":excess,"penalty":penalty}
        rows.append(row)
    rows.sort(key=lambda r:float(((r.get("score") or {}).get("robust_score") or -1e9)),reverse=True)
    out={**packages,"packages":rows,"team_cluster_penalty_applied":True,"team_cluster_penalty_model":{"soft_limit":soft_limit,"penalty_per_excess_player":weight}}
    hold=next((r for r in rows if r.get("id")=="HOLD"),None)
    if hold is not None:out["hold"]=hold
    return out
def _active_local_capabilities(packages:dict[str,Any],package_governance:dict[str,Any],lineup:dict[str,Any])->list[str]:
    cfg=_cfg(); configured={str(x) for x in cfg["capabilities"]}; activation=cfg["capability_activation"]; active=set()
    if packages.get("status")=="READY" and bool(packages.get("local_legality_prevalidated")) and package_governance.get("status")=="READY":
        active.update(configured & {str(x) for x in activation.get("package_ready") or []})
        if not bool(packages.get("team_cluster_penalty_applied")):active.discard("team_cluster_penalty")
        perf_ready=all(isinstance((row.get("score") or {}).get("performance"),dict) for row in packages.get("packages") or [] if isinstance(row,dict) and (row.get("score") or {}).get("valid"))
        if not perf_ready:active.discard("runtime_observability")
    if lineup.get("status")=="READY":active.update(configured & {str(x) for x in activation.get("lineup_ready") or []})
    return sorted(active)
def _prepare(payload:dict[str,Any])->dict[str,Any]:
    truth,prediction,price,rules,team=_inputs(payload); packages=_apply_team_cluster_penalty(build_packages(prediction,team,rules),prediction,team); package_governance=govern_packages(packages,truth); lineup=optimize_lineup(team,prediction,rules); capabilities=_active_local_capabilities(packages,package_governance,lineup); ready=packages.get("status")=="READY" and package_governance.get("status")=="READY" and lineup.get("status")=="READY"
    return {"status":"READY" if ready else "BLOCKED","model":_cfg().get("model_id"),"ruleset_id":rules.get("ruleset_id"),"packages":packages,"package_governance":package_governance,"lineup":lineup,"capabilities":capabilities,"price_context":{"alert_count":len(((price.get("alerts") or {}).get("alerts") or []))}}
def _blocked_trace(reason:str,gate0_preflight:dict[str,Any])->dict[str,Any]:
    items=gate0_preflight.get("items") if isinstance(gate0_preflight.get("items"),list) else []; return {"decision_type":"BLOCKED","action":reason,"confidence":"LOW","evidence":[{"source":"governance-service","field":"gate0_preflight","authority":"governance-service","freshness":None,"provenance":{"model":gate0_preflight.get("model"),"pass":gate0_preflight.get("pass")}}] if gate0_preflight else [],"constraints_checked":[str(x.get("id")) for x in items if x.get("id")],"production_recommendation":None}
def _finalize(payload:dict[str,Any],prepared:dict[str,Any]|None=None)->dict[str,Any]:
    truth,prediction,price,rules,_=_inputs(payload); prepared=prepared if isinstance(prepared,dict) else _prepare(payload); packages=prepared.get("packages") if isinstance(prepared.get("packages"),dict) else {}; package_governance=prepared.get("package_governance") if isinstance(prepared.get("package_governance"),dict) else {}; lineup=prepared.get("lineup") if isinstance(prepared.get("lineup"),dict) else {}; local_capabilities=prepared.get("capabilities") if isinstance(prepared.get("capabilities"),list) else []; evaluation=payload.get("evaluation") if isinstance(payload.get("evaluation"),dict) else {}; evaluation_capabilities=evaluation.get("capabilities") if isinstance(evaluation.get("capabilities"),list) else []; gate0_preflight=payload.get("gate0_preflight") if isinstance(payload.get("gate0_preflight"),dict) else {}; dss=evaluate_dss(truth,price,prediction,local_capabilities=local_capabilities,external_capability_sources={"evaluation":evaluation_capabilities}); local_ready=packages.get("status")=="READY" and package_governance.get("status")=="READY" and lineup.get("status")=="READY"; preflight_ready=bool(gate0_preflight.get("pass"))
    if local_ready:trace=build_trace(truth=truth,prediction=prediction,price=price,packages=packages,package_governance=package_governance,lineup=lineup,dss=dss,gate0_preflight=gate0_preflight); status="READY" if preflight_ready else "BLOCKED"
    else:trace=_blocked_trace("BLOCK decision output until package, package-governance and lineup authorities are READY",gate0_preflight); status="BLOCKED"
    return {"status":status,"model":_cfg().get("model_id"),"package_model":packages.get("model"),"package_governance_model":package_governance.get("model"),"ruleset_id":rules.get("ruleset_id"),"gate0_preflight_pass":preflight_ready,"local_legality_prevalidated":bool(packages.get("local_legality_prevalidated",False)),"package_count":packages.get("package_count",0),"hold":packages.get("hold"),"packages":packages.get("packages",[]),"candidate_pool":packages.get("candidate_pool",{}),"package_governance":package_governance,"selected_package":package_governance.get("selected_package"),"selected_package_id":package_governance.get("selected_package_id"),"optimizer_best_candidate":package_governance.get("optimizer_best_candidate"),"optimizer_best_challenger":package_governance.get("optimizer_best_challenger"),"lineup":lineup,"dss":dss,"decision_trace":trace,"capabilities":local_capabilities,"price_context":prepared.get("price_context",{}),"governance":{**(packages.get("governance") or {}),**(package_governance.get("governance") or {}),"manual_authority_override":bool(package_governance.get("manual_authority_override")),"lineup_authority":lineup.get("authority"),"dss_evaluation_model":dss.get("evaluation_model"),"evaluation_capabilities_consumed":sorted(str(x) for x in evaluation_capabilities),"gate0_preflight_model":gate0_preflight.get("model"),"decision_trace_required":True,"production_recommendation_enabled":bool((_cfg().get("trace") or {}).get("production_recommendation_enabled",False))},"production_recommendation":None}
def handle(operation:str,payload:dict[str,Any])->Any:
    if operation=="status":return {"status":"ACTIVE","bridge_only":False,"production_recommendation":False,"model":_cfg().get("model_id"),"capabilities":list(_cfg().get("capabilities") or []),"operations":["prepare","finalize","build"]}
    if operation=="prepare":return _prepare(payload)
    if operation=="finalize":return _finalize(payload,payload.get("prepared") if isinstance(payload.get("prepared"),dict) else None)
    if operation=="build":return _finalize(payload,_prepare(payload))
    raise KeyError(f"unsupported decision operation: {operation}")
