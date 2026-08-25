from __future__ import annotations
from pathlib import Path
import json
from src.models.v4_prediction import project_horizon,team_strength
from src.models.player_identity import build_identity_index

def fixture_map(fixtures,team_id,n=15):
 out=[]
 for x in fixtures:
  if x.get("finished") or team_id not in {x.get("team_h"),x.get("team_a")}:continue
  home=x.get("team_h")==team_id
  out.append({"event":x.get("event"),"kickoff_time":x.get("kickoff_time"),"home":home,"opponent":x.get("team_a") if home else x.get("team_h"),"difficulty":x.get("team_h_difficulty") if home else x.get("team_a_difficulty")})
 return out[:n]

def build_predictions(bootstrap,fixtures,generated_at):
 elements=bootstrap.get("elements",[]); strengths={t["id"]:team_strength(t["id"],elements) for t in bootstrap.get("teams",[])}; identity=build_identity_index(elements,"2026-27")
 rows=[]
 for p in elements:
  fx=fixture_map(fixtures,p["team"],15); enriched=[]
  for x in fx:
   opp=strengths.get(x["opponent"],{"defence":0.5}); enriched.append(x)
  ctx={"team_attack":strengths.get(p["team"],{}).get("attack",1),"opponent_defence":0.5,"point_in_time":generated_at,"advanced_source":"official_fpl_current_state"}
  r=project_horizon(p,enriched,ctx,n=15); r["stable_key"]=identity["by_element"][p["id"]]["key"]; rows.append(r)
 rows.sort(key=lambda r:r["xpts_5"],reverse=True)
 return {"schema_version":40,"model_version":"v4_prediction_core_1.0","generated_at":generated_at,"point_in_time":True,"players":rows}
