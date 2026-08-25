from src.engines.v4_validation import validate_rows,reconcile_prediction_snapshot,promotion_gate

def rows(n=20):
    out=[]
    for i in range(n):
        out.append({'element':i,'position':'MID' if i%2 else 'DEF','predicted':float(i%7),'actual':float((i+1)%7),'lower80':0,'upper80':10,'predicted_minutes':70,'actual_minutes':90 if i%3 else 20,'start_probability':.8,'p60':.7,'available_at':'2026-08-20T10:00:00Z'})
    return out

def test_validation_metrics_exist():
    r=validate_rows(rows(), '2026-08-20T11:00:00Z')
    assert r['status']=='PASS' and r['n']==20
    assert r['mae'] is not None and r['rmse'] is not None
    assert 'top10_precision' in r['ranking'] and r['minutes']['mae'] is not None

def test_leakage_is_rejected():
    x=rows(3);x[0]['available_at']='2026-08-20T12:00:00Z'
    r=validate_rows(x,'2026-08-20T11:00:00Z')
    assert r['n']==2 and r['leakage_rejected']==1

def test_reconcile_snapshot():
    snap={'generated_at':'2026-08-20T10:00:00Z','players':[{'element':1,'name':'A','position':'MID','fixtures':[{'event':2,'xpts':5,'lower80':1,'upper80':9,'xmins':{'expected_minutes':80,'start_probability':.9,'p60':.8}}]}]}
    actual={1:{'total_points':7,'minutes':90,'started':True}}
    r=reconcile_prediction_snapshot(snap,actual,2,'2026-08-20T11:00:00Z')
    assert r['metrics']['n']==1 and r['rows'][0]['actual']==7

def test_promotion_requires_sample_and_quality():
    assert not promotion_gate({'status':'PASS','n':20,'mae':1,'ranking':{'spearman':.5},'interval80_coverage':.8})['promote']
    good={'status':'PASS','n':400,'mae':2.5,'ranking':{'spearman':.3},'interval80_coverage':.8}
    assert promotion_gate(good)['promote']
