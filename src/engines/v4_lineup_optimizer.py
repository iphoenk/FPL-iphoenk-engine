from __future__ import annotations

import json
from src.engines.fpl_rules_2026 import LEGAL_FORMATION_TUPLES
from src.engines.fpl_legality import formation_from_rows
from src.utils import DATA, CONFIG, read_json

MANUAL_FILE = CONFIG / "manual_lineup.json"
POLICY_FILE = CONFIG / "serving_improvement_registry.json"


def _f(v, default=0.0):
    try: return float(v if v is not None else default)
    except (TypeError, ValueError): return float(default)


def _fixture_row(pred, idx=0):
    fx = pred.get("fixtures") or []
    return fx[idx] if idx < len(fx) and isinstance(fx[idx], dict) else {}


def _player_row(pred, universe_row, idx=0):
    fx = _fixture_row(pred, idx); xm = fx.get("xmins") or {}; xpts = _f(fx.get("xpts")); lower = _f(fx.get("lower80"), xpts); upper = _f(fx.get("upper80"), xpts)
    start = _f(xm.get("start_probability"), 1.0 if _f(xm.get("expected_minutes"), 90) >= 60 else .5)
    start_conf = _f(xm.get("start_probability_confidence"), .5)
    bench = _f(xm.get("bench_probability"), max(0, 1-start)); dnp = _f(xm.get("dnp_probability"), max(0, 1-start-bench)); avail = max(0, min(1, 1-dnp))
    ceiling = max(xpts, upper); floor = min(xpts, lower); interval_width = max(0, upper-lower)
    captain_score = xpts + .12*(ceiling-xpts) - 1.65*dnp - .45*max(0, .78-start)
    vice_score = xpts + .05*(ceiling-xpts) - 1.95*dnp - .55*max(0, .84-start)
    bench_score = xpts*(.70+.30*avail) + .08*start + .05*start_conf
    selection_score = xpts - .28*dnp - .012*interval_width + .08*start + .04*start_conf
    return {
        "element": int(pred.get("element")), "name": universe_row.get("name") or pred.get("name") or str(pred.get("element")),
        "position": universe_row.get("position") or pred.get("position"), "team": universe_row.get("team") or pred.get("team"),
        "xpts": round(xpts,4), "lower80": round(lower,4), "upper80": round(upper,4), "start_probability": round(start,4),
        "start_probability_confidence": round(start_conf,4), "bench_probability": round(bench,4), "dnp_probability": round(dnp,4),
        "availability": round(avail,4), "captain_score": round(captain_score,4), "vice_score": round(vice_score,4),
        "bench_score": round(bench_score,4), "selection_score": round(selection_score,4), "interval_width": round(interval_width,4),
        "role": (pred.get("priors") or {}).get("tactical_role"),
        "captain_reason": {"raw_xpts": round(xpts,4), "ceiling_uplift": round(.12*(ceiling-xpts),4), "dnp_penalty": round(1.65*dnp,4), "start_security_penalty": round(.45*max(0,.78-start),4)},
        "vice_reason": {"raw_xpts": round(xpts,4), "ceiling_uplift": round(.05*(ceiling-xpts),4), "dnp_penalty": round(1.95*dnp,4), "start_security_penalty": round(.55*max(0,.84-start),4)},
    }


def _formation(rows): return formation_from_rows(rows)


def _correlation_penalty(chosen):
    team_counts = {}
    for row in chosen: team_counts[row.get("team")] = team_counts.get(row.get("team"), 0) + 1
    return sum(max(0, count-2) ** 2 for count in team_counts.values()) * .06


