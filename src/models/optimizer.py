from __future__ import annotations

def legal_counts(players):
    counts={"GK":0,"DEF":0,"MID":0,"FWD":0}; clubs={}
    for p in players:
        counts[p["position"]]+=1; club=p.get("team_id",p.get("team")); clubs[club]=clubs.get(club,0)+1
    return counts=={"GK":2,"DEF":5,"MID":5,"FWD":3} and max(clubs.values(),default=0)<=3

def score_squad(players,horizon=5):
    total=0.0
    for p in players:
        series=p.get("xpts_by_gw")
        total += sum(series[:horizon]) if series else float(p.get("projected_points_5gw") or p.get("projected_points") or 0)
    return total

def evaluate_package(current_squad:list[dict], outs:list[int], ins:list[dict], budget_tenths:int,hit_cost:int=0,horizon:int=5,captain_delta:float=0,bench_delta:float=0):
    remain=[p for p in current_squad if p["element"] not in set(outs)]; candidate=remain+ins
    total=sum(int(p.get("price",p.get("now_cost",0))) for p in candidate)
    valid=len(candidate)==15 and legal_counts(candidate) and total<=budget_tenths
    before=score_squad(current_squad,horizon); after=score_squad(candidate,horizon) if len(candidate)==15 else 0
    net=after-before-hit_cost+captain_delta+bench_delta if valid else None
    return {"valid":valid,"total_cost":total,"budget":budget_tenths,"horizon":horizon,"before_xpts":round(before,2),"after_xpts":round(after,2) if valid else None,"hit_cost":hit_cost,"captain_delta":captain_delta,"bench_delta":bench_delta,"net_gain":round(net,2) if net is not None else None}
