from __future__ import annotations
from datetime import datetime

def dt(x): return datetime.fromisoformat(x.replace("Z","+00:00"))
def eligible(available_at,deadline):
    try:return dt(available_at)<=dt(deadline)
    except:return False

def mae(rows): return sum(abs(float(r["actual"])-float(r["predicted"])) for r in rows)/max(1,len(rows))
def rank(v):
    order=sorted(range(len(v)),key=lambda i:v[i]); out=[0]*len(v)
    for n,i in enumerate(order):out[i]=n+1
    return out
def spearman(rows):
    if len(rows)<2:return None
    a=rank([float(x["actual"]) for x in rows]); p=rank([float(x["predicted"]) for x in rows]); n=len(a); return 1-6*sum((x-y)**2 for x,y in zip(a,p))/(n*(n*n-1))
def calibration_error(rows,bins=5):
    if not rows:return None
    s=sorted(rows,key=lambda r:float(r["predicted"])); groups=[s[i::bins] for i in range(bins)]; e=[]
    for g in groups:
        if g:e.append(abs(sum(float(x["predicted"]) for x in g)/len(g)-sum(float(x["actual"]) for x in g)/len(g)))
    return sum(e)/len(e)
def backtest(rows,deadline):
    safe=[r for r in rows if eligible(r.get("available_at"),deadline)]
    rejected=len(rows)-len(safe)
    return {"n":len(safe),"leakage_rejected":rejected,"mae":round(mae(safe),4) if safe else None,"spearman":round(spearman(safe),4) if len(safe)>1 else None,"calibration_error":round(calibration_error(safe),4) if safe else None}
def champion_gate(champion,challenger,min_n=100):
    if challenger.get("n",0)<min_n:return {"promote":False,"reason":"insufficient_sample"}
    if champion.get("mae") is None:return {"promote":True,"reason":"no_existing_champion"}
    better_mae=challenger["mae"]<=champion["mae"]*0.99; rank_ok=(challenger.get("spearman") or -1)>=(champion.get("spearman") or -1); cal_ok=(challenger.get("calibration_error") or 999)<=(champion.get("calibration_error") or 999)*1.05
    return {"promote":bool(better_mae and rank_ok and cal_ok),"reason":"passed" if better_mae and rank_ok and cal_ok else "metrics_not_better"}