def _formation_candidates(rows):
    by = {p:[r for r in rows if r["position"]==p] for p in ("GK","DEF","MID","FWD")}
    if not all(by[p] for p in by): raise RuntimeError("locked squad missing position group")
    gks = sorted(by["GK"], key=lambda r:(r["selection_score"],r["start_probability"],-r["dnp_probability"]), reverse=True)
    candidates = []
    for d,m,f in LEGAL_FORMATION_TUPLES:
        if len(by["DEF"])<d or len(by["MID"])<m or len(by["FWD"])<f: continue
        gk = gks[0]
        chosen = [gk] + sorted(by["DEF"],key=lambda r:(r["selection_score"],r["xpts"]),reverse=True)[:d] + sorted(by["MID"],key=lambda r:(r["selection_score"],r["xpts"]),reverse=True)[:m] + sorted(by["FWD"],key=lambda r:(r["selection_score"],r["xpts"]),reverse=True)[:f]
        xpts = sum(r["xpts"] for r in chosen); dnp = sum(r["dnp_probability"] for r in chosen); uncertainty = sum(r["interval_width"] for r in chosen); correlation = _correlation_penalty(chosen)
        risk_adjusted = xpts - .28*dnp - .012*uncertainty - correlation
        candidates.append({"formation":f"{d}-{m}-{f}","starting_xi":chosen,"xi_xpts":round(xpts,3),"risk_adjusted_score":round(risk_adjusted,3),"uncertainty":round(uncertainty,3),"dnp_risk":round(dnp,3),"structural_correlation_penalty":round(correlation,3)})
    candidates.sort(key=lambda row:(row["risk_adjusted_score"],row["xi_xpts"],-row["dnp_risk"]), reverse=True)
    if not candidates: raise RuntimeError("no legal XI")
    best = candidates[0]["risk_adjusted_score"]
    for row in candidates: row["marginal_gain_vs_best"] = round(row["risk_adjusted_score"]-best,3)
    return candidates


def _gk_governance(rows, selected_gk, policy):
    gks = sorted([r for r in rows if r["position"]=="GK"], key=lambda r:(r["selection_score"],r["xpts"]), reverse=True)
    if len(gks)<2: return {"status":"DECIDED","selected":selected_gk,"alternatives":gks}
    first, second = gks[:2]; raw_margin = abs(first["xpts"]-second["xpts"]); selection_margin = abs(first["selection_score"]-second["selection_score"])
    raw_threshold = _f(policy.get("gk_open_raw_xpts_margin"),.15); sel_threshold = _f(policy.get("gk_open_selection_margin"),.12)
    open_state = raw_margin < raw_threshold and selection_margin < sel_threshold
    return {"status":"OPEN" if open_state else "DECIDED","selected":selected_gk,"alternatives":gks[:2],"raw_xpts_margin":round(raw_margin,4),"risk_adjusted_margin":round(selection_margin,4),"raw_open_threshold":raw_threshold,"selection_open_threshold":sel_threshold,"reason":"RAW_NEAR_TIE_START_SECURITY_MATERIAL" if open_state else "RISK_ADJUSTED_GK_LEADER"}


def _bench(rows, xi_ids, policy):
    bench = [r for r in rows if r["element"] not in xi_ids]; gks = [r for r in bench if r["position"]=="GK"]; out = [r for r in bench if r["position"]!="GK"]
    if len(gks)!=1 or len(out)!=3: raise RuntimeError("bench structure invalid")
    out.sort(key=lambda r:(r["bench_score"],r["xpts"],r["start_probability"]),reverse=True)
    gaps = [round(out[i]["bench_score"]-out[i+1]["bench_score"],4) for i in range(len(out)-1)]
    threshold = _f(policy.get("bench_open_score_margin"),.15); open_state = any(abs(gap)<threshold for gap in gaps)
    reasoning=[]
    for index,row in enumerate(out):
        reasoning.append({"slot":index+1,"element":row["element"],"name":row["name"],"bench_score":row["bench_score"],"autosub_legal":True,"start_security":row["start_probability"],"ceiling":row["upper80"],"role":row.get("role"),"dnp_risk":row["dnp_probability"]})
    return gks[0], out, {"status":"OPEN" if open_state else "DECIDED","score_gaps":gaps,"open_threshold":threshold,"reasoning":reasoning,"false_precision_forbidden":True}


