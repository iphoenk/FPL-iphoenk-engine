from copy import deepcopy

from src.v5.evaluation.owned_challenger_comparator import compare
from src.v5.evaluation.owned_challenger_context import enrich_with_decision_context


def _gw(mean=4.0,std=1.0,fixtures=True):
    return [{"gw":2+i,"mean":mean,"std":std,"fixtures":[{"home":i%2==0,"opponent":10+i,"mean":mean,"std":std}] if fixtures else []} for i in range(5)]

def _p(eid,pos,cost,mean,team=1,start=.9,dnp=.05,status="a",std=1.0,fixtures=True):
    return {"element":eid,"name":f"P{eid}","position":pos,"team_id":team,"now_cost":cost,"status":status,"xpts_by_gw":_gw(mean,std,fixtures),"xpts_5":mean*5,"xmins":{"expected_minutes":82,"start_probability":start,"dnp_probability":dnp},"role":{},"tactical_matchup":{"status":"READY"}}

def _base():
    players=[_p(1,"MID",70,3.5,1),_p(2,"MID",65,3.8,2),_p(3,"DEF",50,3.0,3),_p(101,"MID",72,4.4,4),_p(102,"MID",60,4.0,5),_p(103,"DEF",48,3.6,6)]
    prediction={"planning_gw":2,"players":players}
    team={"owned_ids":[1,2,3],"finance":{"bank":10,"players":[{"element":1,"sell_cost":69},{"element":2,"sell_cost":65},{"element":3,"sell_cost":50}]}}
    watch={"status":"READY","positions":{"MID":[{"element":101,"position":"MID"},{"element":102,"position":"MID"}],"DEF":[{"element":103,"position":"DEF"}],"FWD":[],"GK":[]}}
    workload={str(x):{"status":"VERIFIED","europe":False,"domestic_cup":False,"international":False} for x in [1,2,3,101,102,103]}
    return prediction,team,watch,workload

def _row(out,cid,oid=None):
    return next(r for r in out["pairs"] if r["challenger"]["element"]==cid and (oid is None or r["owned"]["element"]==oid))


def test_upgrade_and_downgrade_price_structures_are_compared_when_affordable():
    prediction,team,watch,workload=_base(); out=compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload,transfer_state={"wildcard_active":True})
    assert _row(out,101,1)["challenger"]["now_cost"] > _row(out,101,1)["owned"]["sell_cost"]
    assert _row(out,102,1)["challenger"]["now_cost"] < _row(out,102,1)["owned"]["sell_cost"]


def test_normal_free_transfer_state_is_preserved_without_fabricated_hit():
    prediction,team,watch,workload=_base(); out=compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload,transfer_state={"free_transfers":1,"authoritative":True})
    row=_row(out,101,1); assert row["transfer_context"]["free_transfers"]==1; assert row["transfer_context"]["authoritative_transfer_state"] is True


def test_europe_domestic_cup_and_international_workload_are_evidence_not_guesses():
    prediction,team,watch,workload=_base(); workload["101"]={"status":"VERIFIED","europe":True,"domestic_cup":True,"international":True,"actual_minutes":120}
    out=compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload); row=_row(out,101,1)
    assert row["challenger"]["workload"]["europe"] is True
    assert row["challenger"]["workload"]["domestic_cup"] is True
    assert row["challenger"]["workload"]["international"] is True
    assert row["challenger"]["workload"]["actual_minutes"]==120


def test_missing_external_consensus_is_neutral_not_fabricated():
    prediction,team,watch,workload=_base(); row=_row(compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload),101,1)
    assert row["external_consensus"]["state"]=="NEUTRAL"


def test_tbd_fixture_is_exposed_as_missing_fixture_detail_not_invented_opponent():
    prediction,team,watch,workload=_base(); c=next(p for p in prediction["players"] if p["element"]==101); c["xpts_by_gw"]=_gw(4.4,fixtures=False)
    row=_row(compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload),101,1)
    assert row["horizons"]["1"]["challenger_fixtures"][0]["opponent"] is None


