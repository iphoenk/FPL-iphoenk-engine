from __future__ import annotations
from typing import Any
from src.v5.config_cache import load_json_config
CONFIG="config/v5_watchlist_registry.json"; CORE="config/dss_core_registry.json"; EXT="config/dss_extension_registry.json"
def _f(value:Any,default:float=0.0)->float:
    try:return float(default if value is None else value)
    except (TypeError,ValueError):return float(default)
def _clip(value:float)->float:return max(0.0,min(1.0,value))
def _owned_ids(team:dict[str,Any])->set[int]:
    rows=team.get("team_value_ledger") or team.get("squad") or []; return {int(x.get("element")) for x in rows if isinstance(x,dict) and x.get("element") is not None}
def _position(player:dict[str,Any])->str:
    raw=str(player.get("position") or "").upper(); return {"1":"GK","2":"DEF","3":"MID","4":"FWD","GKP":"GK"}.get(raw,raw)
def _dss_traversal()->dict[str,Any]:
    core=load_json_config(CORE).get("modules") or []; ext=load_json_config(EXT).get("modules") or []; return {"core_ids":[str(x.get("id")) for x in core],"extension_ids":[str(x.get("id")) for x in ext],"core_count":len(core),"extension_count":len(ext),"all_modules_traversed":bool(core and ext)}
def _dimension_scores(player:dict[str,Any],cfg:dict[str,Any])->tuple[dict[str,float|None],dict[str,Any]]:
    xmins=player.get("xmins") if isinstance(player.get("xmins"),dict) else {}; role=player.get("role") if isinstance(player.get("role"),dict) else {}; current=player.get("current_season") if isinstance(player.get("current_season"),dict) else {}; hist=player.get("historical_prior") if isinstance(player.get("historical_prior"),dict) else {}; norm=cfg.get("normalization") or {}
    start_p,exp_mins=_f(xmins.get("start_probability")),_f(xmins.get("expected_minutes")); x5,x15=_f(player.get("xpts_5")),_f(player.get("xpts_15")); cost_m=max(.1,_f(player.get("now_cost"))/10); xg=_f(current.get("expected_goals") or current.get("xg") or hist.get("xg_per90")); xa=_f(current.get("expected_assists") or current.get("xa") or hist.get("xa_per90")); role_conf=_f(role.get("confidence") or role.get("role_confidence"),.6 if role else 0); set_piece=any(source.get(key) is not None for source in (role,hist,player) for key in ("penalty_share","penalty_role","set_piece_share","set_piece_role"))
    scores={"role":_clip(role_conf) if role else None,"xmins":_clip(start_p*.65+_clip(exp_mins/90)*.35) if xmins else None,"fixtures_3_5":_clip(x5/_f(norm.get("xpts_5_reference"),30)) if x5>0 else None,"underlying":_clip((xg+xa)/1.2) if current or hist else None,"system_fit":_clip(max(role_conf,start_p)) if role or xmins else None,"competition":_clip(start_p) if xmins else None,"set_piece_penalty":1.0 if set_piece else (.35 if role else None),"price_value":_clip((x5/cost_m)/_f(norm.get("value_reference_xpts_per_million"),4.5)) if x5>0 else None,"squad_fit":.65}
    evidence={"start_probability":start_p,"expected_minutes":exp_mins,"dnp_probability":_f(xmins.get("dnp_probability"),max(0,1-start_p)),"xpts_5":x5,"xpts_15":x15,"now_cost":player.get("now_cost"),"ownership_pct":player.get("ownership_pct"),"projection_confidence":player.get("projection_confidence"),"role_available":bool(role),"historical_prior_available":bool(hist),"set_piece_penalty_evidence":set_piece}; return scores,evidence
def build_watchlist(prediction:dict[str,Any],team:dict[str,Any],dss:dict[str,Any]|None=None)->dict[str,Any]:
    cfg=load_json_config(CONFIG); admission=cfg.get("admission") or {}; weights={str(k):_f(v) for k,v in (cfg.get("dimension_weights") or {}).items()}; positions=[str(x) for x in cfg.get("positions") or ["GK","DEF","MID","FWD"]]; owned=_owned_ids(team); ranked={p:[] for p in positions}; rejected=0; traversal=_dss_traversal(); dss=dss or {}; critical_dss_failed=bool((dss.get("summary") or {}).get("critical_failed",False))
    for player in prediction.get("players") or []:
        if not isinstance(player,dict) or player.get("element") is None:continue
        element=int(player["element"])
        if element in owned and bool((cfg.get("governance") or {}).get("exclude_owned_players",True)):continue
        if str(player.get("status") or "a") not in {str(x) for x in cfg.get("allowed_statuses") or ["a","d"]}:continue
        position=_position(player)
        if position not in ranked:continue
        scores,evidence=_dimension_scores(player,cfg); available=sum(weights.get(k,0) for k,v in scores.items() if v is not None); total=sum(weights.values()) or 1; coverage=available/total; critical=[scores.get(str(k)) for k in admission.get("critical_dimensions") or []]; critical_available=[_f(x) for x in critical if x is not None]; critical_score=sum(critical_available)/len(critical_available) if critical_available else 0
        eligible=coverage>=_f(admission.get("minimum_dimension_coverage"),.70) and evidence["start_probability"]>=_f(admission.get("minimum_start_probability"),.45) and evidence["dnp_probability"]<=_f(admission.get("maximum_dnp_probability"),.35) and critical_score>=_f(admission.get("minimum_critical_dimension_score"),.60) and not (critical_dss_failed and admission.get("block_on_critical_dss_failure",True))
        if not eligible:rejected+=1;continue
        weighted=sum(weights.get(k,0)*_f(v) for k,v in scores.items() if v is not None); score=weighted/max(available,1e-9); ranked[position].append({"element":element,"name":player.get("name"),"position":position,"team_id":player.get("team_id"),"price":round(_f(player.get("now_cost"))/10,1),"score":round(score,4),"dimension_coverage":round(coverage,4),"critical_dimension_score":round(critical_score,4),"dimensions":scores,"evidence":evidence,"action":"WATCH","confidence":str(player.get("projection_confidence") or "UNKNOWN")})
    limit=int(cfg.get("max_per_position") or 5)
    for pos in positions:ranked[pos]=sorted(ranked[pos],key=lambda row:(-_f(row.get("score")),-_f((row.get("evidence") or {}).get("xpts_5"))))[:limit]
    count=sum(len(x) for x in ranked.values()); return {"schema_version":int(cfg.get("schema_version") or 1),"model":cfg.get("model_id"),"screening_contract":cfg.get("screening_contract"),"status":"READY" if count else "INSUFFICIENT_EVIDENCE","positions":ranked,"candidate_count":count,"rejected":rejected,"owned_excluded":len(owned),"dss_traversal":traversal,"governance":cfg.get("governance") or {}}