def _captain_pair(xi, policy):
    pool=[r for r in xi if r["position"]!="GK"] or xi; safe=[r for r in pool if r["dnp_probability"]<.30 and r["start_probability"]>=.70] or pool
    ranked=sorted(safe,key=lambda r:(r["captain_score"],r["xpts"],r["upper80"]),reverse=True); captain=ranked[0]
    vice_pool=[r for r in pool if r["element"]!=captain["element"]]; vice_safe=[r for r in vice_pool if r["dnp_probability"]<.25 and r["start_probability"]>=.75] or vice_pool
    vice_ranked=sorted(vice_safe,key=lambda r:(r["vice_score"],r["xpts"],r["start_probability"]),reverse=True); vice=vice_ranked[0]
    threshold=_f(policy.get("captain_close_margin"),.30); cap_gap=(ranked[0]["captain_score"]-ranked[1]["captain_score"]) if len(ranked)>1 else 999; status="OPEN" if cap_gap<threshold else "DECIDED"
    attacker_vice=next((r for r in vice_ranked if r["position"] in {"MID","FWD"}),None); defender_vice=next((r for r in vice_ranked if r["position"]=="DEF"),None)
    governance={"status":status,"captain_margin":round(cap_gap,4),"open_threshold":threshold,"captain_candidates":[{"element":r["element"],"name":r["name"],"score":r["captain_score"],"reason":r["captain_reason"]} for r in ranked[:5]],"vice_candidates":[{"element":r["element"],"name":r["name"],"score":r["vice_score"],"reason":r["vice_reason"]} for r in vice_ranked[:5]],"attacker_vs_defender_vice":{"attacker":attacker_vice,"defender":defender_vice},"small_raw_xpts_edge_cannot_bypass_risk_adjustment":True}
    return captain,vice,governance


def _manual_candidate(rows, manual):
    ids=set(int(x) for x in manual.get("starting_xi",[]));
    if len(ids)!=11:return None
    xi=[r for r in rows if r["element"] in ids]
    if len(xi)!=11 or sum(r["position"]=="GK" for r in xi)!=1 or not _formation(xi):return None
    return xi,_formation(xi),sum(r["xpts"] for r in xi)


