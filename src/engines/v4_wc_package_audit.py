from __future__ import annotations
import json
from collections import Counter
from itertools import combinations
from src.utils import DATA, CONFIG, atomic_json, read_json
from src.engines.v4_wc_optimizer import BUDGET_TENTHS, MAX_PER_CLUB, POSITION_COUNTS, build_candidates, squad_metrics, validate_squad
OUTFILE=DATA/'wc_package_audit_v4.json'

def payload(p): return {'element':p.element,'name':p.name,'position':p.position,'team':p.team,'team_id':p.team_id,'cost':p.cost,'xpts_3':round(p.x3,2),'xpts_5':round(p.x5,2),'xpts_10':round(p.x10,2),'xpts_15':round(p.x15,2),'uncertainty':round(p.uncertainty,3),'objective':round(p.objective,4)}
def package_class(dxi,du,k):
    xr={1:1.5,2:2.5,3:3.5,4:4.5}[k]; ur={1:1.8,2:3.0,3:4.2,4:5.4}[k]
    if dxi>=xr and du>=ur:return 'MATERIAL_UPGRADE'
    if dxi>=xr*.55 and du>=ur*.55:return 'OPTIONAL_IMPROVEMENT'
    return 'KEEP_BASELINE'
def _package_class(delta_x5,delta_obj,replacements): return package_class(delta_x5,delta_obj,replacements)
def frontier(cands,ids,n=7):
    out=[]
    for pos in POSITION_COUNTS:
        rows=[p for p in cands if p.position==pos and p.element not in ids]
        rows.sort(key=lambda p:(p.objective-.12*p.uncertainty,p.x5,-p.cost),reverse=True); out+=rows[:n]
    return out

def _bounded_ins_states(cur,outids,need,bp,budget,beam=28):
    keep=[p for p in cur if p.element not in outids]; base_cost=sum(p.cost for p in keep); base_clubs=Counter(p.team_id for p in keep)
    slots=[]
    for pos,n in need.items(): slots += [pos]*n
    states=[(tuple(),base_cost,base_clubs,0.0)]
    for pos in slots:
        nxt=[]
        for chosen,cost,clubs,score in states:
            used={p.element for p in chosen}
            for p in bp[pos]:
                if p.element in used or cost+p.cost>budget or clubs[p.team_id]>=MAX_PER_CLUB: continue
                cc=clubs.copy(); cc[p.team_id]+=1; nxt.append((chosen+(p,),cost+p.cost,cc,score+p.objective-.12*p.uncertainty))
        nxt.sort(key=lambda s:(s[3],-s[1]),reverse=True); dedup=[]; seen=set()
        for s in nxt:
            key=tuple(sorted(p.element for p in s[0]))
            if key in seen: continue
            seen.add(key); dedup.append(s)
            if len(dedup)>=beam: break
        states=dedup
        if not states: break
    return [s[0] for s in states]

def _candidate_states(cur,outids,need,bp,budget,k,beam_size):
    if k>=3:return _bounded_ins_states(cur,outids,need,bp,budget,beam_size)
    pools=[list(combinations(bp[pos],n)) for pos,n in need.items()]; states=[tuple()]
    for comboset in pools:
        states=[s+c for s in states for c in comboset if len({p.element for p in s+c})==len(s+c)]
    keep=[p for p in cur if p.element not in outids]; keep_cost=sum(p.cost for p in keep); clubs=Counter(p.team_id for p in keep); legal=[]
    for chosen in states:
        if keep_cost+sum(p.cost for p in chosen)>budget: continue
        cc=clubs.copy(); ok=True
        for p in chosen:
            cc[p.team_id]+=1
            if cc[p.team_id]>MAX_PER_CLUB: ok=False; break
        if ok: legal.append((sum(p.objective-.12*p.uncertainty for p in chosen),chosen))
    legal.sort(key=lambda x:x[0],reverse=True); cap=16 if k==1 else 30
    return [x[1] for x in legal[:cap]]

