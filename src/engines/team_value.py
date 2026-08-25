
from __future__ import annotations

def sell_cost(now_cost:int, purchase_cost:int)->int:
    if now_cost <= purchase_cost:
        return now_cost
    return purchase_cost + ((now_cost-purchase_cost)//2)

def build_transfer_spells(transfers:list[dict]):
    spells={}
    for tr in sorted(transfers,key=lambda x:(x.get("event",0),x.get("time",""))):
        out_id=tr.get("element_out"); in_id=tr.get("element_in")
        if out_id in spells:
            spells.pop(out_id,None)
        if in_id is not None:
            spells[in_id]={
                "purchase_cost":tr.get("element_in_cost"),
                "event":tr.get("event"),"time":tr.get("time"),
                "source":"entry/transfers"
            }
    return spells
