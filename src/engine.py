from __future__ import annotations
import argparse, json
from src.utils import DATA, CONFIG, iso_now, utcnow, atomic_json, append_jsonl, read_json, parse_dt
from src.sources.official_fpl import get_json
from src.sources import core_insights, vaastav
from src.engines.team_value import sell_cost, build_transfer_spells
from src.engines.v4_runner import build_predictions

TEAM_ID=3462711

def detect_phase(bootstrap):
 events=bootstrap.get("events",[]); current=next((e for e in events if e.get("is_current")),None); nxt=next((e for e in events if e.get("is_next")),None); finished=[e for e in events if e.get("finished")]; last=max(finished,key=lambda e:e["id"]) if finished else None; planning=None
 if current:
  deadline=parse_dt(current.get("deadline_time")); planning=current if deadline and deadline>utcnow() else (nxt or current)
 else: planning=nxt
 return {"current_gw":current["id"] if current else None,"next_gw":nxt["id"] if nxt else None,"last_finished_gw":last["id"] if last else None,"planning_gw":planning["id"] if planning else None,"submitted_gw":(current or last or {}).get("id"),"scoring_gw":current["id"] if current else None,"deadline_time":planning.get("deadline_time") if planning else None,"is_live_event":bool(current and not current.get("finished"))}

def maps(b):
 teams={t["id"]:t["name"] for t in b["teams"]}; pos={1:"GK",2:"DEF",3:"MID",4:"FWD"}; by_id={p["id"]:p for p in b["elements"]}; return teams,pos,by_id

def resolve_locked_player(row,by_id,teams,pos):
 e=row.get("element"); p=by_id.get(int(e)) if e is not None else None
 if not p: raise RuntimeError(f"FAIL CLOSED: locked element {e} missing")
 if row.get("position") and pos.get(p.get("element_type"))!=row["position"]: raise RuntimeError(f"FAIL CLOSED: position mismatch {e}")
 if row.get("expected_web_name") and p.get("web_name")!=row["expected_web_name"]: raise RuntimeError(f"FAIL CLOSED: name mismatch {e}")
 if row.get("expected_team") and teams.get(p.get("team"))!=row["expected_team"]: raise RuntimeError(f"FAIL CLOSED: team mismatch {e}")
 return p

def expanded_live(el):
 s=el.get("stats",{}); allowed=["minutes","goals_scored","assists","clean_sheets","goals_conceded","own_goals","penalties_saved","penalties_missed","yellow_cards","red_cards","saves","bonus","bps","total_points","defensive_contribution"]; out={k:s.get(k) for k in allowed if k in s}; out["explain"]=el.get("explain"); return out

