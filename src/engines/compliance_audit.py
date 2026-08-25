from __future__ import annotations
import json
from pathlib import Path
from src.engines.fpl_rules_2026 import SCORING, DEFCON, CHIPS, MAX_CHIPS_PER_GW, FIRST_HALF_LAST_GW, SECOND_HALF_FIRST_GW, chip_allowed, chip_half, positional_defcon_actions
from src.models.v4_prediction import defcon_expected_points, project_horizon

EXPECTED_SCORING={
 'goal_points':{'GK':10,'DEF':6,'MID':5,'FWD':4},'assist':3,'clean_sheet':{'GK':4,'DEF':4,'MID':1,'FWD':0},
 'appearance_under_60':1,'appearance_60_plus':2,'saves_per_point':3,'penalty_save':5,'bonus':[1,2,3],
 'yellow_card':-1,'red_card':-3,'own_goal':-2,'penalty_miss':-2,'goals_conceded_per_minus_point':2,'defcon_points':2,
}

def check(name, condition, detail=''):
 return {'name':name,'pass':bool(condition),'detail':detail}

def run_audit():
 checks=[]
 checks.append(check('scoring_single_source',SCORING==EXPECTED_SCORING,str(SCORING)))
 checks.append(check('defcon_gk_veto',DEFCON['GK']['eligible'] is False and defcon_expected_points(99,90,1,1)==0.0))
 checks.append(check('defcon_def_cbit_10',DEFCON['DEF']=={'eligible':True,'threshold':10,'metric':'CBIT'}))
 checks.append(check('defcon_mid_cbirt_12',DEFCON['MID']=={'eligible':True,'threshold':12,'metric':'CBIRT'}))
 checks.append(check('defcon_fwd_cbirt_12',DEFCON['FWD']=={'eligible':True,'threshold':12,'metric':'CBIRT'}))
 checks.append(check('recoveries_excluded_for_def',positional_defcon_actions('DEF',1,1,1,1,10)==4))
 checks.append(check('recoveries_included_mid_fwd',positional_defcon_actions('MID',1,1,1,1,10)==14 and positional_defcon_actions('FWD',1,1,1,1,10)==14))
 checks.append(check('defcon_reward_capped_two',0<=defcon_expected_points(99,90,2,1)<=2 and 0<=defcon_expected_points(99,90,3,1)<=2))
 checks.append(check('chip_halves',FIRST_HALF_LAST_GW==19 and SECOND_HALF_FIRST_GW==20 and chip_half(19)==1 and chip_half(20)==2))
 checks.append(check('one_chip_per_gw_constant',MAX_CHIPS_PER_GW==1))
 checks.append(check('free_hit_not_gw1',chip_allowed('free_hit',1,[])[0] is False))
 used=[{'chip':'free_hit','gw':19}]
 checks.append(check('free_hit_not_consecutive',chip_allowed('free_hit',20,used)[0] is False))
 checks.append(check('chip_once_per_half',chip_allowed('wildcard',10,[{'chip':'wildcard','gw':5}])[0] is False and chip_allowed('wildcard',20,[{'chip':'wildcard','gw':5}])[0] is True))
 checks.append(check('wc_fh_preserve_banked_ft',CHIPS['wildcard']['preserve_banked_ft'] is True and CHIPS['free_hit']['preserve_banked_ft'] is True))
 # DGW compliance: each fixture is scored independently, so the route can award up to 2 points in each match.
 p={'id':999,'web_name':'Audit DEF','status':'a','minutes':900,'starts':10,'element_type':2,'expected_goals':'0','expected_assists':'0','bps':0,'defensive_contribution':100}
 fx=[{'event':30,'difficulty':3,'home':True},{'event':30,'difficulty':3,'home':False}]
 r=project_horizon(p,fx,{'recent_starts':[1,1,1,1,1],'def_actions90_prior':20},n=2)
 dc=[x['components']['defcon'] for x in r['fixtures']]
 checks.append(check('dgw_defcon_per_match',len(dc)==2 and all(0<=x<=2.001 for x in dc),str(dc)))
 passed=all(x['pass'] for x in checks)
 return {'audit_version':'4.3.1','ruleset':'FPL-2026-27','overall':'PASS' if passed else 'FAIL','checks':checks}

def main(path='data/compliance_audit.json'):
 out=run_audit(); Path(path).parent.mkdir(parents=True,exist_ok=True); Path(path).write_text(json.dumps(out,indent=2),encoding='utf-8')
 for x in out['checks']: print(('PASS' if x['pass'] else 'FAIL'),x['name'],x['detail'])
 print('OVERALL',out['overall'])
 if out['overall']!='PASS': raise SystemExit(2)

if __name__=='__main__': main()
