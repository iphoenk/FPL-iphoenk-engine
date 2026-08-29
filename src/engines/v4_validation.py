from __future__ import annotations
import math
from collections import defaultdict
from statistics import mean
from src.models.v4_calibration import eligible, spearman

POSITIONS={1:'GK',2:'DEF',3:'MID',4:'FWD'}


def _clip_probability(value):return min(.999999,max(.000001,float(value)))
def rmse(rows):return None if not rows else math.sqrt(sum((float(r['actual'])-float(r['predicted']))**2 for r in rows)/len(rows))
def mae(rows):return None if not rows else sum(abs(float(r['actual'])-float(r['predicted'])) for r in rows)/len(rows)
def interval_coverage(rows):
    with_band=[r for r in rows if r.get('lower80') is not None and r.get('upper80') is not None]
    if not with_band:return None
    return sum(float(r['lower80'])<=float(r['actual'])<=float(r['upper80']) for r in with_band)/len(with_band)
def _brier(pairs):return round(mean((float(p)-float(a))**2 for p,a in pairs),4) if pairs else None
def _log_loss(pairs):
    if not pairs:return None
    values=[]
    for p,a in pairs:
        q=_clip_probability(p);values.append(-(float(a)*math.log(q)+(1-float(a))*math.log(1-q)))
    return round(mean(values),4)


def minutes_metrics(rows):
    m=[r for r in rows if r.get('actual_minutes') is not None and r.get('predicted_minutes') is not None]
    if not m:return {'n':0,'mae':None,'start_n':0,'start_missing':0,'start_brier':None,'start_log_loss':None,'dnp_n':0,'dnp_brier':None,'dnp_log_loss':None,'p60_brier':None}
    mmae=mean(abs(float(r['actual_minutes'])-float(r['predicted_minutes'])) for r in m);sb=[];dnp=[];p6=[];start_missing=0
    for r in m:
        actual_started=r.get('actual_started')
        if actual_started is None:start_missing+=1
        elif r.get('start_probability') is not None:sb.append((float(r['start_probability']),1.0 if bool(actual_started) else 0.0))
        actual_dnp=1.0 if float(r['actual_minutes'])==0 else 0.0
        if r.get('dnp_probability') is not None:dnp.append((float(r['dnp_probability']),actual_dnp))
        actual60=1.0 if float(r['actual_minutes'])>=60 else 0.0
        if r.get('p60') is not None:p6.append((float(r['p60']),actual60))
    return {'n':len(m),'mae':round(mmae,4),'start_n':len(sb),'start_missing':start_missing,'start_brier':_brier(sb),'start_log_loss':_log_loss(sb),'dnp_n':len(dnp),'dnp_brier':_brier(dnp),'dnp_log_loss':_log_loss(dnp),'p60_brier':_brier(p6)}


def ranking_metrics(rows,ks=(10,25,50)):
    if not rows:return {}
    actual_sorted=sorted(rows,key=lambda r:float(r['actual']),reverse=True);predicted_sorted=sorted(rows,key=lambda r:float(r['predicted']),reverse=True);out={'spearman':round(spearman(rows),4) if len(rows)>1 else None}
    for k in ks:
        pred={r['element'] for r in predicted_sorted[:k]};actual={r['element'] for r in actual_sorted[:k]};out[f'top{k}_precision']=round(len(pred&actual)/max(1,len(pred)),4);out[f'top{k}_actual_points']=round(sum(float(r['actual']) for r in predicted_sorted[:k]),2)
    return out


def _calibration_bucket(rows):
    if not rows:return None
    predicted=mean(float(x['predicted']) for x in rows);actual=mean(float(x['actual']) for x in rows);bias=predicted-actual;coverage=interval_coverage(rows)
    return {'n':len(rows),'mae':round(mae(rows),4),'rmse':round(rmse(rows),4),'mean_predicted':round(predicted,4),'mean_actual':round(actual,4),'bias':round(bias,4),'drift_abs':round(abs(bias),4),'interval80_coverage':round(coverage,4) if coverage is not None else None,'minutes':minutes_metrics(rows)}


def position_breakdown(rows):
    groups=defaultdict(list)
    for r in rows:groups[r.get('position','UNK')].append(r)
    return {pos:_calibration_bucket(group) for pos,group in groups.items()}


def captaincy_metric(rows):
    if not rows:return None
    best_pred=max(rows,key=lambda r:float(r['predicted']));best_actual=max(rows,key=lambda r:float(r['actual']))
    return {'predicted_captain':best_pred['element'],'predicted_captain_actual':float(best_pred['actual']),'actual_best':best_actual['element'],'actual_best_points':float(best_actual['actual']),'regret':round(float(best_actual['actual'])-float(best_pred['actual']),2)}


