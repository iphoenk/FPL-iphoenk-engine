from __future__ import annotations
import math

def mae(actual,pred):
    return sum(abs(a-p) for a,p in zip(actual,pred))/max(1,len(actual))

def rank(values):
    order=sorted(range(len(values)),key=lambda i:values[i]); r=[0]*len(values)
    for n,i in enumerate(order): r[i]=n+1
    return r

def spearman(actual,pred):
    if len(actual)<2 or len(actual)!=len(pred): return None
    a=rank(actual); p=rank(pred); n=len(a); d2=sum((x-y)**2 for x,y in zip(a,p))
    return 1-(6*d2)/(n*(n*n-1))

def calibration(actual,pred,bins=5):
    if not actual: return None
    pairs=sorted(zip(pred,actual)); chunks=[pairs[i::bins] for i in range(bins)]
    errs=[]
    for c in chunks:
        if c: errs.append(abs(sum(x for x,_ in c)/len(c)-sum(y for _,y in c)/len(c)))
    return sum(errs)/max(1,len(errs))

def register(name,version,features,training_cutoff,actual=None,pred=None,status="challenger"):
    metrics={}
    if actual is not None and pred is not None:
        metrics={"mae":round(mae(actual,pred),4),"spearman":round(spearman(actual,pred),4) if spearman(actual,pred) is not None else None,"calibration_error":round(calibration(actual,pred),4)}
    return {"name":name,"version":version,"features":features,"training_cutoff":training_cutoff,"status":status,"metrics":metrics}