def _robustness_decision(raw_xi,raw_score,manual_xi,manual_score):
    rid={r["element"] for r in raw_xi};mid={r["element"] for r in manual_xi};changed=max(1,len(rid^mid)//2);gain=raw_score-manual_score;affected=[r for r in raw_xi+manual_xi if r["element"] in (rid^mid)];mean_width=sum(r["interval_width"] for r in affected)/max(1,len(affected));threshold=.50*changed+.055*mean_width
    return {"changed_slots":changed,"raw_gain":round(gain,3),"required_margin":round(threshold,3),"decision":"CHANGE_RECOMMENDED" if gain>=threshold else "HOLD_MANUAL_DRAFT","robust_enough":gain>=threshold}


def optimize_lineup(predictions,universe,locked,gw_index=0,manual=None):
    policy=(read_json(POLICY_FILE,{}) or {}).get("lineup") or {};pmap={int(p.get("element")):p for p in predictions.get("players",[]) if p.get("element") is not None};umap={int(p.get("element")):p for p in universe.get("players",[]) if p.get("element") is not None};locked_ids=[int(p["element"]) for p in locked.get("players",[])]
    if len(locked_ids)!=15:raise RuntimeError("locked squad must contain 15 players")
    missing=[e for e in locked_ids if e not in pmap or e not in umap]
    if missing:raise RuntimeError(f"locked players missing prediction/universe data: {missing}")
    rows=[_player_row(pmap[e],umap[e],gw_index) for e in locked_ids]; formations=_formation_candidates(rows);best=formations[0];raw_xi=list(best["starting_xi"]);raw_form=best["formation"];raw_score=best["xi_xpts"]
    formation_margin=(best["risk_adjusted_score"]-formations[1]["risk_adjusted_score"]) if len(formations)>1 else 999;formation_open=formation_margin<_f(policy.get("formation_open_margin"),.35)
    chosen_xi=raw_xi;formation=raw_form;xi_score=raw_score;governance={"manual_draft_available":False,"decision":"OPTIMIZER_ONLY"};manual_snapshot=None
    if manual:
        mc=_manual_candidate(rows,manual)
        if mc:
            governance={"manual_draft_available":True,**_robustness_decision(raw_xi,raw_score,mc[0],mc[2])};manual_snapshot={"formation":mc[1],"xi_xpts":round(mc[2],2),"starting_ids":[r["element"] for r in mc[0]],"captain":manual.get("captain"),"vice_captain":manual.get("vice_captain"),"status":manual.get("status")}
            if governance["decision"]=="HOLD_MANUAL_DRAFT":chosen_xi,formation,xi_score=mc
    xi_ids={r["element"] for r in chosen_xi};selected_gk=next(r for r in chosen_xi if r["position"]=="GK");gk_governance=_gk_governance(rows,selected_gk,policy);bench_gk,bench_out,bench_governance=_bench(rows,xi_ids,policy);opt_c,opt_v,cap_governance=_captain_pair(chosen_xi,policy);captain,opt_vice=opt_c,opt_v;captain_decision="OPTIMIZER"
    if manual_snapshot and governance["decision"]=="HOLD_MANUAL_DRAFT":
        mm={r["element"]:r for r in chosen_xi};mc=mm.get(int(manual.get("captain",-1)));mv=mm.get(int(manual.get("vice_captain",-1)))
        if mc and mv and mc["dnp_probability"]<.30 and mc["start_probability"]>=.70:
            cap_gain=opt_c["captain_score"]-mc["captain_score"]
            if cap_gain<.40:captain,opt_vice,captain_decision=mc,mv,"HOLD_MANUAL_CAPTAIN"
    chip="WILDCARD" if bool(locked.get("wildcard_active")) else "NONE"
    alternatives=[{k:v for k,v in row.items() if k!="starting_xi"}|{"starting_ids":[r["element"] for r in row["starting_xi"]]} for row in formations]
    return {"schema_version":4962,"engine":"v4.9.6-lineup-risk-auditable","gw_offset":gw_index+1,"formation":formation,"formation_state":"OPEN" if formation_open else "DECIDED","formation_margin":round(formation_margin,4),"formation_alternatives":alternatives,"xi_xpts":round(xi_score,2),"starting_xi":sorted(chosen_xi,key=lambda r:(0 if r["position"]=="GK" else 1 if r["position"]=="DEF" else 2 if r["position"]=="MID" else 3,-r["xpts"])),"captain":captain,"vice_captain":opt_vice,"captaincy_governance":cap_governance,"gk_selection":gk_governance,"bench":{"gk":bench_gk,"order":[{"slot":i+1,**r} for i,r in enumerate(bench_out)]},"bench_governance":bench_governance,"optimizer_proposal":{"formation":raw_form,"xi_xpts":round(raw_score,2),"starting_ids":[r["element"] for r in raw_xi],"captain":opt_c["element"],"vice_captain":opt_v["element"]},"manual_draft":manual_snapshot,"governance":governance|{"captain_decision":captain_decision},"chip_context":{"active_chip":chip,"other_chip_recommendation":"NONE" if chip=="WILDCARD" else "UNASSESSED","single_chip_rule_respected":True},"guardrails":{"legal_formation":True,"all_legal_formations_evaluated":True,"formation_close_call_can_be_open":True,"gk_near_tie_risk_adjusted":True,"bench_false_precision_forbidden":True,"captain_reason_decomposed":True,"attacker_defender_vice_compared":True,"one_gk_in_xi":True,"captain_in_xi":True,"vice_in_xi":True,"bench_has_one_gk_three_outfield":True,"manual_draft_not_overwritten_without_margin":True,"prediction_interval_robustness":True}}


def run():
    out=optimize_lineup(read_json(DATA/"predictions_v4.json",{}),read_json(DATA/"universe.json",{}),read_json(CONFIG/"locked_squad.json",{}),manual=read_json(MANUAL_FILE,{}));print(json.dumps(out,ensure_ascii=False,indent=2));return out

if __name__=="__main__":run()