def test_injury_and_suspension_block_challenger_eligibility():
    for status in ("i","s"):
        prediction,team,watch,workload=_base(); next(p for p in prediction["players"] if p["element"]==101)["status"]=status
        out=compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload)
        assert not any(r["challenger"]["element"]==101 for r in out["pairs"])


def test_one_haul_or_weak_process_never_generates_buy_sell_action():
    prediction,team,watch,workload=_base(); emerging=_p(105,"MID",70,3.6,8); prediction["players"].append(emerging); workload["105"]={"status":"VERIFIED"}
    out=compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload,emerging_candidates=[{"element":105,"triggered":True,"trigger":"BRACE","underlying_quality":"WEAK"}])
    row=_row(out,105); assert row["classification"] not in {"BUY","SELL","STRONG_TRANSFER"}


def test_xmins_deterioration_can_remove_candidate_while_improvement_restores_it():
    prediction,team,watch,workload=_base(); c=next(p for p in prediction["players"] if p["element"]==101); c["xmins"].update({"start_probability":.2,"dnp_probability":.6})
    assert not any(r["challenger"]["element"]==101 for r in compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload)["pairs"])
    c["xmins"].update({"start_probability":.9,"dnp_probability":.05}); assert any(r["challenger"]["element"]==101 for r in compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload)["pairs"])


def test_canonical_club_limit_or_other_illegality_is_consumed_not_recomputed():
    base={"pairs":[{"owned":{"element":1},"challenger":{"element":101,"lane":"GOVERNED_WATCHLIST"},"horizons":{"5":{"raw_gain":3}},"classification":"REVIEW","performance_signal":"STRONG","evidence":{},"reasons":[]}],"top_comparisons":[]}
    decision={"hold":{"score":{"robust_score":40}},"packages":[{"id":"x","changes":1,"outs":[{"element":1}],"ins":[{"element":101}],"legal":False,"score":{"robust_score":45}}]}
    row=enrich_with_decision_context(base,decision)["pairs"][0]; assert row["canonical_package_context"]["legal"] is False; assert row["canonical_package_context"]["authority"]=="DECISION_PACKAGE_OPTIMIZER"


def test_early_season_high_uncertainty_reduces_signal_to_noise():
    prediction,team,watch,workload=_base(); c=next(p for p in prediction["players"] if p["element"]==101); c["xpts_by_gw"]=_gw(4.4,std=5.0)
    row=_row(compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload),101,1)
    assert row["horizons"]["5"]["signal_to_noise"] < 1.0
    assert row["confidence"] != "HIGH"


def test_watchlist_demotion_is_advisory_only():
    base={"pairs":[{"owned":{"element":1},"challenger":{"element":101,"lane":"GOVERNED_WATCHLIST"},"horizons":{"5":{"raw_gain":-1}},"classification":"HOLD_OWNED","performance_signal":"NOISE","evidence":{},"reasons":[]}],"top_comparisons":[]}
    row=enrich_with_decision_context(base,{})["pairs"][0]; assert row["watchlist_advisory"]["action"]=="REVIEW_DEMOTION"; assert row["watchlist_mutation"] is False


def test_multiple_challengers_can_map_to_one_owned_and_one_challenger_to_multiple_owned():
    prediction,team,watch,workload=_base(); out=compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload)
    mids=[r for r in out["pairs"] if r["challenger"]["element"] in {101,102}]
    assert {r["challenger"]["element"] for r in mids}=={101,102}
    targets=[r["owned"]["element"] for r in out["pairs"] if r["challenger"]["element"]==101]
    assert len(set(targets))>=2


def test_cross_engine_divergence_remains_advisory():
    prediction,team,watch,workload=_base(); row=_row(compare(prediction=prediction,team=team,watchlist=watch,workload_context=workload,external_consensus={"101":{"state":"REVIEW_DIVERGENCE"}}),101,1)
    assert row["external_consensus"]=={"state":"REVIEW_DIVERGENCE","governance":"ADVISORY_ONLY_NO_MAJORITY_VOTE"}
