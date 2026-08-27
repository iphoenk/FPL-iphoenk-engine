from __future__ import annotations
import math
import random
from statistics import NormalDist
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/correlated_simulation.json"

def _f(v: Any, d: float = 0.0) -> float:
    try: return float(d if v is None else v)
    except (TypeError, ValueError): return float(d)

def _normal_sample(rng: random.Random, mean: float, std: float) -> float:
    return mean + max(0.0, std) * rng.gauss(0.0, 1.0)

def _quantile(values: list[float], q: float) -> float | None:
    if not values: return None
    rows=sorted(values); idx=max(0,min(len(rows)-1,int(round((len(rows)-1)*q))))
    return rows[idx]

def simulate_package_delta(challenger: dict[str, Any], hold: dict[str, Any], *, seed: int | None = None) -> dict[str, Any]:
    cfg=load_json_config(CONFIG); rng=random.Random(int(cfg.get("seed") if seed is None else seed))
    min_draws=max(100,int(cfg.get("minimum_draws") or 2000)); batch=max(100,int(cfg.get("batch_draws") or 1000)); max_draws=max(min_draws,int(cfg.get("maximum_draws") or 20000)); target=max(1e-6,_f(cfg.get("adaptive_stop_probability_se"),0.0075))
    team_rho=max(0.0,min(0.95,_f(cfg.get("team_common_shock_rho"),0.18))); opp_rho=max(0.0,min(0.95,_f(cfg.get("opponent_common_shock_rho"),0.10))); min_std=max(0.01,_f(cfg.get("minimum_std"),0.25))
    def stats(row: dict[str,Any])->tuple[float,float]:
        score=row.get("score") if isinstance(row.get("score"),dict) else {}; mean=_f(score.get("raw_robust_score"),_f(score.get("robust_score"))); std=max(min_std,_f((row.get("monte_carlo") or {}).get("std"),_f(score.get("uncertainty"),1.5))); return mean,std
    cm,cs=stats(challenger); hm,hs=stats(hold); deltas=[]; wins=0; draws=0
    while draws < max_draws:
        for _ in range(min(batch,max_draws-draws)):
            common_team=rng.gauss(0,1); common_opp=rng.gauss(0,1); c_id=rng.gauss(0,1); h_id=rng.gauss(0,1)
            c_z=math.sqrt(team_rho)*common_team+math.sqrt(opp_rho)*common_opp+math.sqrt(max(0.0,1-team_rho-opp_rho))*c_id
            h_z=math.sqrt(team_rho)*common_team+math.sqrt(opp_rho)*common_opp+math.sqrt(max(0.0,1-team_rho-opp_rho))*h_id
            delta=(cm+cs*c_z)-(hm+hs*h_z); deltas.append(delta); wins+=int(delta>0); draws+=1
        if draws>=min_draws:
            p=wins/draws; se=math.sqrt(max(1e-9,p*(1-p)/draws))
            if se <= target: break
    p=wins/max(1,draws); se=math.sqrt(max(1e-9,p*(1-p)/max(1,draws)))
    return {"model":cfg.get("model_id"),"status":"SHADOW_ONLY","seed":int(cfg.get("seed") if seed is None else seed),"draws":draws,"adaptive_stopped":draws<max_draws,"p_outperform_hold_correlated":round(p,6),"probability_standard_error":round(se,6),"delta_mean":round(sum(deltas)/len(deltas),4) if deltas else None,"delta_p10":round(_quantile(deltas,0.10),4) if deltas else None,"delta_p50":round(_quantile(deltas,0.50),4) if deltas else None,"delta_p90":round(_quantile(deltas,0.90),4) if deltas else None,"decision_authority":False}
