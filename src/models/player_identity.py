from __future__ import annotations
import re

def stable_key(season:str, element:int)->str:
    return f"{season}:{int(element)}"

def norm_name(value:str)->str:
    return re.sub(r"[^a-z0-9]","",(value or "").casefold())

def build_identity_index(elements:list[dict], season:str)->dict:
    by_element={}; by_name={}
    for p in elements:
        row={"key":stable_key(season,p["id"]),"element":p["id"],"team_id":p.get("team"),"web_name":p.get("web_name")}
        by_element[p["id"]]=row
        for name in (p.get("web_name"),p.get("first_name"),p.get("second_name"),f'{p.get("first_name","")} {p.get("second_name","")}'):
            n=norm_name(name)
            if n: by_name.setdefault(n,[]).append(row)
    return {"by_element":by_element,"by_name":by_name}

def resolve_external(row:dict,index:dict,element_field="element",name_field="name"):
    eid=row.get(element_field)
    if eid is not None and int(eid) in index["by_element"]: return {**index["by_element"][int(eid)],"match":"element"}
    candidates=index["by_name"].get(norm_name(row.get(name_field,"")),[])
    if len(candidates)==1: return {**candidates[0],"match":"unique_name_fallback"}
    return None