def tactical_ablation_metric(rows):
    comparable=[r for r in rows if r.get('predicted_without_tactical') is not None]
    if not comparable:return {'status':'NO_SAFE_SAMPLE','n':0,'mae_with_tactical':None,'mae_without_tactical':None,'lift':None}
    with_mae=mae(comparable);without_rows=[{**r,'predicted':r['predicted_without_tactical']} for r in comparable];without_mae=mae(without_rows)
    return {'status':'PASS','n':len(comparable),'mae_with_tactical':round(with_mae,4),'mae_without_tactical':round(without_mae,4),'lift':round(without_mae-with_mae,4)}


def decision_regret(rows,submitted_state=None):
    submitted=(submitted_state or {}).get('submitted') or {};by_id={int(r['element']):r for r in rows};xi=[int(x) for x in submitted.get('starting_xi') or []];bench=[int(x) for x in submitted.get('bench') or []];captain=submitted.get('captain')
    if not xi:return {'status':'UNAVAILABLE','reason':'official_submitted_state_missing'}
    xi_actual=sum(float((by_id.get(e) or {}).get('actual',0)) for e in xi);best11=sum(sorted((float(r['actual']) for r in rows),reverse=True)[:11]);bench_actual=sum(float((by_id.get(e) or {}).get('actual',0)) for e in bench);captain_actual=float((by_id.get(int(captain or 0)) or {}).get('actual',0));best_cap=max((float((by_id.get(e) or {}).get('actual',0)) for e in xi),default=0)
    return {'status':'PASS','captain_regret':round(best_cap-captain_actual,2),'xi_regret':round(best11-xi_actual,2),'bench_regret':round(bench_actual,2),'transfer_regret_3_5gw':{'status':'PENDING_HORIZON','reason':'requires realized multi-GW outcomes; never reconstructed early'}}


def validate_rows(rows,deadline,submitted_state=None):
    safe=[r for r in rows if eligible(r.get('available_at'),deadline)];rejected=[r for r in rows if r not in safe]
    if not safe:return {'status':'NO_SAFE_SAMPLE','n':0,'leakage_rejected':len(rejected)}
    cov=interval_coverage(safe)
    return {'status':'PASS','n':len(safe),'leakage_rejected':len(rejected),'mae':round(mae(safe),4),'rmse':round(rmse(safe),4),'interval80_coverage':round(cov,4) if cov is not None else None,'ranking':ranking_metrics(safe),'minutes':minutes_metrics(safe),'by_position':position_breakdown(safe),'captaincy':captaincy_metric(safe),'decision_regret':decision_regret(safe,submitted_state),'tactical_ablation':tactical_ablation_metric(safe),'calibration_source':'immutable_predeadline_forecast_vs_post_gw_actuals'}


def reconcile_prediction_snapshot(prediction_snapshot,actual_by_element,event,deadline,submitted_state=None):
    rows=[];generated=prediction_snapshot.get('generated_at')
    for p in prediction_snapshot.get('players',[]):
        fx=next((x for x in p.get('fixtures',[]) if int(x.get('event') or -1)==int(event)),None)
        if not fx:continue
        a=actual_by_element.get(int(p['element']))
        if not a:continue
        xm=fx.get('xmins',{});tactical=float((fx.get('components') or {}).get('tactical_adjustment') or 0)
        rows.append({'element':int(p['element']),'name':p.get('name'),'position':p.get('position'),'predicted':float(fx.get('xpts',0)),'predicted_without_tactical':round(float(fx.get('xpts',0))-tactical,4),'tactical_delta':tactical,'actual':float(a.get('total_points',0)),'lower80':fx.get('lower80'),'upper80':fx.get('upper80'),'predicted_minutes':xm.get('expected_minutes'),'actual_minutes':a.get('minutes'),'actual_started':a.get('started'),'start_probability':xm.get('start_probability'),'dnp_probability':xm.get('dnp_probability'),'p60':xm.get('p60'),'available_at':generated})
    return {'event':event,'deadline':deadline,'prediction_generated_at':generated,'rows':rows,'metrics':validate_rows(rows,deadline,submitted_state)}


def promotion_gate(report,minimum_n=300):
    m=report.get('metrics',report)
    if m.get('status')!='PASS':return {'promote':False,'reason':'validation_not_passed'}
    if m.get('n',0)<minimum_n:return {'promote':False,'reason':'insufficient_sample'}
    if m.get('mae') is None or m['mae']>3.5:return {'promote':False,'reason':'mae_too_high'}
    if m.get('ranking',{}).get('spearman') is None or m['ranking']['spearman']<0.15:return {'promote':False,'reason':'ranking_too_weak'}
    cov=m.get('interval80_coverage')
    if cov is not None and not .65<=cov<=.92:return {'promote':False,'reason':'interval_miscalibrated'}
    return {'promote':True,'reason':'passed'}
