from __future__ import annotations

import json
from src.utils import DATA, CONFIG, atomic_json, read_json

OUTFILE = DATA / "lineup_decision_v4.json"
MANUAL_FILE = CONFIG / "manual_lineup.json"
LEGAL_FORMATIONS = [(d,m,10-d-m) for d in range(3,6) for m in range(2,6) if 1 <= 10-d-m <= 3]


def _f(v, default=0.0):
    try: return float(v if v is not None else default)
    except Exception: return float(default)


def _fixture_row(pred, idx=0):
    fx=pred.get("fixtures") or []
    return fx[idx] if idx < len(fx) and isinstance(fx[idx],dict) else {}


def _player_row(pred, universe_row, idx=0):
    fx=_fixture_row(pred,idx); xm=fx.get("xmins") or {}; xpts=_f(fx.get("xpts")); lower=_f(fx.get("lower80"),xpts); upper=_f(fx.get("upper80"),xpts)
    start=_f(xm.get("start_probability"),1.0 if _f(xm.get("expected_minutes"),90)>=60 else .5)
    bench=_f(xm.get("bench_probability"),max(0,1-start)); dnp=_f(xm.get("dnp_probability"),max(0,1-start-bench)); avail=max(0,min(1,1-dnp))
    ceiling=max(xpts,upper); floor=min(xpts,lower)
    captain_score=xpts + .12*(ceiling-xpts) - 1.65*dnp - .45*max(0,.78-start)
    vice_score=xpts + .05*(ceiling-xpts) - 1.95*dnp - .55*max(0,.84-start)
    bench_score=xpts*(.70+.30*avail)+.08*start
    return {"element":int(pred.get("element")),"name":universe_row.get("name") or pred.get("name") or str(pred.get("element")),"position":universe_row.get("position") or pred.get("position"),"team":universe_row.get("team") or pred.get("team"),"xpts":round(xpts,4),"lower80":round(lower,4),"upper80":round(upper,4),"start_probability":round(start,4),"bench_probability":round(bench,4),"dnp_probability":round(dnp,4),"availability":round(avail,4),"captain_score":round(captain_score,4),"vice_score":round(vice_score,4),"bench_score":round(bench_score,4),"interval_width":round(max(0,upper-lower),4)}


def _formation(rows):
    c={p:sum(r["position"]==p for r in rows) for p in ("DEF","MID","FWD")}
    form=f"{c['DEF']}-{c['MID']}-{c['FWD']}"
    return form if (c['DEF'],c['MID'],c['FWD']) in LEGAL_FORMATIONS else None


def _legal_xi(rows):
    by={p:[r for r in rows if r["position"]==p] for p in ("GK","DEF","MID","FWD")}
    if not all(by[p] for p in by): raise RuntimeError("locked squad missing position group")
    gk=max(by["GK"],key=lambda r:(r["xpts"],r["start_probability"],-r["dnp_probability"]))
    best=None
    for d,m,f in LEGAL_FORMATIONS:
        if len(by["DEF"])<d or len(by["MID"])<m or len(by["FWD"])<f: continue
        chosen=[gk]+sorted(by["DEF"],key=lambda r:(r["xpts"],r["start_probability"]),reverse=True)[:d]+sorted(by["MID"],key=lambda r:(r["xpts"],r["start_probability"]),reverse=True)[:m]+sorted(by["FWD"],key=lambda r:(r["xpts"],r["start_probability"]),reverse=True)[:f]
        score=sum(r["xpts"] for r in chosen); risk=sum(r["dnp_probability"] for r in chosen); width=sum(r["interval_width"] for r in chosen)
        key=(score-.10*risk-.005*width,score,-risk)
        if best is None or key>best[0]: best=(key,chosen,f"{d}-{m}-{f}",score)
    if best is None: raise RuntimeError("no legal XI")
    return best[1],best[2],best[3]


def _bench(rows,xi_ids):
    bench=[r for r in rows if r["element"] not in xi_ids]; gks=[r for r in bench if r["position"]=="GK"]; out=[r for r in bench if r["position"]!="GK"]
    if len(gks)!=1 or len(out)!=3: raise RuntimeError("bench structure invalid")
    out.sort(key=lambda r:(r["bench_score"],r["xpts"],r["start_probability"]),reverse=True)
    return gks[0],out


def _captain_pair(xi):
    pool=[r for r in xi if r["position"]!="GK"] or xi
    safe=[r for r in pool if r["dnp_probability"]<.30 and r["start_probability"]>=.70] or pool
    captain=max(safe,key=lambda r:(r["captain_score"],r["xpts"],r["upper80"]))
    vice_pool=[r for r in pool if r["element"]!=captain["element"]]
    vice_safe=[r for r in vice_pool if r["dnp_probability"]<.25 and r["start_probability"]>=.75] or vice_pool
    vice=max(vice_safe,key=lambda r:(r["vice_score"],r["xpts"],r["start_probability"]))
    return captain,vice


def _manual_candidate(rows, manual):
    ids=set(int(x) for x in manual.get("starting_xi",[]))
    if len(ids)!=11: return None
    xi=[r for r in rows if r["element"] in ids]
    if len(xi)!=11 or sum(r["position"]=="GK" for r in xi)!=1 or not _formation(xi): return None
    return xi,_formation(xi),sum(r["xpts"] for r in xi)


