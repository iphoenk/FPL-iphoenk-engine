from __future__ import annotations
import math
from typing import Any

def _f(value: Any) -> float | None:
    try: return float(value) if value is not None else None
    except (TypeError, ValueError): return None

def poisson_at_least_one(lam: Any) -> float | None:
    value=_f(lam)
    if value is None or value < 0:return None
    return 1.0-math.exp(-value)

def player_return_probabilities(xg90: Any, xa90: Any, expected_minutes: Any) -> dict[str, Any]:
    xg,xa,mins=_f(xg90),_f(xa90),_f(expected_minutes)
    if xg is None or xa is None or mins is None:
        return {"status":"UNAVAILABLE","reason":"xg90/xa90/expected_minutes evidence incomplete"}
    share=max(0.0,min(1.5,mins/90.0)); goal_lam=max(0.0,xg)*share; assist_lam=max(0.0,xa)*share
    p_goal=poisson_at_least_one(goal_lam); p_assist=poisson_at_least_one(assist_lam); p_return=1.0-(1.0-(p_goal or 0.0))*(1.0-(p_assist or 0.0))
    return {"status":"ACTIVE","contract":"independent_poisson_return_v1","goal_lambda":round(goal_lam,6),"assist_lambda":round(assist_lam,6),"p_goal":round(p_goal or 0.0,6),"p_assist":round(p_assist or 0.0,6),"p_attacking_return":round(p_return,6),"governance":{"bounded_share":True,"not_team_score_distribution":True}}