def audit_packages(predictions,universe,locked,max_replacements=4,budget=BUDGET_TENTHS,per_position_frontier=7,top_per_size=8,beam_size=28):
    cands=build_candidates(predictions,universe); by={p.element:p for p in cands}; ids={int(x['element']) for x in locked.get('players',[])}
    missing=ids-set(by)
    if missing:raise RuntimeError(f'baseline players missing from candidate universe: {sorted(missing)}')
    cur=[by[e] for e in ids]; ok,reason=validate_squad(cur,budget)
    if not ok:raise RuntimeError(f'baseline invalid: {reason}')
    fr=frontier(cands,ids,per_position_frontier); bp={pos:[p for p in fr if p.position==pos] for pos in POSITION_COUNTS}; cm=squad_metrics(cur); basecost=cm['cost']; results={}; baseline_unc=sum(p.uncertainty for p in cur); metrics_cache={}
    def metrics(target):
        key=tuple(sorted(p.element for p in target))
        if key not in metrics_cache: metrics_cache[key]=squad_metrics(target)
        return metrics_cache[key]
    for k in range(1,max_replacements+1):
        packs=[]
        for outs in combinations(cur,k):
            outids={p.element for p in outs}; need=Counter(p.position for p in outs)
            if any(len(bp[pos])<n for pos,n in need.items()): continue
            for chosen in _candidate_states(cur,outids,need,bp,budget,k,beam_size):
                if len(chosen)!=k: continue
                target=[p for p in cur if p.element not in outids]+list(chosen); ok,_=validate_squad(target,budget)
                if not ok: continue
                tm=metrics(target); dxi=tm['best_xi_xpts_5']-cm['best_xi_xpts_5']; du=tm['bench_adjusted_utility_5']-cm['bench_adjusted_utility_5']; risk_delta=sum(p.uncertainty for p in target)-baseline_unc; risk_penalty=max(0,risk_delta)*.35+max(0,k-1)*.20; adj_xi=dxi-risk_penalty; adj_util=du-risk_penalty
                packs.append({'replacements':k,'out':[payload(p) for p in sorted(outs,key=lambda x:(x.position,x.name))],'in':[payload(p) for p in sorted(chosen,key=lambda x:(x.position,x.name))],'target_cost':tm['cost'],'target_itb':budget-tm['cost'],'delta_cost':tm['cost']-basecost,'delta_objective':round(tm['objective']-cm['objective'],4),'delta_squad_xpts_3':round(tm['squad_xpts_3']-cm['squad_xpts_3'],2),'delta_squad_xpts_5':round(tm['squad_xpts_5']-cm['squad_xpts_5'],2),'delta_squad_xpts_10':round(tm['squad_xpts_10']-cm['squad_xpts_10'],2),'delta_squad_xpts_15':round(tm['squad_xpts_15']-cm['squad_xpts_15'],2),'delta_best_xi_xpts_5':round(dxi,2),'delta_bench_adjusted_utility_5':round(du,2),'risk_delta':round(risk_delta,3),'risk_penalty':round(risk_penalty,3),'adjusted_best_xi_gain_5':round(adj_xi,2),'adjusted_utility_gain_5':round(adj_util,2),'classification':package_class(adj_xi,adj_util,k)})
        packs.sort(key=lambda r:(r['adjusted_utility_gain_5'],r['adjusted_best_xi_gain_5'],r['delta_objective'],r['target_itb']),reverse=True); results[str(k)]=packs[:top_per_size]
    best={k:(rows[0] if rows else None) for k,rows in results.items()}; mat=[x for x in best.values() if x and x['classification']=='MATERIAL_UPGRADE']; opt=[x for x in best.values() if x and x['classification']=='OPTIONAL_IMPROVEMENT']
    if mat: overall=max(mat,key=lambda x:(x['adjusted_utility_gain_5'],x['adjusted_best_xi_gain_5'])); verdict='MATERIAL_UPGRADE'
    elif opt: overall=max(opt,key=lambda x:(x['adjusted_utility_gain_5'],x['adjusted_best_xi_gain_5'])); verdict='OPTIONAL_IMPROVEMENT'
    else: overall=None; verdict='KEEP_15'
    return {'schema_version':444,'engine':'v4.4.3-wc-package-audit-memoized','wildcard_active':bool(locked.get('wildcard_active')),'baseline':cm|{'itb':budget-basecost},'screened_players':len(cands),'frontier_players':len(fr),'max_replacements':max_replacements,'best_by_replacement_count':best,'packages':results,'overall_verdict':verdict,'recommended_package':overall,'performance':{'metrics_cache_entries':len(metrics_cache),'frontier_per_position':per_position_frontier,'beam_size':beam_size},'guardrails':{'max_per_club':MAX_PER_CLUB,'budget_tenths':budget,'position_counts':POSITION_COUNTS,'larger_packages_require_higher_gain':True,'ranking_metric':'risk-adjusted best-XI plus bench-adjusted 5GW utility','search':'shortlisted k<=2, bounded beam k=3-4, memoized squad metrics','frontier_per_position':per_position_frontier,'beam_size':beam_size,'risk_penalty_enabled':True}}
def run():
    out=audit_packages(read_json(DATA/'predictions_v4.json',{}),read_json(DATA/'universe.json',{}),read_json(CONFIG/'locked_squad.json',{})); atomic_json(OUTFILE,out); print(json.dumps(out,ensure_ascii=False,indent=2)); return out
if __name__=='__main__':run()
