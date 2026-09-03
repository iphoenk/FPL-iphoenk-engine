from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from time import perf_counter

from src.engines import v4_full_universe_package_search as facade
from src.engines.v4_decision_pipeline import effective_planning_squad
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_wc_optimizer import build_candidates, reconcile_owned_costs
from src.utils import CONFIG, DATA, read_json

MIN_KEYS = tuple(facade._MINIMIZE)
MAX_KEYS = tuple(facade._MAXIMIZE)
DEC_MIN = {"cost", "projection_uncertainty", "xmins_uncertainty", "tactical_uncertainty", "roster_change_uncertainty", "price_risk"}
DEC_MAX = {"xpts_3", "xpts_5", "xpts_10", "xpts_15", "gw_xpts_1", "gw_xpts_2", "gw_xpts_3", "gw_xpts_4", "gw_xpts_5", "tactical_role_confidence", "opponent_matchup_confidence"}


def player_state(player, dims):
    gw = tuple(float(dims[f"gw_xpts_{i}"]) for i in range(1,6))
    confidence = float(dims["sanity_confidence"])
    spike = float(dims["rate_spike_risk"])
    season = float(dims["current_season_weight"])
    return {
        "ids": (player.element,),
        "mins": tuple(float(dims[k]) for k in MIN_KEYS),
        "maxs": tuple(float(dims[k]) for k in MAX_KEYS),
        "gw_orders": tuple((v,) for v in gw),
        "conf_order": (confidence,),
        "spike_order": (spike,),
        "season_order": (season,),
    }


def merge(a,b):
    return {
        "ids": tuple(sorted(a["ids"]+b["ids"])),
        "mins": tuple(x+y for x,y in zip(a["mins"],b["mins"])),
        "maxs": tuple(x+y for x,y in zip(a["maxs"],b["maxs"])),
        "gw_orders": tuple(tuple(sorted(x+y, reverse=True)) for x,y in zip(a["gw_orders"],b["gw_orders"])),
        "conf_order": tuple(sorted(a["conf_order"]+b["conf_order"])),
        "spike_order": tuple(sorted(a["spike_order"]+b["spike_order"], reverse=True)),
        "season_order": tuple(sorted(a["season_order"]+b["season_order"])),
    }


def dominates(a,b,eps=1e-9):
    min_ok = all(x <= y + eps for x,y in zip(a["mins"],b["mins"]))
    max_ok = all(x + eps >= y for x,y in zip(a["maxs"],b["maxs"]))
    gw_ok = all(all(x + eps >= y for x,y in zip(ax,bx)) for ax,bx in zip(a["gw_orders"],b["gw_orders"]))
    conf_ok = all(x + eps >= y for x,y in zip(a["conf_order"],b["conf_order"]))
    spike_ok = all(x <= y + eps for x,y in zip(a["spike_order"],b["spike_order"]))
    season_ok = all(x + eps >= y for x,y in zip(a["season_order"],b["season_order"]))
    if not (min_ok and max_ok and gw_ok and conf_ok and spike_ok and season_ok):
        return False
    strict = False
    for i,k in enumerate(MIN_KEYS):
        if k in DEC_MIN and a["mins"][i] + eps < b["mins"][i]: strict=True
    for i,k in enumerate(MAX_KEYS):
        if k in DEC_MAX and a["maxs"][i] > b["maxs"][i] + eps: strict=True
    if not strict:
        for ax,bx in zip(a["gw_orders"],b["gw_orders"]):
            if any(x > y + eps for x,y in zip(ax,bx)): strict=True; break
    return strict


def insert(frontier,row):
    for inc in frontier:
        if dominates(inc,row): return False
    kept=[]
    for inc in frontier:
        if not dominates(row,inc): kept.append(inc)
    kept.append(row)
    frontier[:] = kept
    return True


