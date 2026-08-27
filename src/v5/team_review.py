from __future__ import annotations
from collections import Counter
from typing import Any
from src.v5.config_cache import load_json_config

CONFIG="config/v5_team_review_registry.json"
def build_team_review(truth:dict[str,Any],prediction:dict[str,Any],decision:dict[str,Any],watchlist:dict[str,Any]|None=None)->dict[str,Any]:
    cfg=load_json_config(CONFIG); team=(truth.get("team") or {}) if isinstance(truth,dict) else {}; squad=[x for x in team.get("squad") or [] if isinstance(x,dict)]; pmap={int(x["element"]):x for x in prediction.get("players") or [] if isinstance(x,dict) and x.get("element") is not None}; risks=[]; club_counts=Counter()
    for row in squad:
        element=int(row.get("element") or -1); player=pmap.get(element,{})
        if row.get("team_id") is not None:club_counts[int(row["team_id"])]+=1
        xmins=player.get("xmins") if isinstance(player.get("xmins"),dict) else {}; dnp=float(xmins.get("dnp_probability") or 0.0); conf=str(player.get("projection_confidence") or "")
        if dnp>=0.20 or conf in {"LOW","VERY_LOW"}:risks.append({"element":element,"name":player.get("name"),"dnp_probability":round(dnp,4),"projection_confidence":conf or None})
    horizons={h:round(sum(float((pmap.get(int(r.get("element") or -1),{}).get(f"xpts_{h}") or 0.0)) for r in squad),3) for h in (3,5,10,15)}; watch=watchlist if isinstance(watchlist,dict) else {}
    return {"model":cfg.get("model_id"),"status":"READY","read_only":True,"may_mutate_decision":False,"squad_risk_summary":{"risk_count":len(risks),"players":risks,"club_counts":dict(sorted(club_counts.items()))},"horizon_exposure":horizons,"watchlist_pressure":{"candidate_count":int(watch.get("candidate_count") or 0)},"decision_snapshot":{"status":decision.get("status"),"selected_package_id":decision.get("selected_package_id")},"governance":cfg.get("governance")}
