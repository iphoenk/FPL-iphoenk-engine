
from __future__ import annotations
import math

def clamp(x,a,b): return max(a,min(b,x))

def simple_xmins(player:dict, advanced:dict|None=None):
    # Conservative baseline. This is intentionally interpretable, not "AI magic".
    status=player.get("status","a")
    if status in {"i","s","u"}: return 0.05
    mins=float(player.get("minutes") or 0)
    starts_proxy=min(1.0, mins/90.0)
    base=0.72+0.23*clamp(starts_proxy,0,1)
    return clamp(base,0.05,0.98)

def project_points(player:dict, advanced:dict|None=None, fixture_difficulty:float=3.0):
    adv=advanced or {}
    xmins=simple_xmins(player,adv)
    xg=float(adv.get("expected_goals") or 0)
    xa=float(adv.get("expected_assists") or 0)
    pos=player.get("element_type")
    goal_pts={1:6,2:6,3:5,4:4}.get(pos,4)
    cs_pts={1:4,2:4,3:1,4:0}.get(pos,0)
    # Very simple per-90 translation; used as a scaffold until calibrated model is trained.
    appearance=2*xmins
    attacking=(xg*goal_pts + xa*3)*xmins
    cs_prob=clamp(0.50 - 0.08*(fixture_difficulty-2),0.08,0.60)
    clean=cs_pts*cs_prob*xmins
    bonus=0.35*xmins
    return {
        "xmins_probability":round(xmins,4),
        "projected_points":round(appearance+attacking+clean+bonus,3),
        "components":{"appearance":round(appearance,3),"attack":round(attacking,3),
                      "clean_sheet":round(clean,3),"bonus":round(bonus,3)},
        "model":"interpretable_scaffold_v1",
        "confidence":"LOW-MEDIUM until multi-GW calibration"
    }
