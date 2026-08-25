
from __future__ import annotations
from datetime import datetime
from src.utils import parse_dt

FORBIDDEN_SAME_GW_FIELDS = {
    "xP","ep_this","event_points","total_points","bonus","bps"
}

def feature_is_eligible(feature_name:str, available_at:str|None, target_deadline:str|None, source_data_class:str|None):
    if feature_name in FORBIDDEN_SAME_GW_FIELDS and source_data_class in {"post_match_or_post_gw","post_gw"}:
        return False, "post-event field blocked for same-GW pre-deadline prediction"
    av=parse_dt(available_at); dl=parse_dt(target_deadline)
    if av and dl and av > dl:
        return False, "feature became available after target deadline"
    return True, "eligible"

def filter_features(row:dict, available_at:str|None, target_deadline:str|None, source_data_class:str|None):
    clean={}; blocked={}
    for k,v in row.items():
        ok,reason=feature_is_eligible(k,available_at,target_deadline,source_data_class)
        (clean if ok else blocked)[k]=v if ok else {"value":v,"reason":reason}
    return clean, blocked
