from __future__ import annotations

import json
from src.engines.fpl_rules_2026 import LEGAL_FORMATION_TUPLES
from src.engines.fpl_legality import formation_from_rows
from src.utils import DATA, CONFIG, read_json

MANUAL_FILE = CONFIG / "manual_lineup.json"
POLICY_FILE = CONFIG / "serving_improvement_registry.json"
UNDERSTAT_POLICY_FILE = CONFIG / "intelligence" / "understat_tactical.json"
UNDERSTAT_FILE = DATA / "understat_tactical_v4.json"


def _f(v, default=0.0):
    try: return float(v if v is not None else default)
    except (TypeError, ValueError): return float(default)


def _fixture_row(pred, idx=0):
    fx = pred.get("fixtures") or []
    return fx[idx] if idx < len(fx) and isinstance(fx[idx], dict) else {}


def _understat_for_element(tactical, element):
    row = ((tactical or {}).get("tactical_matchups") or {}).get(str(int(element))) or {}
    return {
        "state": row.get("state") or "INSUFFICIENT_EVIDENCE",
        "confidence": _f(row.get("confidence"), 0.0),
        "freshness": row.get("freshness"),
        "dimensions": row.get("dimensions") or {},
        "supporting_signals": row.get("supporting_signals") or [],
        "conflicting_signals": row.get("conflicting_signals") or [],
        "uncertainty": row.get("uncertainty") or {},
    }


def _player_row(pred, universe_row, idx=0, tactical=None):
    fx = _fixture_row(pred, idx); xm = fx.get("xmins") or {}; xpts = _f(fx.get("xpts")); lower = _f(fx.get("lower80"), xpts); upper = _f(fx.get("upper80"), xpts)
    start = _f(xm.get("start_probability"), 1.0 if _f(xm.get("expected_minutes"), 90) >= 60 else .5)
    start_conf = _f(xm.get("start_probability_confidence"), .5)
    bench = _f(xm.get("bench_probability"), max(0, 1-start)); dnp = _f(xm.get("dnp_probability"), max(0, 1-start-bench)); avail = max(0, min(1, 1-dnp))
    ceiling = max(xpts, upper); interval_width = max(0, upper-lower)
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
        "understat_tactical": _understat_for_element(tactical or {}, int(pred.get("element"))),
        "captain_reason": {"raw_xpts": round(xpts,4), "ceiling_uplift": round(.12*(ceiling-xpts),4), "dnp_penalty": round(1.65*dnp,4), "start_security_penalty": round(.45*max(0,.78-start),4)},
        "vice_reason": {"raw_xpts": round(xpts,4), "ceiling_uplift": round(.05*(ceiling-xpts),4), "dnp_penalty": round(1.95*dnp,4), "start_security_penalty": round(.55*max(0,.84-start),4)},
    }


def _formation(rows): return formation_from_rows(rows)


def _correlation_penalty(chosen):
    team_counts = {}
    for row in chosen: team_counts[row.get("team")] = team_counts.get(row.get("team"), 0) + 1
    return sum(max(0, count-2) ** 2 for count in team_counts.values()) * .06


def _positive_tactical(row, minimum_confidence):
    tactical = row.get("understat_tactical") or {}
    return str(tactical.get("state") or "") == "POSITIVE" and _f(tactical.get("confidence")) >= minimum_confidence


def _xmins_safe(candidate, boundary, max_start_disadvantage=.05, max_dnp_disadvantage=.05):
    start_disadvantage = _f(boundary.get("start_probability")) - _f(candidate.get("start_probability"))
    dnp_disadvantage = _f(candidate.get("dnp_probability")) - _f(boundary.get("dnp_probability"))
    return (
        start_disadvantage <= max_start_disadvantage + 1e-9
        and dnp_disadvantage <= max_dnp_disadvantage + 1e-9
    )


