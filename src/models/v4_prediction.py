from __future__ import annotations
import math
from statistics import mean, pstdev
POS={1:"GK",2:"DEF",3:"MID",4:"FWD"}; GOAL_PTS={1:6,2:6,3:5,4:4}; CS_PTS={1:4,2:4,3:1,4:0}; XG_PRIOR={1:0.01,2:0.06,3:0.18,4:0.30}; XA_PRIOR={1:0.005,2:0.08,3:0.16,4:0.11}; DEF_ACTION_PRIOR={1:1.0,2:7.0,3:6.0,4:3.0}
def clamp(x,a=0.,b=1.):return max(a,min(b,x))
def f(v,d=0.):
 try:return float(v if v is not None else d)
 except:return float(d)
def availability(p):
 if p.get('status') in {'s','u'}:return 0.
 c=p.get('chance_of_playing_next_round')
 if c is not None:return clamp(f(c)/100)
 return .35 if p.get('status')=='i' else .75 if p.get('status')=='d' else 1.
def workload_factor(ctx):return clamp(1-.025*max(0,5-f(ctx.get('rest_days'),7))-.0008*f(ctx.get('cup_minutes_last7'))-.00045*f(ctx.get('international_minutes_last10'))-.000015*f(ctx.get('travel_km_last10')), .65,1)
def lineup_distribution(p,ctx=None):
 ctx=ctx or {};av=availability(p);mins=f(p.get('minutes'));starts=f(p.get('starts'));apps=max(starts,math.ceil(mins/90) if mins else 0);hist=ctx.get('recent_starts',[]);recent=sum(bool(x) for x in hist[-5:])/max(1,len(hist[-5:])) if hist else None;base=recent if recent is not None else clamp(.48+.075*starts+.0018*mins,.25,.96);comp=clamp(f(ctx.get('competition_pressure')),0,1);rot=clamp(f(ctx.get('manager_rotation_rate'),.12),0,.7);start=clamp(base*av*(1-.35*comp)*(1-.30*rot)*clamp(f(ctx.get('injury_return_ramp'),1),.25,1)*workload_factor(ctx));bench=clamp((av-start)*(.72+.15*comp),0,1-start);dnp=clamp(1-start-bench);sm=clamp(f(ctx.get('avg_minutes_when_start'),mins/max(1,apps) if mins else 72),45,90);sub=clamp(f(ctx.get('avg_minutes_when_sub'),18),1,35);em=start*sm+bench*sub;p60=start*clamp((sm-50)/18,0,1)
 return {'start_probability':round(start,4),'bench_probability':round(bench,4),'dnp_probability':round(dnp,4),'expected_minutes':round(em,1),'p60':round(p60,4),'workload_factor':round(workload_factor(ctx),4)}
def team_strength(team_id,players):
 rows=[p for p in players if p.get('team')==team_id];xg=sum(f(p.get('expected_goals')) for p in rows);xa=sum(f(p.get('expected_assists')) for p in rows);gc=sum(f(p.get('goals_conceded')) for p in rows);return {'attack':round(1+xg+.55*xa,3),'defence':round(1/(1+gc/max(1,len(rows))),3)}
def fixture_adjustment(fixture,home=True,team_attack=1,opp_defence=.5):return (1.06 if home else .95)*clamp(.82+.10*(3-f(fixture.get('difficulty'),3))+.04*(team_attack-1)+.08*(opp_defence-.5),.72,1.28)
def shrink_rate(obs,mins,prior,prior_minutes=720):
 m=max(0,f(mins));w=m/(m+max(90,f(prior_minutes,720)));return prior*(1-w)+max(0,f(obs))*w,w
def rates(p,adv=None,ctx=None):
 a=adv or {};ctx=ctx or {};mins=max(1,f(p.get('minutes')));pos=int(p.get('element_type',3));rxg=f(a.get('xg_per90'),f(p.get('expected_goals'))*90/mins);rxa=f(a.get('xa_per90'),f(p.get('expected_assists'))*90/mins);xg,w=shrink_rate(rxg,mins,f(ctx.get('xg90_prior'),XG_PRIOR[pos]),f(ctx.get('attacking_prior_minutes'),720));xa,_=shrink_rate(rxa,mins,f(ctx.get('xa90_prior'),XA_PRIOR[pos]),f(ctx.get('attacking_prior_minutes'),720));raw_da=max(0,f(a.get('defensive_contribution_per90'),f(p.get('defensive_contribution'))*90/mins));da,dw=shrink_rate(raw_da,mins,f(ctx.get('def_actions90_prior'),DEF_ACTION_PRIOR[pos]),f(ctx.get('defcon_prior_minutes'),720));return {'xg90':xg,'xa90':xa,'raw_xg90':max(0,rxg),'raw_xa90':max(0,rxa),'current_season_weight':w,'saves90':max(0,f(p.get('saves'))*90/mins),'bps90':f(p.get('bps'))*90/mins,'def_actions90':da,'raw_def_actions90':raw_da,'defcon_weight':dw}
