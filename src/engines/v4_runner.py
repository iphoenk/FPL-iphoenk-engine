from __future__ import annotations
from src.models.v4_prediction import project_horizon,team_strength,XG_PRIOR,XA_PRIOR
from src.models.player_identity import build_identity_index

def f(v,d=0.0):
 try:return float(v if v is not None else d)
 except:return float(d)

def fixture_map(fixtures,team_id,n=15):
 out=[]
 for x in fixtures:
  if x.get("finished") or team_id not in {x.get("team_h"),x.get("team_a")}:continue
  home=x.get("team_h")==team_id
  out.append({"event":x.get("event"),"kickoff_time":x.get("kickoff_time"),"home":home,"opponent":x.get("team_a") if home else x.get("team_h"),"difficulty":x.get("team_h_difficulty") if home else x.get("team_a_difficulty")})
 return out[:n]

def player_priors(p):
 pos=int(p.get("element_type",3)); price=f(p.get("now_cost"))/10; ownership=f(p.get("selected_by_percent")); influence=f(p.get("influence")); creativity=f(p.get("creativity")); threat=f(p.get("threat"))
 # Price is used only as a weak proxy for established attacking responsibility, never as a direct points bonus.
 premium=max(0.0,min(1.0,(price-6.0)/9.5)); role=max(0.0,min(1.0,(ownership/35)*0.25+(threat/100)*0.45+(creativity/100)*0.30))
 xg=XG_PRIOR[pos]*(1+0.75*premium+0.35*role); xa=XA_PRIOR[pos]*(1+0.45*premium+0.45*role)
 return {"xg90_prior":xg,"xa90_prior":xa,"premium_prior":premium,"role_prior":role}

def team_defence_prior(team):
 # Official team strength is a safer early-season anchor than one match's goals conceded.
 strength=f(team.get("strength_defence_home"),1000)+f(team.get("strength_defence_away"),1000); strength/=2
 return max(0.18,min(0.48,0.30+(strength-1000)/4000))

def build_predictions(bootstrap,fixtures,generated_at):
 elements=bootstrap.get("elements",[]); teams={t["id"]:t for t in bootstrap.get("teams",[])}; strengths={tid:team_strength(tid,elements) for tid in teams}; identity=build_identity_index(elements,"2026-27")
 rows=[]
 for p in elements:
  fx=fixture_map(fixtures,p["team"],15); pri=player_priors(p); team=teams[p["team"]]; def_prior=team_defence_prior(team)
  ctx={"team_attack":strengths.get(p["team"],{}).get("attack",1),"opponent_defence":0.5,"team_cs_prior":def_prior,"point_in_time":generated_at,"advanced_source":"official_fpl_current_state","xg90_prior":pri["xg90_prior"],"xa90_prior":pri["xa90_prior"],"premium_prior":pri["premium_prior"],"role_prior":pri["role_prior"]}
  r=project_horizon(p,fx,ctx,n=15); r["stable_key"]=identity["by_element"][p["id"]]["key"]; r["priors"]={k:round(v,4) for k,v in pri.items()}; rows.append(r)
 rows.sort(key=lambda r:r["xpts_5"],reverse=True)
 return {"schema_version":41,"model_version":"v4.1-positional-calibration","generated_at":generated_at,"point_in_time":True,"players":rows}
