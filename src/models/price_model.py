from __future__ import annotations
import math

def sigmoid(x): return 1/(1+math.exp(-max(-20,min(20,x))))

def price_pressure(player:dict,total_players:int,history:dict|None=None)->dict:
    own=float(player.get("selected_by_percent") or 0); owners=max(1,total_players*own/100)
    net=(player.get("transfers_in_event") or 0)-(player.get("transfers_out_event") or 0)
    ratio=net/owners
    hist=history or {}; threshold=float(hist.get("estimated_threshold_ratio") or 0.12)
    scale=max(0.025,float(hist.get("scale") or 0.045))
    rise=sigmoid((ratio-threshold)/scale); fall=sigmoid((-ratio-threshold)/scale)
    confidence="LOW" if not history else "MEDIUM"
    return {"net_transfers":net,"ownership_pct":own,"pressure_ratio":round(ratio,6),"rise_probability":round(rise,4),"fall_probability":round(fall,4),"confidence":confidence,"model":"empirical_pressure_v1","note":"probability is model estimate, not an official FPL threshold"}
