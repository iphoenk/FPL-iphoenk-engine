from __future__ import annotations

import json, os
from src.sources.official_fpl import get_json
from src.utils import DATA, ROOT, atomic_json, iso_now

TEAM_ID = 3462711
MAX_DETAIL = int(os.getenv("FPL_ELEMENT_SUMMARY_MAX", "40"))
MINI_LEAGUE_CONFIG = ROOT / "config" / "strategy" / "mini_leagues.json"


def _load(name, default):
    try:
        with open(DATA/name) as f: return json.load(f)
    except Exception:
        return default


def _mini_league_config():
    try:
        payload=json.loads(MINI_LEAGUE_CONFIG.read_text(encoding="utf-8"))
        return payload if isinstance(payload,dict) else {}
    except Exception:
        return {}


def _configured_league_ids(kind):
    cfg=_mini_league_config()
    key=f"{kind}_league_ids"
    configured=[str(x).strip() for x in cfg.get(key,[]) if str(x).strip()]
    env_name=(cfg.get("environment_override") or {}).get(kind) or ("FPL_CLASSIC_LEAGUE_IDS" if kind=="classic" else "FPL_H2H_LEAGUE_IDS")
    env_ids=[x.strip() for x in os.getenv(str(env_name),"").split(",") if x.strip()]
    out=[]
    for lid in configured+env_ids:
        if lid not in out: out.append(lid)
    return out


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
    for lid in _configured_league_ids("classic"):
        p,h=get_json(f"leagues-classic/{lid}/standings/",retries=1); health[f"league_classic_{lid}"]=h
        if p: result["classic"][lid]=p
    for lid in _configured_league_ids("h2h"):
        p,h=get_json(f"leagues-h2h/{lid}/standings/",retries=1); health[f"league_h2h_{lid}"]=h
        if p: result["h2h"][lid]=p
    return result


def _i(value, default=0):
    try: return int(value)
    except (TypeError,ValueError): return int(default)


def _standing_rows(payload):
    standings=(payload or {}).get("standings") or {}
    rows=standings.get("results") or []
    return [row for row in rows if isinstance(row,dict)]


def _league_snapshot(kind,lid,payload,previous,current_gw_points):
    rows=_standing_rows(payload)
    user=next((row for row in rows if _i(row.get("entry"),-1)==TEAM_ID),None)
    league=payload.get("league") or {}
    if not user:
        return {
            "kind":kind,"league_id":str(lid),"league_name":league.get("name"),
            "status":"ENTRY_NOT_ON_FETCHED_PAGE","entry_id":TEAM_ID,
        }
    ordered=sorted(rows,key=lambda row:_i(row.get("rank"),10**9))
    idx=next((n for n,row in enumerate(ordered) if _i(row.get("entry"),-1)==TEAM_ID),-1)
    above=ordered[idx-1] if idx>0 else None
    below=ordered[idx+1] if 0<=idx<len(ordered)-1 else None
    total=_i(user.get("total"))
    rank=_i(user.get("rank"))
    last_rank=_i(user.get("last_rank"),rank)
    snap={
        "generated_at":iso_now(),"kind":kind,"league_id":str(lid),"league_name":league.get("name"),
        "status":"TRACKING","entry_id":TEAM_ID,"rank":rank,"last_rank":last_rank,
        "rank_delta":last_rank-rank,"total_points":total,"current_gw_points":current_gw_points,
        "above":None,"below":None,
        "points_behind_above":None,"points_ahead_below":None,
    }
    if above:
        snap["above"]={"entry":above.get("entry"),"entry_name":above.get("entry_name"),"player_name":above.get("player_name"),"rank":above.get("rank"),"total":above.get("total")}
        snap["points_behind_above"]=max(0,_i(above.get("total"))-total)
    if below:
        snap["below"]={"entry":below.get("entry"),"entry_name":below.get("entry_name"),"player_name":below.get("player_name"),"rank":below.get("rank"),"total":below.get("total")}
        snap["points_ahead_below"]=max(0,total-_i(below.get("total")))
    prev_current=(previous or {}).get("current") or {}
    if prev_current:
        prior_total=_i(prev_current.get("total_points"),total)
        snap["points_delta_since_last_refresh"]=total-prior_total
        prior_gap=prev_current.get("points_behind_above")
        if prior_gap is not None and snap["points_behind_above"] is not None:
            snap["gap_to_above_delta"]=snap["points_behind_above"]-_i(prior_gap)
    return snap


def _mini_league_tracking(leagues,previous_detail,latest):
    cfg=_mini_league_config()
    limit=max(1,_i(cfg.get("history_limit"),20))
    previous=((previous_detail or {}).get("mini_league_tracking") or {}).get("leagues") or {}
    configured={"classic":_configured_league_ids("classic"),"h2h":_configured_league_ids("h2h")}
    if not configured["classic"] and not configured["h2h"]:
        return {
            "status":"CONFIG_REQUIRED","model":cfg.get("model_id","mini_league_tracking_v1"),
            "configured":configured,"leagues":{},
            "note":"set numeric Classic/H2H league IDs in config or environment; no rival state is inferred without explicit league selection",
        }
    out={}
    gw_points=((latest.get("entry") or {}).get("summary_event_points"))
    for kind in ("classic","h2h"):
        for lid in configured[kind]:
            key=f"{kind}:{lid}"
            payload=(leagues.get(kind) or {}).get(str(lid))
            prior=previous.get(key) or {}
            if not payload:
                out[key]={"current":{"kind":kind,"league_id":str(lid),"status":"UNAVAILABLE"},"history":list(prior.get("history") or [])[-limit:]}
                continue
            current=_league_snapshot(kind,lid,payload,prior,gw_points)
            history=list(prior.get("history") or [])
            history.append({k:current.get(k) for k in ("generated_at","rank","total_points","points_behind_above","points_ahead_below")})
            out[key]={"current":current,"history":history[-limit:]}
    tracking_count=sum(1 for row in out.values() if (row.get("current") or {}).get("status")=="TRACKING")
    return {
        "status":"TRACKING" if tracking_count else "CONFIGURED_NO_LIVE_STANDINGS",
        "model":cfg.get("model_id","mini_league_tracking_v1"),"configured":configured,
        "tracking_count":tracking_count,"leagues":out,
        "governance":cfg.get("governance") or {},
    }


def run():
    previous_detail=_load("official_detail.json",{})
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
    mini_league_tracking=_mini_league_tracking(leagues,previous_detail,latest)

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
        "leagues":leagues,"mini_league_tracking":mini_league_tracking,"entry_cup":cup,"official_health":official_health,
    }
    atomic_json(DATA/"official_detail.json",payload)
    latest["official_detail_summary"]={
        "generated_at":payload["generated_at"],"owned_detail_coverage":f"{sum(1 for x in owned if str(x) in details)}/{len(owned)}",
        "detail_requested":len(detail_ids),"detail_live":detail_ok,
        "set_piece_notes_status":health["set_piece_notes"].get("status"),
        "dream_team_status":health["dream_team_season"].get("status"),
        "entry_cup_status":health["entry_cup"].get("status"),
        "mini_league_status":mini_league_tracking.get("status"),
        "mini_leagues_tracking":mini_league_tracking.get("tracking_count",0),
        "overall":official_health["overall"],"file":"data/official_detail.json",
    }
    latest["official_health_panel"]=official_health
    atomic_json(DATA/"latest.json",latest)
    return payload

if __name__ == "__main__": run()
