from __future__ import annotations
import math
from statistics import mean, pstdev

POS={1:"GK",2:"DEF",3:"MID",4:"FWD"}
GOAL_PTS={1:6,2:6,3:5,4:4}; CS_PTS={1:4,2:4,3:1,4:0}

def clamp(x,a=0.0,b=1.0): return max(a,min(b,x))
def f(v,d=0.0):
    try:return float(v if v is not None else d)
    except:return float(d)

def availability(p):
    if p.get("status") in {"s","u"}: return 0.0
    c=p.get("chance_of_playing_next_round")
    if c is not None:return clamp(f(c)/100)
    return 0.35 if p.get("status")=="i" else 0.75 if p.get("status")=="d" else 1.0

def workload_factor(ctx):
    rest=f(ctx.get("rest_days"),7); cup=f(ctx.get("cup_minutes_last7")); intl=f(ctx.get("international_minutes_last10")); travel=f(ctx.get("travel_km_last10"))
    return clamp(1-0.025*max(0,5-rest)-0.0008*cup-0.00045*intl-0.000015*travel,0.65,1)

def lineup_distribution(p,ctx=None):
    ctx=ctx or {}; av=availability(p); mins=f(p.get("minutes")); starts=f(p.get("starts")); apps=max(starts,math.ceil(mins/90) if mins else 0)
    history=ctx.get("recent_starts",[]); recent=sum(1 for x in history[-5:] if x)/max(1,len(history[-5:])) if history else None
    base=recent if recent is not None else clamp(0.48+0.075*starts+0.0018*mins,0.25,0.96)
    competition=clamp(f(ctx.get("competition_pressure"),0),0,1); manager=clamp(f(ctx.get("manager_rotation_rate"),0.12),0,0.7)
    injury_ramp=clamp(f(ctx.get("injury_return_ramp"),1),0.25,1); work=workload_factor(ctx)
    start=clamp(base*av*(1-0.35*competition)*(1-0.30*manager)*injury_ramp*work)
    bench=clamp((av-start)*(0.72+0.15*competition),0,1-start); dnp=clamp(1-start-bench)
    start_mins=clamp(f(ctx.get("avg_minutes_when_start"), mins/max(1,apps) if mins else 72),45,90); submins=clamp(f(ctx.get("avg_minutes_when_sub"),18),1,35)
    em=start*start_mins+bench*submins
    return {"start_probability":round(start,4),"bench_probability":round(bench,4),"dnp_probability":round(dnp,4),"expected_minutes":round(em,1),"workload_factor":round(work,4)}

def team_strength(team_id,players):
    rows=[p for p in players if p.get("team")==team_id]; xg=sum(f(p.get("expected_goals")) for p in rows); xa=sum(f(p.get("expected_assists")) for p in rows); gc=sum(f(p.get("goals_conceded")) for p in rows)
    return {"attack":round(1+xg+0.55*xa,3),"defence":round(1/(1+gc/max(1,len(rows))),3)}

def fixture_adjustment(fixture,home=True,team_attack=1,opp_defence=0.5):
    diff=f(fixture.get("difficulty"),3); home_factor=1.06 if home else 0.95; matchup=clamp(0.82+0.10*(3-diff)+0.06*(team_attack-1)+0.12*(opp_defence-0.5),0.65,1.35)
    return home_factor*matchup

def rates(p,adv=None):
    a=adv or {}; mins=max(1,f(p.get("minutes"))); xg=f(a.get("xg_per90"),f(p.get("expected_goals"))*90/mins); xa=f(a.get("xa_per90"),f(p.get("expected_assists"))*90/mins)
    return {"xg90":max(0,xg),"xa90":max(0,xa),"saves90":max(0,f(p.get("saves"))*90/mins),"bps90":f(p.get("bps"))*90/mins,"defcon90":f(a.get("defensive_contribution_per90"),f(p.get("defensive_contribution"))*90/mins)}

def project_fixture(p,fixture,ctx=None,adv=None):
    ctx=ctx or {}; d=lineup_distribution(p,ctx); share=d["expected_minutes"]/90; r=rates(p,adv); pos=int(p.get("element_type",3)); adj=fixture_adjustment(fixture,fixture.get("home",True),f(ctx.get("team_attack"),1),f(ctx.get("opponent_defence"),0.5))
    setpiece=1+0.08*f(ctx.get("set_piece_share"))+0.18*f(ctx.get("penalty_share")); attack=(r["xg90"]*GOAL_PTS[pos]+r["xa90"]*3)*share*adj*setpiece
    appearance=d["start_probability"]*(2 if d["expected_minutes"]>=60 else 1)+d["bench_probability"]
    csprob=clamp(0.36+0.075*(3-f(fixture.get("difficulty"),3))+(0.04 if fixture.get("home",True) else -0.02),0.08,0.68); cs=CS_PTS[pos]*csprob*share
    saves=(r["saves90"]/3)*share if pos==1 else 0; defcon=max(0,r["defcon90"])*share; bonus=clamp(r["bps90"]/90,0,1.6)*share
    mu=max(0,appearance+attack+cs+saves+defcon+bonus); sigma=max(0.9,math.sqrt(mu+0.8)*(1.15-d["start_probability"]*0.25))
    return {"event":fixture.get("event"),"xpts":round(mu,3),"lower80":round(max(0,mu-1.282*sigma),3),"upper80":round(mu+1.282*sigma,3),"xmins":d,"components":{"appearance":round(appearance,3),"attack":round(attack,3),"clean_sheet":round(cs,3),"saves":round(saves,3),"defcon":round(defcon,3),"bonus":round(bonus,3)},"provenance":{"model":"v4_prediction_core_1.0","fixture_source":"official_fpl","advanced_source":ctx.get("advanced_source","official_fpl+community"),"point_in_time":ctx.get("point_in_time")}}

def project_horizon(p,fixtures,ctx=None,adv=None,n=15):
    rows=[project_fixture(p,x,ctx,adv) for x in fixtures[:n]]; xs=[x["xpts"] for x in rows]
    return {"element":p.get("id"),"name":p.get("web_name"),"position":POS.get(p.get("element_type")),"fixtures":rows,"xpts_3":round(sum(xs[:3]),2),"xpts_5":round(sum(xs[:5]),2),"xpts_10":round(sum(xs[:10]),2),"xpts_15":round(sum(xs[:15]),2),"mean_xpts":round(mean(xs),3) if xs else 0,"uncertainty":round(pstdev(xs),3) if len(xs)>1 else None,"model":"v4_prediction_core_1.0"}
