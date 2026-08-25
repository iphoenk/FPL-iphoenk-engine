from __future__ import annotations

import json, os
from src.sources.official_fpl import get_json
from src.utils import DATA, atomic_json, iso_now

TEAM_ID = 3462711
MAX_DETAIL = int(os.getenv("FPL_ELEMENT_SUMMARY_MAX", "40"))


def _load(name, default):
    try:
        with open(DATA/name) as f: return json.load(f)
    except Exception:
        return default


def _ids_from_state(bootstrap):
    owned=[]
    team=_load("team.json",{})
    for x in team.get("squad",[]):
        if x.get("element") is not None: owned.append(int(x["element"]))
    prices=_load("prices.json",{})
    radar=[int(x["element"]) for x in prices.get("top_buy_pressure",[]) if x.get("element") is not None]
    elements=bootstrap.get("elements",[])
    popular=sorted(elements,key=lambda p:(p.get("total_points") or 0,float(p.get("selected_by_percent") or 0)),reverse=True)
    candidates=[int(p["id"]) for p in popular]
    out=[]
    for i in owned+radar+candidates:
        if i not in out: out.append(i)
        if len(out)>=MAX_DETAIL: break
    return owned,out


def _compact_element_summary(payload):
    if not payload: return None
    return {
        "fixtures": payload.get("fixtures",[]),
        "history": payload.get("history",[]),
        "history_past": payload.get("history_past",[]),
    }


def _fixture_stats(fixtures, planning_gw):
    rows=[]
    for f in fixtures or []:
        if planning_gw and f.get("event") not in {planning_gw, planning_gw-1}: continue
        rows.append({
            "id":f.get("id"),"event":f.get("event"),"kickoff_time":f.get("kickoff_time"),
            "team_h":f.get("team_h"),"team_a":f.get("team_a"),"team_h_score":f.get("team_h_score"),
            "team_a_score":f.get("team_a_score"),"finished":f.get("finished"),"started":f.get("started"),
            "stats":f.get("stats",[]),
        })
    return rows


def _live_rich(live):
    if not live: return {"elements":[]}
    keys=("minutes","goals_scored","assists","clean_sheets","goals_conceded","own_goals",
          "penalties_saved","penalties_missed","yellow_cards","red_cards","saves","bonus","bps",
          "total_points","defensive_contribution")
    out=[]
    for e in live.get("elements",[]):
        s=e.get("stats",{})
        out.append({"id":e.get("id"),**{k:s.get(k) for k in keys if k in s},"explain":e.get("explain")})
    return {"elements":out}


def _optional_leagues(health):
    result={"classic":{},"h2h":{}}
    classic=[x.strip() for x in os.getenv("FPL_CLASSIC_LEAGUE_IDS","").split(",") if x.strip()]
    h2h=[x.strip() for x in os.getenv("FPL_H2H_LEAGUE_IDS","").split(",") if x.strip()]
    for lid in classic:
        p,h=get_json(f"leagues-classic/{lid}/standings/",retries=1); health[f"league_classic_{lid}"]=h
        if p: result["classic"][lid]=p
    for lid in h2h:
        p,h=get_json(f"leagues-h2h/{lid}/standings/",retries=1); health[f"league_h2h_{lid}"]=h
        if p: result["h2h"][lid]=p
    return result


def run():
    latest=_load("latest.json",{})
    bootstrap,hb=get_json("bootstrap-static/")
    if not bootstrap: raise RuntimeError("Official bootstrap unavailable")
    phase=latest.get("phase",{})
    planning=phase.get("planning_gw")
    scoring=phase.get("scoring_gw") or phase.get("current_gw")
    health={"bootstrap":hb}

    fixtures,h=get_json("fixtures/"); health["fixtures_detail"]=h
    live=None
    if scoring:
        live,h=get_json(f"event/{scoring}/live/"); health["event_live_detail"]=h

    setpieces,h=get_json("team/set-piece-notes/",retries=1); health["set_piece_notes"]=h
    dream_all,h=get_json("dream-team/",retries=1); health["dream_team_season"]=h
    dream_gw=None
    dream_gw_id=phase.get("last_finished_gw") or scoring
    if dream_gw_id:
        dream_gw,h=get_json(f"dream-team/{dream_gw_id}/",retries=1); health["dream_team_gw"]=h

    owned,detail_ids=_ids_from_state(bootstrap)
    details={}
    detail_health={}
    for eid in detail_ids:
        payload,h=get_json(f"element-summary/{eid}/",retries=1)
        detail_health[str(eid)]=h
        if payload: details[str(eid)]=_compact_element_summary(payload)

    cup,h=get_json(f"entry/{TEAM_ID}/cup/",retries=1); health["entry_cup"]=h
    leagues=_optional_leagues(health)

    detail_ok=sum(1 for h in detail_health.values() if h.get("status")=="LIVE")
    official_health={
        "core":latest.get("endpoint_health",{}),
        "detail":health,
        "element_summary":{"requested":len(detail_ids),"live":detail_ok,"failed":len(detail_ids)-detail_ok},
        "overall":"HEALTHY" if hb.get("status")=="LIVE" and detail_ok>=len(owned) else "DEGRADED",
    }
    payload={
        "generated_at":iso_now(),"owned_element_ids":owned,"detail_element_ids":detail_ids,
        "element_summaries":details,"set_piece_notes":setpieces,"fixture_stats":_fixture_stats(fixtures,planning),
        "event_live_rich":_live_rich(live),"dream_team":{"season":dream_all,"gw":dream_gw,"gw_id":dream_gw_id},
        "leagues":leagues,"entry_cup":cup,"official_health":official_health,
    }
    atomic_json(DATA/"official_detail.json",payload)
    latest["official_detail_summary"]={
        "generated_at":payload["generated_at"],"owned_detail_coverage":f"{sum(1 for x in owned if str(x) in details)}/{len(owned)}",
        "detail_requested":len(detail_ids),"detail_live":detail_ok,
        "set_piece_notes_status":health["set_piece_notes"].get("status"),
        "dream_team_status":health["dream_team_season"].get("status"),
        "entry_cup_status":health["entry_cup"].get("status"),
        "overall":official_health["overall"],"file":"data/official_detail.json",
    }
    latest["official_health_panel"]=official_health
    atomic_json(DATA/"latest.json",latest)
    return payload

if __name__ == "__main__": run()
