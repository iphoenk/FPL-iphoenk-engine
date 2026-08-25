
from __future__ import annotations
import math

def mae(pred, actual):
    xs=[abs(float(a)-float(b)) for a,b in zip(pred,actual)]
    return sum(xs)/len(xs) if xs else None

def brier(probabilities, outcomes):
    xs=[(float(p)-float(o))**2 for p,o in zip(probabilities,outcomes)]
    return sum(xs)/len(xs) if xs else None

def spearman_rank(xs,ys):
    if len(xs)!=len(ys) or len(xs)<2: return None
    def ranks(v):
        order=sorted(range(len(v)),key=lambda i:v[i])
        r=[0]*len(v)
        for rank,i in enumerate(order): r[i]=rank+1
        return r
    rx,ry=ranks(xs),ranks(ys)
    n=len(xs)
    d2=sum((a-b)**2 for a,b in zip(rx,ry))
    return 1-(6*d2)/(n*(n*n-1))