def _select_close_call(
    rows, count, score_key, margin, minimum_confidence, allow_tactical=True,
    max_start_disadvantage=.05, max_dnp_disadvantage=.05,
):
    ordered = sorted(rows, key=lambda r:(_f(r.get(score_key)), _f(r.get("xpts")), _f(r.get("start_probability"))), reverse=True)
    selected = list(ordered[:count])
    metadata = {"used": False, "displaced_element": None, "promoted_element": None, "score_gap": None}
    if not allow_tactical or not selected or len(ordered) <= count:
        return selected, metadata
    boundary = selected[-1]
    boundary_positive = _positive_tactical(boundary, minimum_confidence)
    eligible = []
    for candidate in ordered[count:]:
        gap = _f(boundary.get(score_key)) - _f(candidate.get(score_key))
        if gap < -1e-9 or gap > margin or not _positive_tactical(candidate, minimum_confidence):
            continue
        if not _xmins_safe(candidate, boundary, max_start_disadvantage, max_dnp_disadvantage):
            continue
        if boundary_positive and _f((candidate.get("understat_tactical") or {}).get("confidence")) <= _f((boundary.get("understat_tactical") or {}).get("confidence")):
            continue
        eligible.append((_f((candidate.get("understat_tactical") or {}).get("confidence")), _f(candidate.get(score_key)), candidate, gap))
    if eligible:
        _, _, challenger, gap = max(eligible, key=lambda item:(item[0], item[1], -int(item[2].get("element") or 0)))
        selected[-1] = challenger
        metadata = {
            "used": True,
            "displaced_element": boundary.get("element"),
            "promoted_element": challenger.get("element"),
            "score_gap": round(gap,4),
            "governed_margin": margin,
            "max_start_probability_disadvantage": max_start_disadvantage,
            "max_dnp_probability_disadvantage": max_dnp_disadvantage,
            "xmins_guard_passed": True,
            "reason": "POSITIVE_UNDERSTAT_MATCHUP_BREAKS_CLOSE_CALL_ONLY",
            "direct_xpts_mutation": False,
            "direct_xmins_mutation": False,
        }
    return selected, metadata


def _formation_candidates(rows, tactical_policy):
    by = {p:[r for r in rows if r["position"]==p] for p in ("GK","DEF","MID","FWD")}
    if not all(by[p] for p in by): raise RuntimeError("locked squad missing position group")
    cfg = tactical_policy.get("close_call") or {}
    player_margin = _f(cfg.get("lineup_selection_score_margin"), .12)
    formation_margin = _f(cfg.get("formation_risk_adjusted_margin"), .25)
    minimum_confidence = _f(cfg.get("minimum_confidence"), .6)
    max_start_disadvantage = _f(cfg.get("max_start_probability_disadvantage"), .05)
    max_dnp_disadvantage = _f(cfg.get("max_dnp_probability_disadvantage"), .05)
    gks = sorted(by["GK"], key=lambda r:(r["selection_score"],r["start_probability"],-r["dnp_probability"]), reverse=True)
    candidates = []
    for d,m,f in LEGAL_FORMATION_TUPLES:
        if len(by["DEF"])<d or len(by["MID"])<m or len(by["FWD"])<f: continue
        gk = gks[0]
        args = (player_margin, minimum_confidence, True, max_start_disadvantage, max_dnp_disadvantage)
        defs, def_meta = _select_close_call(by["DEF"], d, "selection_score", *args)
        mids, mid_meta = _select_close_call(by["MID"], m, "selection_score", *args)
        fwds, fwd_meta = _select_close_call(by["FWD"], f, "selection_score", *args)
        chosen = [gk] + defs + mids + fwds
        xpts = sum(r["xpts"] for r in chosen); dnp = sum(r["dnp_probability"] for r in chosen); uncertainty = sum(r["interval_width"] for r in chosen); correlation = _correlation_penalty(chosen)
        risk_adjusted = xpts - .28*dnp - .012*uncertainty - correlation
        tactical_positive = sum(_positive_tactical(row, minimum_confidence) for row in chosen)
        candidates.append({
            "formation":f"{d}-{m}-{f}","starting_xi":chosen,"xi_xpts":round(xpts,3),"risk_adjusted_score":round(risk_adjusted,3),"uncertainty":round(uncertainty,3),"dnp_risk":round(dnp,3),"structural_correlation_penalty":round(correlation,3),
            "mean_start_probability": round(sum(_f(r.get("start_probability")) for r in chosen)/len(chosen),4),
            "mean_dnp_probability": round(sum(_f(r.get("dnp_probability")) for r in chosen)/len(chosen),4),
            "understat_positive_context_count": tactical_positive,
            "understat_player_close_calls": [meta for meta in (def_meta, mid_meta, fwd_meta) if meta.get("used")],
        })
    candidates.sort(key=lambda row:(row["risk_adjusted_score"],row["xi_xpts"],-row["dnp_risk"]), reverse=True)
    if not candidates: raise RuntimeError("no legal XI")
    raw_leader = candidates[0]
    near = [
        row for row in candidates
        if raw_leader["risk_adjusted_score"] - row["risk_adjusted_score"] <= formation_margin
        and raw_leader["mean_start_probability"] - row["mean_start_probability"] <= max_start_disadvantage + 1e-9
        and row["mean_dnp_probability"] - raw_leader["mean_dnp_probability"] <= max_dnp_disadvantage + 1e-9
    ]
    selected = max(near, key=lambda row:(row["understat_positive_context_count"], row["risk_adjusted_score"], row["xi_xpts"])) if near else raw_leader
    tactical_formation_used = selected is not raw_leader and selected["understat_positive_context_count"] > raw_leader["understat_positive_context_count"]
    if tactical_formation_used:
        candidates.remove(selected)
        candidates.insert(0, selected)
    selected_score = candidates[0]["risk_adjusted_score"]
    for row in candidates:
        row["marginal_gain_vs_best"] = round(row["risk_adjusted_score"]-selected_score,3)
        row["understat_formation_close_call"] = {
            "used": tactical_formation_used and row is candidates[0],
            "raw_risk_leader_formation": raw_leader["formation"],
            "raw_risk_leader_score": raw_leader["risk_adjusted_score"],
            "governed_margin": formation_margin,
            "xmins_guarded": True,
            "direct_xpts_mutation": False,
            "direct_xmins_mutation": False,
        }
    return candidates


