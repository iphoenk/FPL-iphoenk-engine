from __future__ import annotations
import math
from collections import defaultdict
from statistics import mean
from src.models.v4_calibration import eligible, spearman

POSITIONS={1:'GK',2:'DEF',3:'MID',4:'FWD'}

def rmse(rows):
    if not rows:return None
    return math.sqrt(sum((float(r['actual'])-float(r['predicted']))**2 for r in rows)/len(rows))

def mae(rows):
    if not rows:return None
    return sum(abs(float(r['actual'])-float(r['predicted'])) for r in rows)/len(rows)

def interval_coverage(rows):
    with_band=[r for r in rows if r.get('lower80') is not None and r.get('upper80') is not None]
    if not with_band:return None
    hit=sum(float(r['lower80'])<=float(r['actual'])<=float(r['upper80']) for r in with_band)
    return hit/len(with_band)

def minutes_metrics(rows):
    m=[r for r in rows if r.get('actual_minutes') is not None and r.get('predicted_minutes') is not None]
    if not m:return {'n':0,'mae':None,'start_brier':None,'p60_brier':None}
    mmae=mean(abs(float(r['actual_minutes'])-float(r['predicted_minutes'])) for r in m)
    sb=[];p6=[]
    for r in m:
        actual_start=1.0 if float(r['actual_minutes'])>0 and r.get('actual_started',float(r['actual_minutes'])>=45) else 0.0
        if r.get('start_probability') is not None:sb.append((float(r['start_probability'])-actual_start)**2)
        actual60=1.0 if float(r['actual_minutes'])>=60 else 0.0
        if r.get('p60') is not None:p6.append((float(r['p60'])-actual60)**2)
    return {'n':len(m),'mae':round(mmae,4),'start_brier':round(mean(sb),4) if sb else None,'p60_brier':round(mean(p6),4) if p6 else None}

def ranking_metrics(rows,ks=(10,25,50)):
    if not rows:return {}
    actual_sorted=sorted(rows,key=lambda r:float(r['actual']),reverse=True)
    predicted_sorted=sorted(rows,key=lambda r:float(r['predicted']),reverse=True)
    out={'spearman':round(spearman(rows),4) if len(rows)>1 else None}
    actual_ids=[r['element'] for r in actual_sorted]
    for k in ks:
        pred={r['element'] for r in predicted_sorted[:k]}; actual={r['element'] for r in actual_sorted[:k]}
        out[f'top{k}_precision']=round(len(pred&actual)/max(1,len(pred)),4)
        out[f'top{k}_actual_points']=round(sum(float(r['actual']) for r in predicted_sorted[:k]),2)
    return out

def position_breakdown(rows):
    groups=defaultdict(list)
    for r in rows:groups[r.get('position','UNK')].append(r)
    out={}
    for pos,g in groups.items():
        out[pos]={'n':len(g),'mae':round(mae(g),4),'rmse':round(rmse(g),4),'mean_predicted':round(mean(float(x['predicted']) for x in g),4),'mean_actual':round(mean(float(x['actual']) for x in g),4)}
    return out

def captaincy_metric(rows):
    if not rows:return None
    best_pred=max(rows,key=lambda r:float(r['predicted'])); best_actual=max(rows,key=lambda r:float(r['actual']))
    return {'predicted_captain':best_pred['element'],'predicted_captain_actual':float(best_pred['actual']),'actual_best':best_actual['element'],'actual_best_points':float(best_actual['actual']),'regret':round(float(best_actual['actual'])-float(best_pred['actual']),2)}

def validate_rows(rows,deadline):
    safe=[r for r in rows if eligible(r.get('available_at'),deadline)]
    rejected=[r for r in rows if r not in safe]
    if not safe:return {'status':'NO_SAFE_SAMPLE','n':0,'leakage_rejected':len(rejected)}
    return {'status':'PASS','n':len(safe),'leakage_rejected':len(rejected),'mae':round(mae(safe),4),'rmse':round(rmse(safe),4),'interval80_coverage':round(interval_coverage(safe),4) if interval_coverage(safe) is not None else None,'ranking':ranking_metrics(safe),'minutes':minutes_metrics(safe),'by_position':position_breakdown(safe),'captaincy':captaincy_metric(safe)}

def reconcile_prediction_snapshot(prediction_snapshot,actual_by_element,event,deadline):
    rows=[]
    generated=prediction_snapshot.get('generated_at')
    for p in prediction_snapshot.get('players',[]):
        fx=next((x for x in p.get('fixtures',[]) if int(x.get('event') or -1)==int(event)),None)
        if not fx:continue
        a=actual_by_element.get(int(p['element']))
        if not a:continue
        xm=fx.get('xmins',{})
        rows.append({'element':int(p['element']),'name':p.get('name'),'position':p.get('position'),'predicted':float(fx.get('xpts',0)),'actual':float(a.get('total_points',0)),'lower80':fx.get('lower80'),'upper80':fx.get('upper80'),'predicted_minutes':xm.get('expected_minutes'),'actual_minutes':a.get('minutes'),'actual_started':a.get('started'),'start_probability':xm.get('start_probability'),'p60':xm.get('p60'),'available_at':generated})
    return {'event':event,'deadline':deadline,'prediction_generated_at':generated,'rows':rows,'metrics':validate_rows(rows,deadline)}

def promotion_gate(report,minimum_n=300):
    m=report.get('metrics',report)
    if m.get('status')!='PASS':return {'promote':False,'reason':'validation_not_passed'}
    if m.get('n',0)<minimum_n:return {'promote':False,'reason':'insufficient_sample'}
    if m.get('mae') is None or m['mae']>3.5:return {'promote':False,'reason':'mae_too_high'}
    if m.get('ranking',{}).get('spearman') is None or m['ranking']['spearman']<0.15:return {'promote':False,'reason':'ranking_too_weak'}
    cov=m.get('interval80_coverage')
    if cov is not None and not .65<=cov<=.92:return {'promote':False,'reason':'interval_miscalibrated'}
    return {'promote':True,'reason':'passed'}
