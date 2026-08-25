from __future__ import annotations

MIN_OWNERSHIP_PCT=0.5
MIN_ABS_NET=5000


def classify(net_transfers:int, ownership_pct:float, estimated_owners:int)->dict:
    ratio=net_transfers/max(estimated_owners,1)
    actionable=ownership_pct>=MIN_OWNERSHIP_PCT and abs(net_transfers)>=MIN_ABS_NET
    confidence="HIGH" if actionable and abs(net_transfers)>=25000 else "MEDIUM" if actionable else "NOISE"
    return {"momentum":ratio,"actionable":actionable,"confidence":confidence,
            "market_noise":not actionable,"min_ownership_pct":MIN_OWNERSHIP_PCT,"min_abs_net":MIN_ABS_NET}