def run(mode="daily",sync_stats=False,deep_stats=False):
 health={}; bootstrap,h=get_json("bootstrap-static/"); health["bootstrap"]=h
 if not bootstrap: atomic_json(DATA/"health.json",health); raise RuntimeError("bootstrap unavailable")
 fixtures,h=get_json("fixtures/");health["fixtures"]=h; status,h=get_json("event-status/");health["event_status"]=h; entry,h=get_json(f"entry/{TEAM_ID}/");health["entry"]=h; history,h=get_json(f"entry/{TEAM_ID}/history/");health["history"]=h; transfers,h=get_json(f"entry/{TEAM_ID}/transfers/");health["transfers"]=h; transfers=transfers or []
 phase=detect_phase(bootstrap); teams,pos,by_id=maps(bootstrap); submitted_gw=phase["submitted_gw"]; picks=None
 if submitted_gw: picks,h=get_json(f"entry/{TEAM_ID}/event/{submitted_gw}/picks/"); h["status"]="LIVE" if picks else "NOT_YET_AVAILABLE"; health["picks"]=h
 scoring_gw=phase["scoring_gw"]; live=None
 if scoring_gw: live,h=get_json(f"event/{scoring_gw}/live/"); h["status"]="IDLE" if h["status"]=="LIVE" and not phase["is_live_event"] else h["status"]; health["event_live"]=h
 lock=read_json(CONFIG/"locked_squad.json",{}); use_lock=bool(lock.get("wildcard_active")) and phase["planning_gw"]!=submitted_gw; squad=[]
 if use_lock:
  seen=set()
  for row in lock.get("players",[]):
   p=resolve_locked_player(row,by_id,teams,pos)
   if p["id"] in seen: raise RuntimeError(f"FAIL CLOSED: duplicate {p['id']}")
   seen.add(p["id"]); squad.append({"element":p["id"],"name":p["web_name"],"position":pos[p["element_type"]],"purchase_cost":row.get("purchase_cost"),"source":"locked_squad_element_id"})
 elif picks:
  for x in picks.get("picks",[]):
   p=by_id.get(x["element"])
   if p:squad.append({"element":p["id"],"name":p["web_name"],"position":pos[p["element_type"]],"source":"official_picks"})
 if squad and len(squad)!=15:raise RuntimeError(f"FAIL CLOSED: squad count {len(squad)}")
 counts={k:sum(1 for p in squad if p["position"]==k) for k in ["GK","DEF","MID","FWD"]}
 if squad and counts!={"GK":2,"DEF":5,"MID":5,"FWD":3}:raise RuntimeError(f"FAIL CLOSED: positions {counts}")
 clubs={}
 for row in squad:club=teams[by_id[row["element"]]["team"]];clubs[club]=clubs.get(club,0)+1
 if squad and max(clubs.values(),default=0)>3:raise RuntimeError(f"FAIL CLOSED: club limit {clubs}")
 spells=build_transfer_spells(transfers); gw1,_=get_json(f"entry/{TEAM_ID}/event/1/picks/",retries=1); gw1ids={x["element"] for x in (gw1 or {}).get("picks",[])}; ledger=[]
 for row in squad:
  p=by_id[row["element"]]; purchase=row.get("purchase_cost"); source=row.get("source")
  if purchase is None:
   if p["id"] in spells and spells[p["id"]].get("purchase_cost") is not None:purchase=spells[p["id"]]["purchase_cost"];source="entry/transfers"
   elif p["id"] in gw1ids:purchase=p["now_cost"]-p.get("cost_change_start",0);source="gw1_reconstruction"
  ledger.append({"element":p["id"],"name":p["web_name"],"team":teams[p["team"]],"position":pos[p["element_type"]],"purchase_cost":purchase,"now_cost":p["now_cost"],"sell_cost":sell_cost(p["now_cost"],purchase) if purchase is not None else None,"purchase_source":source,"ownership":p.get("selected_by_percent"),"status":p.get("status")})
 adv_summary={}; stats_gw=phase["current_gw"] or phase["last_finished_gw"]
 if sync_stats and stats_gw:
  ci=core_insights.sync_gw(stats_gw); vv=vaastav.sync_gw(stats_gw); adv_summary={"core_insights":{"ok":bool(ci.get("schema_valid")),"rows":ci.get("row_count"),"error":ci.get("error")},"vaastav":{"ok":bool(vv.get("rows")),"rows":vv.get("row_count"),"error":vv.get("error")}}
  if deep_stats:adv_summary["deep"]=core_insights.sync_optional_deep_files(stats_gw)
 live_payload={"generated_at":iso_now(),"status":"IDLE","scoring_gw":scoring_gw,"players":[]}
 if picks and live:
  lb={e["id"]:e for e in live.get("elements",[])}; detail=[];gross=0
  for pk in picks.get("picks",[]):
   p=by_id.get(pk["element"],{}); stats=expanded_live(lb.get(pk["element"],{})); raw=stats.get("total_points",0) or 0; mult=pk.get("multiplier",0); gross+=raw*mult if mult>0 else 0; detail.append({"element":pk["element"],"name":p.get("web_name"),"team":teams.get(p.get("team")),"position":pos.get(p.get("element_type")),"pick_position":pk.get("position"),"multiplier":mult,"captain":pk.get("is_captain"),"vice":pk.get("is_vice_captain"),**stats})
  hit=(picks.get("entry_history") or {}).get("event_transfers_cost",0); live_payload={"generated_at":iso_now(),"status":"PROVISIONAL" if phase["is_live_event"] else "RECONCILED_OR_IDLE","scoring_gw":scoring_gw,"gross_points":gross,"hit":hit,"net_points":gross-hit,"players":detail}
 atomic_json(DATA/"live.json",live_payload)
 prev=read_json(DATA/"price_cache.json",{}).get("players",{});cur={};confirmed=[];momentum=[];total_players=bootstrap.get("total_players",0) or 0
 for p in bootstrap["elements"]:
  cur[str(p["id"])]={"now_cost":p["now_cost"],"ownership":p.get("selected_by_percent")};old=prev.get(str(p["id"]));
  if old and old.get("now_cost")!=p["now_cost"]:confirmed.append({"element":p["id"],"name":p["web_name"],"previous":old["now_cost"],"current":p["now_cost"],"delta":p["now_cost"]-old["now_cost"]})
  own=float(p.get("selected_by_percent") or 0);est=max(1,int(total_players*own/100));net=(p.get("transfers_in_event") or 0)-(p.get("transfers_out_event") or 0);momentum.append({"element":p["id"],"name":p["web_name"],"net_transfers":net,"ownership_pct":own,"momentum":net/est})
 momentum.sort(key=lambda x:x["momentum"],reverse=True);atomic_json(DATA/"price_cache.json",{"generated_at":iso_now(),"players":cur});atomic_json(DATA/"prices.json",{"generated_at":iso_now(),"confirmed_changes":confirmed,"top_buy_pressure":momentum[:25],"top_sell_pressure":list(reversed(momentum[-25:]))})
 universe=[{"element":p["id"],"name":p["web_name"],"team":teams[p["team"]],"team_id":p["team"],"position":pos[p["element_type"]],"element_type":p["element_type"],"now_cost":p["now_cost"],"ownership":p.get("selected_by_percent"),"status":p.get("status"),"points":p.get("total_points"),"minutes":p.get("minutes"),"transfers_in_event":p.get("transfers_in_event"),"transfers_out_event":p.get("transfers_out_event")} for p in bootstrap["elements"]]
 generated=iso_now(); predictions=build_predictions(bootstrap,fixtures or [],generated); atomic_json(DATA/"predictions_v4.json",predictions)
 atomic_json(DATA/"universe.json",{"generated_at":generated,"players":universe});atomic_json(DATA/"health.json",health);atomic_json(DATA/"chips.json",{"generated_at":generated,"used":(history or {}).get("chips",[])});atomic_json(DATA/"team.json",{"generated_at":generated,"team_id":TEAM_ID,"squad_authority":"LOCKED_PRE_DEADLINE" if use_lock else "OFFICIAL_SUBMITTED","squad":squad,"team_value_ledger":ledger,"totals":{"market_value":sum(x["now_cost"] for x in ledger),"sell_value":sum(x["sell_cost"] for x in ledger if x["sell_cost"] is not None),"itb":lock.get("itb_tenths") if use_lock else (entry or {}).get("last_deadline_bank")}})
 snapshot={"schema_version":40,"engine_version":"4.0.0-rc1","generated_at":generated,"mode":mode,"team_id":TEAM_ID,"phase":phase,"endpoint_health":health,"squad_authority":"LOCKED_PRE_DEADLINE" if use_lock else "OFFICIAL_SUBMITTED","advanced_stats_sync":adv_summary,"prediction_summary":{"model":predictions["model_version"],"players":len(predictions["players"]),"top_5gw":predictions["players"][:10]},"team_summary":{"itb":lock.get("itb_tenths") if use_lock else (entry or {}).get("last_deadline_bank"),"market_value":sum(x["now_cost"] for x in ledger),"sell_value":sum(x["sell_cost"] for x in ledger if x["sell_cost"] is not None)},"live_summary":{"status":live_payload["status"],"gross_points":live_payload.get("gross_points"),"net_points":live_payload.get("net_points")},"price_summary":{"confirmed_changes":confirmed,"top_buy_pressure":momentum[:10]},"files":{"team":"data/team.json","live":"data/live.json","prices":"data/prices.json","health":"data/health.json","universe":"data/universe.json","chips":"data/chips.json","predictions":"data/predictions_v4.json"},"meta":{"direct_fpl_api_authority":True,"fail_closed":True,"prediction_point_in_time":True,"advanced_stats_are_community_enrichment":True,"leakage_guard_required_for_predictive_training":True}}
 atomic_json(DATA/"latest.json",snapshot);gw=phase["submitted_gw"] or phase["planning_gw"]
 if gw:atomic_json(DATA/"gw"/f"{gw:02d}.json",snapshot)
 append_jsonl(DATA/"history.jsonl",snapshot);return snapshot

def cli():
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
 for name in ["daily","deadline","live"]:
  p=sub.add_parser(name);p.add_argument("--stats",action="store_true");p.add_argument("--deep-stats",action="store_true")
 p=sub.add_parser("stats-sync");p.add_argument("--gw",type=int,required=True);p.add_argument("--deep",action="store_true");p=sub.add_parser("advanced-stats");p.add_argument("--gw",type=int,required=True);p.add_argument("--query",required=True);args=ap.parse_args()
 if args.cmd in {"daily","deadline","live"}:print(json.dumps(run(args.cmd,args.stats,args.deep_stats),ensure_ascii=False,indent=2))
 elif args.cmd=="stats-sync":
  out={"core_insights":core_insights.sync_gw(args.gw),"vaastav":vaastav.sync_gw(args.gw)}
  if args.deep:out["deep"]=core_insights.sync_optional_deep_files(args.gw)
  print(json.dumps(out,ensure_ascii=False,indent=2))
 else:print(json.dumps(core_insights.query_player(args.gw,args.query),ensure_ascii=False,indent=2))
if __name__=="__main__":cli()