def _gk_governance(rows, selected_gk, policy):
    gks = sorted([r for r in rows if r["position"]=="GK"], key=lambda r:(r["selection_score"],r["xpts"]), reverse=True)
    if len(gks)<2: return {"status":"DECIDED","selected":selected_gk,"alternatives":gks}
    first, second = gks[:2]; raw_margin = abs(first["xpts"]-second["xpts"]); selection_margin = abs(first["selection_score"]-second["selection_score"])
    raw_threshold = _f(policy.get("gk_open_raw_xpts_margin"),.15); sel_threshold = _f(policy.get("gk_open_selection_margin"),.12)
    open_state = raw_margin < raw_threshold and selection_margin < sel_threshold
    return {"status":"OPEN" if open_state else "DECIDED","selected":selected_gk,"alternatives":gks[:2],"raw_xpts_margin":round(raw_margin,4),"risk_adjusted_margin":round(selection_margin,4),"raw_open_threshold":raw_threshold,"selection_open_threshold":sel_threshold,"reason":"RAW_NEAR_TIE_START_SECURITY_MATERIAL" if open_state else "RISK_ADJUSTED_GK_LEADER"}


def _bench(rows, xi_ids, policy, tactical_policy):
    bench = [r for r in rows if r["element"] not in xi_ids]; gks = [r for r in bench if r["position"]=="GK"]; out = [r for r in bench if r["position"]!="GK"]
    if len(gks)!=1 or len(out)!=3: raise RuntimeError("bench structure invalid")
    out.sort(key=lambda r:(r["bench_score"],r["xpts"],r["start_probability"]),reverse=True)
    cfg = tactical_policy.get("close_call") or {}
    tactical_margin=_f(cfg.get("bench_score_margin"),.12); minimum_confidence=_f(cfg.get("minimum_confidence"),.6)
    max_start_disadvantage=_f(cfg.get("max_start_probability_disadvantage"),.05); max_dnp_disadvantage=_f(cfg.get("max_dnp_probability_disadvantage"),.05)
    swaps=[]
    for index in range(len(out)-1):
        first, second = out[index], out[index+1]
        gap = _f(first.get("bench_score"))-_f(second.get("bench_score"))
        if (
            0 <= gap <= tactical_margin
            and _positive_tactical(second,minimum_confidence)
            and not _positive_tactical(first,minimum_confidence)
            and _xmins_safe(second, first, max_start_disadvantage, max_dnp_disadvantage)
        ):
            out[index],out[index+1]=second,first
            swaps.append({"from_slot":index+2,"to_slot":index+1,"element":second["element"],"base_score_gap":round(gap,4),"governed_margin":tactical_margin,"xmins_guard_passed":True})
            break
    gaps = [round(out[i]["bench_score"]-out[i+1]["bench_score"],4) for i in range(len(out)-1)]
    threshold = _f(policy.get("bench_open_score_margin"),.15); open_state = any(abs(gap)<threshold for gap in gaps)
    reasoning=[]
    for index,row in enumerate(out):
        reasoning.append({"slot":index+1,"element":row["element"],"name":row["name"],"bench_score":row["bench_score"],"autosub_legal":True,"start_security":row["start_probability"],"ceiling":row["upper80"],"role":row.get("role"),"dnp_risk":row["dnp_probability"],"understat_tactical":row.get("understat_tactical")})
    return gks[0], out, {"status":"OPEN" if open_state else "DECIDED","score_gaps":gaps,"open_threshold":threshold,"reasoning":reasoning,"false_precision_forbidden":True,"understat_close_call_swaps":swaps,"understat_xmins_guarded":True,"understat_direct_xpts_mutation":False,"understat_direct_xmins_mutation":False}


