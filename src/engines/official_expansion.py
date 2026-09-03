from __future__ import annotations

import json, os
from concurrent.futures import ThreadPoolExecutor

from src.engines.official_snapshot_primitives import endpoint_health, load_snapshot
from src.sources.official_fpl import get_json
from src.utils import DATA, ROOT, atomic_json, iso_now

TEAM_ID = 3462711
DETAIL_POLICY_PATH = ROOT / "config" / "runtime" / "official_detail_policy.json"
MINI_LEAGUE_CONFIG = ROOT / "config" / "strategy" / "mini_leagues.json"


def _detail_policy():
    payload = json.loads(DETAIL_POLICY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_OFFICIAL_DETAIL_POLICY_V1":
        raise RuntimeError("unexpected V3 official detail policy registry")
    return payload


_DETAIL_POLICY = _detail_policy()
MAX_DETAIL = max(1, int(os.getenv("FPL_ELEMENT_SUMMARY_MAX", str(_DETAIL_POLICY["element_summary_max"]))))
DETAIL_WORKERS = max(1, min(MAX_DETAIL, int(os.getenv("FPL_ELEMENT_SUMMARY_WORKERS", str(_DETAIL_POLICY["element_summary_workers"])))))
REQUEST_RETRIES = max(1, int(_DETAIL_POLICY.get("request_retries") or 1))


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


def _discovered_private_league_ids(kind, entry):
    cfg=_mini_league_config()
    auto=cfg.get("auto_discovery") or {}
    if not auto.get("enabled") or not isinstance(entry,dict): return []
    rows=((entry.get("leagues") or {}).get(kind) or [])
    limit=max(0,_i(auto.get("max_per_kind"),5))
    signals=tuple(auto.get("private_signals") or ["entry_can_leave","entry_can_admin","entry_can_invite"])
    out=[]
    for row in rows:
        if not isinstance(row,dict): continue
        if auto.get("private_only",True) and not any(row.get(key) is True for key in signals): continue
        lid=str(row.get("id") or "").strip()
        if lid and lid not in out: out.append(lid)
        if limit and len(out)>=limit: break
    return out


def _configured_league_ids(kind, entry=None):
    cfg=_mini_league_config()
    key=f"{kind}_league_ids"
    configured=[str(x).strip() for x in cfg.get(key,[]) if str(x).strip()]
    env_name=(cfg.get("environment_override") or {}).get(kind) or ("FPL_CLASSIC_LEAGUE_IDS" if kind=="classic" else "FPL_H2H_LEAGUE_IDS")
    env_ids=[x.strip() for x in os.getenv(str(env_name),"").split(",") if x.strip()]
    discovered=_discovered_private_league_ids(kind,entry)
    out=[]
    for lid in configured+env_ids+discovered:
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
    return {"fixtures": payload.get("fixtures",[]),"history": payload.get("history",[]),"history_past": payload.get("history_past",[])}


def _fetch_element_summary(eid):
    payload, health = get_json(f"element-summary/{eid}/", retries=REQUEST_RETRIES)
    return int(eid), payload, health


def _element_summaries(detail_ids):
    """Fetch the unchanged governed detail universe with bounded transport concurrency."""
    if not detail_ids:
        return {}, {}
    workers = max(1, min(DETAIL_WORKERS, len(detail_ids)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="v3-official-detail") as pool:
        fetched = list(pool.map(_fetch_element_summary, detail_ids))
    details={}
    health={}
    for eid,payload,row_health in fetched:
        health[str(eid)]=row_health
        if payload:
            details[str(eid)]=_compact_element_summary(payload)
    return details,health


def _fixture_stats(fixtures, planning_gw):
    rows=[]
    for f in fixtures or []:
        if planning_gw and f.get("event") not in {planning_gw, planning_gw-1}: continue
        rows.append({"id":f.get("id"),"event":f.get("event"),"kickoff_time":f.get("kickoff_time"),"team_h":f.get("team_h"),"team_a":f.get("team_a"),"team_h_score":f.get("team_h_score"),"team_a_score":f.get("team_a_score"),"finished":f.get("finished"),"started":f.get("started"),"stats":f.get("stats",[])})
    return rows


def _live_rich(live):
    if not live: return {"elements":[]}
    keys=("minutes","goals_scored","assists","clean_sheets","goals_conceded","own_goals","penalties_saved","penalties_missed","yellow_cards","red_cards","saves","bonus","bps","total_points","defensive_contribution")
    out=[]
    for e in live.get("elements",[]):
        s=e.get("stats",{})
        out.append({"id":e.get("id"),**{k:s.get(k) for k in keys if k in s},"explain":e.get("explain")})
    return {"elements":out}


def _optional_leagues(health,entry):
    result={"classic":{},"h2h":{}}
    for lid in _configured_league_ids("classic",entry):
        p,h=get_json(f"leagues-classic/{lid}/standings/",retries=REQUEST_RETRIES); health[f"league_classic_{lid}"]=h
        if p: result["classic"][lid]=p
    for lid in _configured_league_ids("h2h",entry):
        p,h=get_json(f"leagues-h2h/{lid}/standings/",retries=REQUEST_RETRIES); health[f"league_h2h_{lid}"]=h
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
    if not user: return {"kind":kind,"league_id":str(lid),"league_name":league.get("name"),"status":"ENTRY_NOT_ON_FETCHED_PAGE","entry_id":TEAM_ID}
    ordered=sorted(rows,key=lambda row:_i(row.get("rank"),10**9))
    idx=next((n for n,row in enumerate(ordered) if _i(row.get("entry"),-1)==TEAM_ID),-1)
    above=ordered[idx-1] if idx>0 else None
    below=ordered[idx+1] if 0<=idx<len(ordered)-1 else None
    total=_i(user.get("total")); rank=_i(user.get("rank")); last_rank=_i(user.get("last_rank"),rank)
    snap={"generated_at":iso_now(),"kind":kind,"league_id":str(lid),"league_name":league.get("name"),"status":"TRACKING","entry_id":TEAM_ID,"rank":rank,"last_rank":last_rank,"rank_delta":last_rank-rank,"total_points":total,"current_gw_points":current_gw_points,"above":None,"below":None,"points_behind_above":None,"points_ahead_below":None}
    if above:
        snap["above"]={"entry":above.get("entry"),"entry_name":above.get("entry_name"),"player_name":above.get("player_name"),"rank":above.get("rank"),"total":above.get("total")}; snap["points_behind_above"]=max(0,_i(above.get("total"))-total)
    if below:
        snap["below"]={"entry":below.get("entry"),"entry_name":below.get("entry_name"),"player_name":below.get("player_name"),"rank":below.get("rank"),"total":below.get("total")}; snap["points_ahead_below"]=max(0,total-_i(below.get("total")))
    prev_current=(previous or {}).get("current") or {}
    if prev_current:
        prior_total=_i(prev_current.get("total_points"),total); snap["points_delta_since_last_refresh"]=total-prior_total
        prior_gap=prev_current.get("points_behind_above")
        if prior_gap is not None and snap["points_behind_above"] is not None: snap["gap_to_above_delta"]=snap["points_behind_above"]-_i(prior_gap)
    return snap


def _mini_league_tracking(leagues,previous_detail,entry):
    cfg=_mini_league_config(); limit=max(1,_i(cfg.get("history_limit"),20))
    previous=((previous_detail or {}).get("mini_league_tracking") or {}).get("leagues") or {}
    configured={"classic":_configured_league_ids("classic",entry),"h2h":_configured_league_ids("h2h",entry)}
    discovery={"classic":_discovered_private_league_ids("classic",entry),"h2h":_discovered_private_league_ids("h2h",entry)}
    if not configured["classic"] and not configured["h2h"]:
        return {"status":"NO_PRIVATE_LEAGUES_DISCOVERED","model":cfg.get("model_id","mini_league_tracking_v2_autodiscovery"),"configured":configured,"auto_discovered":discovery,"leagues":{},"note":"no explicit or auto-discovered private mini league is available from the Official entry payload"}
    out={}; gw_points=(entry or {}).get("summary_event_points")
    for kind in ("classic","h2h"):
        for lid in configured[kind]:
            key=f"{kind}:{lid}"; payload=(leagues.get(kind) or {}).get(str(lid)); prior=previous.get(key) or {}
            if not payload:
                out[key]={"current":{"kind":kind,"league_id":str(lid),"status":"UNAVAILABLE"},"history":list(prior.get("history") or [])[-limit:]}; continue
            current=_league_snapshot(kind,lid,payload,prior,gw_points); history=list(prior.get("history") or [])
            history.append({k:current.get(k) for k in ("generated_at","rank","total_points","points_behind_above","points_ahead_below")})
            out[key]={"current":current,"history":history[-limit:]}
    tracking_count=sum(1 for row in out.values() if (row.get("current") or {}).get("status")=="TRACKING")
    return {"status":"TRACKING" if tracking_count else "CONFIGURED_NO_LIVE_STANDINGS","model":cfg.get("model_id","mini_league_tracking_v2_autodiscovery"),"configured":configured,"auto_discovered":discovery,"tracking_count":tracking_count,"leagues":out,"governance":cfg.get("governance") or {}}


def run():
    previous_detail=_load("official_detail.json",{}); latest=_load("latest.json",{})
    snapshot=load_snapshot()
    bootstrap=snapshot.get("bootstrap") or {}
    if not bootstrap: raise RuntimeError("Official snapshot bootstrap unavailable")
    phase=snapshot.get("phase") or latest.get("phase",{}); planning=phase.get("planning_gw"); scoring=phase.get("scoring_gw") or phase.get("current_gw")
    entry=snapshot.get("entry") or {}
    fixtures=snapshot.get("fixtures") or []
    live=snapshot.get("event_live") if scoring else None
    hb=endpoint_health(snapshot,"bootstrap")
    health={
        "bootstrap":hb,
        "entry_detail":endpoint_health(snapshot,"entry"),
        "fixtures_detail":endpoint_health(snapshot,"fixtures"),
    }
    if scoring:
        health["event_live_detail"]=endpoint_health(snapshot,"event_live")

    setpieces,h=get_json("team/set-piece-notes/",retries=REQUEST_RETRIES); health["set_piece_notes"]=h
    dream_all,h=get_json("dream-team/",retries=REQUEST_RETRIES); health["dream_team_season"]=h
    dream_gw=None; dream_gw_id=phase.get("last_finished_gw") or scoring
    if dream_gw_id: dream_gw,h=get_json(f"dream-team/{dream_gw_id}/",retries=REQUEST_RETRIES); health["dream_team_gw"]=h
    owned,detail_ids=_ids_from_state(bootstrap)
    details,detail_health=_element_summaries(detail_ids)
    cup,h=get_json(f"entry/{TEAM_ID}/cup/",retries=REQUEST_RETRIES); health["entry_cup"]=h
    leagues=_optional_leagues(health,entry); mini_league_tracking=_mini_league_tracking(leagues,previous_detail,entry)
    detail_ok=sum(1 for h in detail_health.values() if h.get("status")=="LIVE")
    official_health={"core":snapshot.get("endpoint_health",{}),"detail":health,"element_summary":{"requested":len(detail_ids),"live":detail_ok,"failed":len(detail_ids)-detail_ok},"overall":"HEALTHY" if hb.get("status")=="LIVE" and detail_ok>=len(owned) else "DEGRADED"}
    payload={"generated_at":iso_now(),"owned_element_ids":owned,"detail_element_ids":detail_ids,"element_summaries":details,"set_piece_notes":setpieces,"fixture_stats":_fixture_stats(fixtures,planning),"event_live_rich":_live_rich(live),"dream_team":{"season":dream_all,"gw":dream_gw,"gw_id":dream_gw_id},"leagues":leagues,"mini_league_tracking":mini_league_tracking,"entry_cup":cup,"official_health":official_health,"snapshot_reuse":{"bootstrap":True,"entry":True,"fixtures":True,"current_event_live":bool(scoring)}}
    atomic_json(DATA/"official_detail.json",payload)
    latest["official_detail_summary"]={"generated_at":payload["generated_at"],"owned_detail_coverage":f"{sum(1 for x in owned if str(x) in details)}/{len(owned)}","detail_requested":len(detail_ids),"detail_live":detail_ok,"set_piece_notes_status":health["set_piece_notes"].get("status"),"dream_team_status":health["dream_team_season"].get("status"),"entry_cup_status":health["entry_cup"].get("status"),"mini_league_status":mini_league_tracking.get("status"),"mini_leagues_tracking":mini_league_tracking.get("tracking_count",0),"mini_leagues_auto_discovered":sum(len(v) for v in (mini_league_tracking.get("auto_discovered") or {}).values()),"overall":official_health["overall"],"core_snapshot_reused":True,"file":"data/official_detail.json"}
    latest["official_health_panel"]=official_health; atomic_json(DATA/"latest.json",latest); return payload

if __name__ == "__main__": run()
