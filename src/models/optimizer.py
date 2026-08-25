
from __future__ import annotations
from itertools import combinations

def legal_counts(players):
    counts={"GK":0,"DEF":0,"MID":0,"FWD":0}
    clubs={}
    for p in players:
        counts[p["position"]]+=1
        clubs[p["team"]]=clubs.get(p["team"],0)+1
    return counts=={"GK":2,"DEF":5,"MID":5,"FWD":3} and max(clubs.values() or [0])<=3

def score_squad(players):
    return sum(float(p.get("projected_points_5gw") or p.get("projected_points") or 0) for p in players)

def evaluate_package(current_squad:list[dict], outs:list[int], ins:list[dict], budget_tenths:int):
    remain=[p for p in current_squad if p["element"] not in set(outs)]
    candidate=remain+ins
    total=sum(int(p["price"]) for p in candidate)
    return {
        "valid": len(candidate)==15 and legal_counts(candidate) and total<=budget_tenths,
        "total_cost":total,
        "budget":budget_tenths,
        "projected_score":score_squad(candidate) if len(candidate)==15 else None
    }
