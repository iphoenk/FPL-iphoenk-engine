from __future__ import annotations
import json
from collections import Counter
from itertools import combinations
from src.utils import DATA, CONFIG, atomic_json, read_json
from src.engines.v4_wc_optimizer import BUDGET_TENTHS, MAX_PER_CLUB, POSITION_COUNTS, Candidate, build_candidates, squad_metrics, validate_squad
OUTFILE=DATA/'wc_package_audit_v4.json'

def payload(p): return {'element':p.element,'name':p.name,'position':p.position,'team':p.team,'team_id':p.team_id,'cost':p.cost,'xpts_3':round(p.x3,2),'xpts_5':round(p.x5,2),'xpts_10':round(p.x10,2),'xpts_15':round(p.x15,2),'uncertainty':round(p.uncertainty,3),'objective':round(p.objective,4)}
def package_class(dxi,du,k):
    xr={1:1.5,2:2.5,3:3.5,4:4.5}[k]; ur={1:1.8,2:3.0,3:4.2,4:5.4}[k]
    if dxi>=xr and du>=ur:return 'MATERIAL_UPGRADE'
    if dxi>=xr*.55 and du>=ur*.55:return 'OPTIONAL_IMPROVEMENT'
    return 'KEEP_BASELINE'
def frontier(cands,ids,n=18):
    out=[]
    for pos in POSITION_COUNTS:
        rows=[p for p in cands if p.position==pos and p.element not in ids]; rows.sort(key=lambda p:(p.objective,p.x5,-p.cost),reverse=True); out+=rows[:n]
    return out

def audit_packages(predictions,universe,locked,max_replacements=4,budget=BUDGET_TENTHS,per_position_frontier=18,top_per_size=12):
    cands=build_candidates(predictions,universe); by={p.element:p for p in cands}; ids={int(x['element']) for x in locked.get('players',[])}
    missing=ids-set(by)
    if missing:raise RuntimeError(f'baseline players missing from candidate universe: {sorted(missing)}')
    cur=[by[e] for e in ids]; ok,reason=validate_squad(cur,budget)
    if not ok:raise RuntimeError(f'baseline invalid: {reason}')
    fr=frontier(cands,ids,per_position_frontier); bp={pos:[p for p in fr if p.position==pos] for pos in POSITION_COUNTS}; cm=squad_metrics(cur); basecost=cm['cost']; results={}
    for k in range(1,max_replacements+1):
        packs=[]
        for outs in combinations(cur,k):
            outids={p.element for p in outs}; need=Counter(p.position for p in outs)
            if any(len(bp[pos])<n for pos,n in need.items()):continue
            pools=[(n,bp[pos]) for pos,n in need.items()]
            def rec(i,chosen):
                if i==len(pools):
                    if len({p.element for p in chosen})!=k:return
                    target=[p for p in cur if p.element not in outids]+list(chosen); ok,_=validate_squad(target,budget)
                    if not ok:return
                    tm=squad_metrics(target); dxi=tm['best_xi_xpts_5']-cm['best_xi_xpts_5']; du=tm['bench_adjusted_utility_5']-cm['bench_adjusted_utility_5']
                    packs.append({'replacements':k,'out':[payload(p) for p in sorted(outs,key=lambda x:(x.position,x.name))],'in':[payload(p) for p in sorted(chosen,key=lambda x:(x.position,x.name))],'target_cost':tm['cost'],'target_itb':budget-tm['cost'],'delta_cost':tm['cost']-basecost,'delta_objective':round(tm['objective']-cm['objective'],4),'delta_squad_xpts_3':round(tm['squad_xpts_3']-cm['squad_xpts_3'],2),'delta_squad_xpts_5':round(tm['squad_xpts_5']-cm['squad_xpts_5'],2),'delta_squad_xpts_10':round(tm['squad_xpts_10']-cm['squad_xpts_10'],2),'delta_squad_xpts_15':round(tm['squad_xpts_15']-cm['squad_xpts_15'],2),'delta_best_xi_xpts_5':round(dxi,2),'delta_bench_adjusted_utility_5':round(du,2),'classification':package_class(dxi,du,k)}); return
                n,rows=pools[i]
                for combo in combinations(rows,n):
                    t=chosen+combo
                    if len({p.element for p in t})==len(t):rec(i+1,t)
            rec(0,tuple())
        packs.sort(key=lambda r:(r['delta_bench_adjusted_utility_5'],r['delta_best_xi_xpts_5'],r['delta_objective'],r['target_itb']),reverse=True); results[str(k)]=packs[:top_per_size]
    best={k:(rows[0] if rows else None) for k,rows in results.items()}; mat=[x for x in best.values() if x and x['classification']=='MATERIAL_UPGRADE']; opt=[x for x in best.values() if x and x['classification']=='OPTIONAL_IMPROVEMENT']
    if mat:overall=max(mat,key=lambda x:(x['delta_bench_adjusted_utility_5'],x['delta_best_xi_xpts_5'])); verdict='MATERIAL_UPGRADE'
    elif opt:overall=max(opt,key=lambda x:(x['delta_bench_adjusted_utility_5'],x['delta_best_xi_xpts_5'])); verdict='OPTIONAL_IMPROVEMENT'
    else:overall=None; verdict='KEEP_15'
    return {'schema_version':442,'engine':'v4.4.2-wc-package-audit','wildcard_active':bool(locked.get('wildcard_active')),'baseline':cm|{'itb':budget-basecost},'screened_players':len(cands),'frontier_players':len(fr),'max_replacements':max_replacements,'best_by_replacement_count':best,'packages':results,'overall_verdict':verdict,'recommended_package':overall,'guardrails':{'max_per_club':MAX_PER_CLUB,'budget_tenths':budget,'position_counts':POSITION_COUNTS,'larger_packages_require_higher_gain':True,'ranking_metric':'best-XI plus bench-adjusted 5GW utility'}}
def run():
    out=audit_packages(read_json(DATA/'predictions_v4.json',{}),read_json(DATA/'universe.json',{}),read_json(CONFIG/'locked_squad.json',{})); atomic_json(OUTFILE,out); print(json.dumps(out,ensure_ascii=False,indent=2)); return out
if __name__=='__main__':run()
