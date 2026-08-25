from src.engines.v4_lineup_optimizer import optimize_lineup


def _u(e,name,pos,team_id=1):
    return {"element":e,"name":name,"position":pos,"team_id":team_id,"team":f"T{team_id}","now_cost":50,"status":"a"}

def _p(e,x,start=.95,dnp=.02,upper=None):
    return {"element":e,"fixtures":[{"xpts":x,"lower80":max(0,x-2),"upper80":upper if upper is not None else x+3,"xmins":{"start_probability":start,"bench_probability":max(0,1-start-dnp),"dnp_probability":dnp}}]}


def test_lineup_is_legal_and_bench_ordered():
    universe=[]; preds=[]; locked=[]; e=1
    spec=[("GK",[5,4]),("DEF",[7,6,5,4,3]),("MID",[9,8,7,6,5]),("FWD",[10,8,4])]
    for pos,vals in spec:
        for x in vals:
            universe.append(_u(e,f"P{e}",pos,(e%8)+1)); preds.append(_p(e,x)); locked.append({"element":e}); e+=1
    out=optimize_lineup({"players":preds},{"players":universe},{"players":locked,"wildcard_active":True})
    assert len(out["starting_xi"])==11
    assert out["formation"] in {"3-4-3","3-5-2","4-3-3","4-4-2","4-5-1","5-2-3","5-3-2","5-4-1"}
    assert out["captain"]["element"] in {r["element"] for r in out["starting_xi"]}
    assert out["vice_captain"]["element"] in {r["element"] for r in out["starting_xi"]}
    assert out["captain"]["element"] != out["vice_captain"]["element"]
    assert len(out["bench"]["order"])==3
    assert out["chip_context"]["active_chip"]=="WILDCARD"
    assert out["chip_context"]["other_chip_recommendation"]=="NONE"


def test_captain_penalizes_dnp_risk():
    universe=[]; preds=[]; locked=[]; e=1
    spec=[("GK",[4,3]),("DEF",[5,5,5,4,4]),("MID",[8,7,6,5,4]),("FWD",[9,8,7])]
    for pos,vals in spec:
        for x in vals:
            universe.append(_u(e,f"P{e}",pos,(e%8)+1))
            if pos=="FWD" and x==9: preds.append(_p(e,x,start=.45,dnp=.45,upper=13))
            else: preds.append(_p(e,x,start=.96,dnp=.01,upper=x+2))
            locked.append({"element":e}); e+=1
    out=optimize_lineup({"players":preds},{"players":universe},{"players":locked})
    assert out["captain"]["dnp_probability"] < .45
