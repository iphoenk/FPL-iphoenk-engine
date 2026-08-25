
from __future__ import annotations
import numpy as np

def monte_carlo_rank_scenarios(current_points:int, player_projections:list[dict], sims:int=5000, seed:int=42):
    rng=np.random.default_rng(seed)
    totals=np.full(sims,float(current_points))
    for p in player_projections:
        mean=float(p.get("projected_points") or 0)
        sd=max(1.2,0.75*mean+0.8)
        totals += np.maximum(0,rng.normal(mean,sd,size=sims))
    return {
        "simulations":sims,
        "projected_total_mean":round(float(totals.mean()),2),
        "p10":round(float(np.quantile(totals,0.10)),2),
        "p50":round(float(np.quantile(totals,0.50)),2),
        "p90":round(float(np.quantile(totals,0.90)),2),
        "note":"Points distribution only. Actual OR conversion requires live population/rank distribution."
    }