def main():
    t0=perf_counter()
    pred=read_json(DATA/'predictions_v4.json',{})
    univ=read_json(DATA/'universe.json',{})
    team=read_json(DATA/'team.json',{})
    latest=read_json(DATA/'latest.json',{})
    locked=effective_planning_squad(team,read_json(CONFIG/'locked_squad.json',{}),latest)
    under=read_json(DATA/'understat_tactical_v4.json',{})
    prices=read_json(DATA/'prices.json',{})
    cands=build_candidates(pred,univ)
    inter=build_tactical_interactions(pred,univ,under)
    reconciled,_=reconcile_owned_costs(cands,locked)
    owned={int(r['element']) for r in locked.get('players') or []}
    external,_=facade.safe_prune_incoming_players(reconciled,owned,interactions=inter,prices=prices,predictions=pred,universe=univ)
    imap=facade._core._interaction_rows(inter); pmap=facade._core._price_rows(prices)
    predmap={int(r['element']):r for r in pred.get('players') or [] if r.get('element') is not None}
    umap={int(r['element']):r for r in univ.get('players') or [] if r.get('element') is not None}
    mids=[p for p in external if p.position=='MID']
    by_team=defaultdict(list)
    for p in mids:
        dims=facade._dominance_dimensions(p,interaction_map=imap,price_map=pmap,prediction_map=predmap,universe_map=umap)
        by_team[p.team_id].append(player_state(p,dims))
    prep=perf_counter()
    pair={}
    pair_raw=0
    teams=sorted(by_team)
    # exact team signatures of size 2
    for i,a in enumerate(teams):
        # same-team two
        f=[]
        for x,y in combinations(by_team[a],2):
            pair_raw+=1; insert(f,merge(x,y))
        if f: pair[((a,2),)] = f
        for b in teams[i+1:]:
            f=[]
            for x in by_team[a]:
                for y in by_team[b]:
                    pair_raw+=1; insert(f,merge(x,y))
            if f: pair[((a,1),(b,1))] = f
    tpair=perf_counter()
    triple={}; triple_raw=0
    # same-team 3
    for a in teams:
        f=[]
        for x,y,z in combinations(by_team[a],3):
            triple_raw+=1; insert(f,merge(merge(x,y),z))
        if f: triple[((a,3),)] = f
    # 2+1 signatures, extend exact same-team pair only
    for a in teams:
        pf=pair.get(((a,2),),[])
        if not pf: continue
        for b in teams:
            if b==a: continue
            sig=tuple(sorted(((a,2),(b,1))))
            f=triple.setdefault(sig,[])
            for ps in pf:
                for y in by_team[b]:
                    triple_raw+=1; insert(f,merge(ps,y))
    # three distinct, extend exact pair A,B with C>B to generate once
    for ia,a in enumerate(teams):
        for ib in range(ia+1,len(teams)):
            b=teams[ib]
            pf=pair.get(((a,1),(b,1)),[])
            for c in teams[ib+1:]:
                f=[]
                for ps in pf:
                    for z in by_team[c]:
                        triple_raw+=1; insert(f,merge(ps,z))
                if f: triple[((a,1),(b,1),(c,1))]=f
    t3=perf_counter()
    print({
        'mids':len(mids),'teams':len(teams),'team_sizes':{str(k):len(v) for k,v in sorted(by_team.items())},
        'prep_s':round(prep-t0,3),'pair_s':round(tpair-prep,3),'triple_s':round(t3-tpair,3),'total_s':round(t3-t0,3),
        'pair_raw_extensions':pair_raw,'pair_frontier_states':sum(len(v) for v in pair.values()),'pair_keys':len(pair),
        'triple_raw_extensions':triple_raw,'triple_frontier_states':sum(len(v) for v in triple.values()),'triple_keys':len(triple),
        'triple_max_frontier':max((len(v) for v in triple.values()),default=0),
        'triple_avg_frontier':round(sum(len(v) for v in triple.values())/max(1,len(triple)),2),
    },flush=True)

if __name__=='__main__': main()