def _robustness_decision(raw_xi,raw_score,manual_xi,manual_score):
    rid={r["element"] for r in raw_xi}; mid={r["element"] for r in manual_xi}; changed=max(1,len(rid^mid)//2)
    gain=raw_score-manual_score
    affected=[r for r in raw_xi+manual_xi if r["element"] in (rid^mid)]
    mean_width=sum(r["interval_width"] for r in affected)/max(1,len(affected))
    threshold=.50*changed + .055*mean_width
    return {"changed_slots":changed,"raw_gain":round(gain,3),"required_margin":round(threshold,3),"decision":"CHANGE_RECOMMENDED" if gain>=threshold else "HOLD_MANUAL_DRAFT","robust_enough":gain>=threshold}


def optimize_lineup(predictions,universe,locked,gw_index=0,manual=None):
    pmap={int(p.get("element")):p for p in predictions.get("players",[]) if p.get("element") is not None}; umap={int(p.get("element")):p for p in universe.get("players",[]) if p.get("element") is not None}
    locked_ids=[int(p["element"]) for p in locked.get("players",[])]
    if len(locked_ids)!=15: raise RuntimeError("locked squad must contain 15 players")
    missing=[e for e in locked_ids if e not in pmap or e not in umap]
    if missing: raise RuntimeError(f"locked players missing prediction/universe data: {missing}")
    rows=[_player_row(pmap[e],umap[e],gw_index) for e in locked_ids]
    raw_xi,raw_form,raw_score=_legal_xi(rows); chosen_xi=raw_xi; formation=raw_form; xi_score=raw_score; governance={"manual_draft_available":False,"decision":"OPTIMIZER_ONLY"}; manual_snapshot=None
    if manual:
        mc=_manual_candidate(rows,manual)
        if mc:
            governance={"manual_draft_available":True,**_robustness_decision(raw_xi,raw_score,mc[0],mc[2])}
            manual_snapshot={"formation":mc[1],"xi_xpts":round(mc[2],2),"starting_ids":[r["element"] for r in mc[0]],"captain":manual.get("captain"),"vice_captain":manual.get("vice_captain"),"status":manual.get("status")}
            if governance["decision"]=="HOLD_MANUAL_DRAFT": chosen_xi,formation,xi_score=mc
    xi_ids={r["element"] for r in chosen_xi}; bench_gk,bench_out=_bench(rows,xi_ids); opt_c,opt_v=_captain_pair(chosen_xi)
    captain,opt_vice=opt_c,opt_v; captain_decision="OPTIMIZER"
    if manual_snapshot and governance["decision"]=="HOLD_MANUAL_DRAFT":
        mm={r["element"]:r for r in chosen_xi}; mc=mm.get(int(manual.get("captain",-1))); mv=mm.get(int(manual.get("vice_captain",-1)))
        if mc and mv and mc["dnp_probability"]<.30 and mc["start_probability"]>=.70:
            cap_gain=opt_c["captain_score"]-mc["captain_score"]
            if cap_gain<.40: captain,opt_vice,captain_decision=mc,mv,"HOLD_MANUAL_CAPTAIN"
    chip="WILDCARD" if bool(locked.get("wildcard_active")) else "NONE"
    return {"schema_version":452,"engine":"v4.5.2-lineup-robust-governance","gw_offset":gw_index+1,"formation":formation,"xi_xpts":round(xi_score,2),"starting_xi":sorted(chosen_xi,key=lambda r:(0 if r["position"]=="GK" else 1 if r["position"]=="DEF" else 2 if r["position"]=="MID" else 3,-r["xpts"])),"captain":captain,"vice_captain":opt_vice,"bench":{"gk":bench_gk,"order":[{"slot":i+1,**r} for i,r in enumerate(bench_out)]},"optimizer_proposal":{"formation":raw_form,"xi_xpts":round(raw_score,2),"starting_ids":[r["element"] for r in raw_xi],"captain":opt_c["element"],"vice_captain":opt_v["element"]},"manual_draft":manual_snapshot,"governance":governance|{"captain_decision":captain_decision},"chip_context":{"active_chip":chip,"other_chip_recommendation":"NONE" if chip=="WILDCARD" else "UNASSESSED","single_chip_rule_respected":True},"guardrails":{"legal_formation":True,"one_gk_in_xi":True,"captain_in_xi":True,"vice_in_xi":True,"bench_has_one_gk_three_outfield":True,"captain_risk_adjusted":True,"captain_safe_pool_preferred":True,"manual_draft_not_overwritten_without_margin":True,"prediction_interval_robustness":True}}


def run():
    out=optimize_lineup(read_json(DATA/"predictions_v4.json",{}),read_json(DATA/"universe.json",{}),read_json(CONFIG/"locked_squad.json",{}),manual=read_json(MANUAL_FILE,{}))
    atomic_json(OUTFILE,out); print(json.dumps(out,ensure_ascii=False,indent=2)); return out

if __name__=="__main__": run()