def _captain_pair(xi, policy):
    pool=[r for r in xi if r["position"]!="GK"] or xi; safe=[r for r in pool if r["dnp_probability"]<.30 and r["start_probability"]>=.70] or pool
    ranked=sorted(safe,key=lambda r:(r["captain_score"],r["xpts"],r["upper80"]),reverse=True); captain=ranked[0]
    vice_pool=[r for r in pool if r["element"]!=captain["element"]]; vice_safe=[r for r in vice_pool if r["dnp_probability"]<.25 and r["start_probability"]>=.75] or vice_pool
    vice_ranked=sorted(vice_safe,key=lambda r:(r["vice_score"],r["xpts"],r["start_probability"]),reverse=True); vice=vice_ranked[0]
    threshold=_f(policy.get("captain_close_margin"),.30); cap_gap=(ranked[0]["captain_score"]-ranked[1]["captain_score"]) if len(ranked)>1 else 999; status="OPEN" if cap_gap<threshold else "DECIDED"
    attacker_vice=next((r for r in vice_ranked if r["position"] in {"MID","FWD"}),None); defender_vice=next((r for r in vice_ranked if r["position"]=="DEF"),None)
    governance={"status":status,"captain_margin":round(cap_gap,4),"open_threshold":threshold,"captain_candidates":[{"element":r["element"],"name":r["name"],"score":r["captain_score"],"reason":r["captain_reason"]} for r in ranked[:5]],"vice_candidates":[{"element":r["element"],"name":r["name"],"score":r["vice_score"],"reason":r["vice_reason"]} for r in vice_ranked[:5]],"attacker_vs_defender_vice":{"attacker":attacker_vice,"defender":defender_vice},"small_raw_xpts_edge_cannot_bypass_risk_adjustment":True,"understat_captaincy_semantics_unchanged":True}
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


