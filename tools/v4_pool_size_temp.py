from src.engines import v4_full_universe_package_search as facade
from src.engines.v4_decision_pipeline import effective_planning_squad
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_wc_optimizer import POSITION_COUNTS, build_candidates, reconcile_owned_costs
from src.utils import CONFIG, DATA, read_json

predictions=read_json(DATA/'predictions_v4.json',{})
universe=read_json(DATA/'universe.json',{})
team=read_json(DATA/'team.json',{})
latest=read_json(DATA/'latest.json',{})
locked=effective_planning_squad(team,read_json(CONFIG/'locked_squad.json',{}),latest)
understat=read_json(DATA/'understat_tactical_v4.json',{})
prices=read_json(DATA/'prices.json',{})
candidates=build_candidates(predictions,universe)
interactions=build_tactical_interactions(predictions,universe,understat)
reconciled,_=reconcile_owned_costs(candidates,locked)
owned={int(r['element']) for r in locked.get('players') or []}
external,proofs=facade.safe_prune_incoming_players(reconciled,owned,interactions=interactions,prices=prices,predictions=predictions,universe=universe)
pools={p:[] for p in POSITION_COUNTS}
for row in external:pools[row.position].append(row)
print({'candidates':len(candidates),'external_before':len(reconciled)-len(owned),'safe_pruned':len(proofs),'external_after':len(external),'pools':{p:len(v) for p,v in pools.items()}},flush=True)
