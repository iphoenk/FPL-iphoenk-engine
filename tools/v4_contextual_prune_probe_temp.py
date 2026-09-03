from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from statistics import mean

from src.engines import v4_full_universe_package_search as facade
from src.engines.v4_decision_pipeline import effective_planning_squad
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_wc_optimizer import POSITION_COUNTS, build_candidates, reconcile_owned_costs
from src.utils import CONFIG, DATA, read_json


def no_worse(ld, rd, eps=1e-6):
    return (
        all(ld[k] <= rd[k] + eps for k in facade._MINIMIZE)
        and all(ld[k] + eps >= rd[k] for k in facade._MAXIMIZE)
        and (
            any(ld[k] + eps < rd[k] for k in facade._MINIMIZE)
            or any(ld[k] > rd[k] + eps for k in facade._MAXIMIZE)
        )
    )

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
by_id={p.element:p for p in reconciled}
current=tuple(by_id[e] for e in sorted(owned))
external,_=facade.safe_prune_incoming_players(reconciled,owned,interactions=inter,prices=prices,predictions=pred,universe=univ)
interaction_map=facade._core._interaction_rows(inter)
price_map=facade._core._price_rows(prices)
pred_map={int(r['element']):r for r in pred.get('players') or [] if r.get('element') is not None}
univ_map={int(r['element']):r for r in univ.get('players') or [] if r.get('element') is not None}
dims={p.element:facade._dominance_dimensions(p,interaction_map=interaction_map,price_map=price_map,prediction_map=pred_map,universe_map=univ_map) for p in external}
pools=defaultdict(list)
for p in external:pools[p.position].append(p)

summary={}
for k in (1,2,3):
    samples=defaultdict(list)
    removed=defaultdict(list)
    for outs in combinations(current,k):
        keep=tuple(p for p in current if p not in outs)
        keep_clubs=Counter(p.team_id for p in keep)
        need=Counter(p.position for p in outs)
        for pos,count in need.items():
            rows=pools[pos]
            kept=[]
            for right in rows:
                dominated=False
                for left in rows:
                    if left.element==right.element:
                        continue
                    # Replacement must be legal for every possible completion of this k-package.
                    # At most k-1 other incoming players can share left.team_id.
                    if left.team_id != right.team_id and keep_clubs.get(left.team_id,0) + k > 3:
                        continue
                    if no_worse(dims[left.element],dims[right.element]):
                        dominated=True
                        break
                if not dominated:
                    kept.append(right)
            samples[pos].append(len(kept))
            removed[pos].append(len(rows)-len(kept))
    summary[str(k)]={pos:{'min':min(vals),'avg':round(mean(vals),1),'max':max(vals),'avg_removed':round(mean(removed[pos]),1)} for pos,vals in samples.items()}
print({'base_pools':{p:len(v) for p,v in pools.items()},'contextual':summary},flush=True)