def optimize_lineup(predictions,universe,locked,gw_index=0,manual=None,tactical=None):
    policy=(read_json(POLICY_FILE,{}) or {}).get("lineup") or {};tactical_policy=read_json(UNDERSTAT_POLICY_FILE,{}) or {};tactical=tactical if tactical is not None else read_json(UNDERSTAT_FILE,{})
    pmap={int(p.get("element")):p for p in predictions.get("players",[]) if p.get("element") is not None};umap={int(p.get("element")):p for p in universe.get("players",[]) if p.get("element") is not None};locked_ids=[int(p["element"]) for p in locked.get("players",[])]
    if len(locked_ids)!=15:raise RuntimeError("locked squad must contain 15 players")
    missing=[e for e in locked_ids if e not in pmap or e not in umap]
    if missing:raise RuntimeError(f"locked players missing prediction/universe data: {missing}")
    rows=[_player_row(pmap[e],umap[e],gw_index,tactical=tactical) for e in locked_ids]; formations=_formation_candidates(rows,tactical_policy);best=formations[0];raw_xi=list(best["starting_xi"]);raw_form=best["formation"];raw_score=best["xi_xpts"]
    formation_margin=(best["risk_adjusted_score"]-formations[1]["risk_adjusted_score"]) if len(formations)>1 else 999;formation_open=abs(formation_margin)<_f(policy.get("formation_open_margin"),.35)
    chosen_xi=raw_xi;formation=raw_form;xi_score=raw_score;governance={"manual_draft_available":False,"decision":"OPTIMIZER_ONLY"};manual_snapshot=None
    if manual:
        mc=_manual_candidate(rows,manual)
        if mc:
            governance={"manual_draft_available":True,**_robustness_decision(raw_xi,raw_score,mc[0],mc[2])};manual_snapshot={"formation":mc[1],"xi_xpts":round(mc[2],2),"starting_ids":[r["element"] for r in mc[0]],"captain":manual.get("captain"),"vice_captain":manual.get("vice_captain"),"status":manual.get("status")}
            if governance["decision"]=="HOLD_MANUAL_DRAFT":chosen_xi,formation,xi_score=mc
    xi_ids={r["element"] for r in chosen_xi};selected_gk=next(r for r in chosen_xi if r["position"]=="GK");gk_governance=_gk_governance(rows,selected_gk,policy);bench_gk,bench_out,bench_governance=_bench(rows,xi_ids,policy,tactical_policy);opt_c,opt_v,cap_governance=_captain_pair(chosen_xi,policy);captain,opt_vice=opt_c,opt_v;captain_decision="OPTIMIZER"
    if manual_snapshot and governance["decision"]=="HOLD_MANUAL_DRAFT":
        mm={r["element"]:r for r in chosen_xi};mc=mm.get(int(manual.get("captain",-1)));mv=mm.get(int(manual.get("vice_captain",-1)))
        if mc and mv and mc["dnp_probability"]<.30 and mc["start_probability"]>=.70:
            cap_gain=opt_c["captain_score"]-mc["captain_score"]
            if cap_gain<.40:captain,opt_vice,captain_decision=mc,mv,"HOLD_MANUAL_CAPTAIN"
    chip="WILDCARD" if bool(locked.get("wildcard_active")) else "NONE"
    alternatives=[{k:v for k,v in row.items() if k!="starting_xi"}|{"starting_ids":[r["element"] for r in row["starting_xi"]]} for row in formations]
    understat_health=(tactical.get("health") or {}).get("status") or "UNAVAILABLE"
    return {"schema_version":4963,"engine":"v4.9.6-lineup-risk-auditable-understat-close-call","gw_offset":gw_index+1,"formation":formation,"formation_state":"OPEN" if formation_open else "DECIDED","formation_margin":round(formation_margin,4),"formation_alternatives":alternatives,"xi_xpts":round(xi_score,2),"starting_xi":sorted(chosen_xi,key=lambda r:(0 if r["position"]=="GK" else 1 if r["position"]=="DEF" else 2 if r["position"]=="MID" else 3,-r["xpts"])),"captain":captain,"vice_captain":opt_vice,"captaincy_governance":cap_governance,"gk_selection":gk_governance,"bench":{"gk":bench_gk,"order":[{"slot":i+1,**r} for i,r in enumerate(bench_out)]},"bench_governance":bench_governance,"optimizer_proposal":{"formation":raw_form,"xi_xpts":round(raw_score,2),"starting_ids":[r["element"] for r in raw_xi],"captain":opt_c["element"],"vice_captain":opt_v["element"]},"manual_draft":manual_snapshot,"governance":governance|{"captain_decision":captain_decision},"understat_tactical":{"health":understat_health,"close_call_only":True,"xmins_guarded":True,"direct_xpts_mutation":False,"direct_xmins_mutation":False,"captaincy_semantics_unchanged":True},"chip_context":{"active_chip":chip,"other_chip_recommendation":"NONE" if chip=="WILDCARD" else "UNASSESSED","single_chip_rule_respected":True},"guardrails":{"legal_formation":True,"all_legal_formations_evaluated":True,"formation_close_call_can_be_open":True,"gk_near_tie_risk_adjusted":True,"bench_false_precision_forbidden":True,"captain_reason_decomposed":True,"attacker_defender_vice_compared":True,"one_gk_in_xi":True,"captain_in_xi":True,"vice_in_xi":True,"bench_has_one_gk_three_outfield":True,"manual_draft_not_overwritten_without_margin":True,"prediction_interval_robustness":True,"understat_only_breaks_governed_close_calls":True,"understat_missing_is_neutral":True,"understat_cannot_erase_xmins":True,"understat_direct_xpts_mutation":False,"understat_direct_xmins_mutation":False,"optimizer_legal_formation_width_unchanged":True}}


def run():
    out=optimize_lineup(read_json(DATA/"predictions_v4.json",{}),read_json(DATA/"universe.json",{}),read_json(CONFIG/"locked_squad.json",{}),manual=read_json(MANUAL_FILE,{}));print(json.dumps(out,ensure_ascii=False,indent=2));return out

if __name__=="__main__":run()