def defcon_expected_points(actions90,em,pos,p60=1.0):
 if em<1:return 0.
 th=10. if pos in {1,2} else 12.;ea=max(0,actions90)*em/90;prob=1/(1+math.exp(-(ea-th)/max(2.2,th*.22)));return 2*prob*clamp(p60,0,1)
def clean_sheet_probability(fixture,ctx):
 prior=clamp(f(ctx.get('team_cs_prior'),.30),.15,.50);diff=f(fixture.get('difficulty'),3);home=.025 if fixture.get('home',True) else -.02;return clamp(prior+.045*(3-diff)+home,.08,.55)
def bonus_expected(r,share,mins):
 w=max(0,min(1,mins/(mins+900)));observed=clamp(r['bps90']/30,0,3);return ((1-w)*.15+w*observed)*share
def project_fixture(p,fixture,ctx=None,adv=None):
 ctx=ctx or {};d=lineup_distribution(p,ctx);share=d['expected_minutes']/90;r=rates(p,adv,ctx);pos=int(p.get('element_type',3));adj=fixture_adjustment(fixture,fixture.get('home',True),f(ctx.get('team_attack'),1),f(ctx.get('opponent_defence'),.5));setpiece=1+.08*f(ctx.get('set_piece_share'))+.18*f(ctx.get('penalty_share'));attack=(r['xg90']*GOAL_PTS[pos]+r['xa90']*3)*share*adj*setpiece;appearance=d['start_probability']*(1+d['p60'])+d['bench_probability'];csprob=clean_sheet_probability(fixture,ctx);cs=CS_PTS[pos]*csprob*d['p60'];saves=(r['saves90']/3)*share if pos==1 else 0;defcon=defcon_expected_points(r['def_actions90'],d['expected_minutes'],pos,d['p60']);bonus=bonus_expected(r,share,f(p.get('minutes')));mu=max(0,appearance+attack+cs+saves+defcon+bonus);sigma=max(.9,math.sqrt(mu+.8)*(1.15-d['start_probability']*.25))
 return {'event':fixture.get('event'),'xpts':round(mu,3),'lower80':round(max(0,mu-1.282*sigma),3),'upper80':round(mu+1.282*sigma,3),'xmins':d,'components':{'appearance':round(appearance,3),'attack':round(attack,3),'clean_sheet':round(cs,3),'saves':round(saves,3),'defcon':round(defcon,3),'bonus':round(bonus,3)},'rates':{'xg90':round(r['xg90'],4),'xa90':round(r['xa90'],4),'raw_xg90':round(r['raw_xg90'],4),'raw_xa90':round(r['raw_xa90'],4),'current_season_weight':round(r['current_season_weight'],4),'def_actions90':round(r['def_actions90'],4),'raw_def_actions90':round(r['raw_def_actions90'],4),'defcon_weight':round(r['defcon_weight'],4)},'calibration':{'clean_sheet_probability':round(csprob,4),'premium_prior':round(f(ctx.get('premium_prior')),4),'role_prior':round(f(ctx.get('role_prior')),4)},'provenance':{'model':'v4.2-defence-calibration','fixture_source':'official_fpl','advanced_source':ctx.get('advanced_source','official_fpl+community'),'point_in_time':ctx.get('point_in_time'),'attacking_rate_shrinkage':True,'defcon_rate_shrinkage':True,'cs_prior_calibration':True,'p60_scoring_gate':True,'bonus_regression':True}}
def project_horizon(p,fixtures,ctx=None,adv=None,n=15):
 rows=[project_fixture(p,x,ctx,adv) for x in fixtures[:n]];xs=[x['xpts'] for x in rows];return {'element':p.get('id'),'name':p.get('web_name'),'position':POS.get(p.get('element_type')),'fixtures':rows,'xpts_3':round(sum(xs[:3]),2),'xpts_5':round(sum(xs[:5]),2),'xpts_10':round(sum(xs[:10]),2),'xpts_15':round(sum(xs[:15]),2),'mean_xpts':round(mean(xs),3) if xs else 0,'uncertainty':round(pstdev(xs),3) if len(xs)>1 else None,'model':'v4.2-defence-calibration'}
