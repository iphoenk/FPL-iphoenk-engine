from __future__ import annotations

from typing import Any

from src.v5.decision.decision_trace import build_trace
from src.v5.decision.tactical_consumption import apply_lineup_overlay
from src.v5.services.decision import handle as core_handle


def _rebuild_trace(result:dict[str,Any],payload:dict[str,Any])->dict[str,Any]:
    truth=payload.get("truth") if isinstance(payload.get("truth"),dict) else {}; prediction=payload.get("prediction") if isinstance(payload.get("prediction"),dict) else {}; price=payload.get("price") if isinstance(payload.get("price"),dict) else {}; lineup=result.get("lineup") if isinstance(result.get("lineup"),dict) else {}; package_governance=result.get("package_governance") if isinstance(result.get("package_governance"),dict) else {}; dss=result.get("dss") if isinstance(result.get("dss"),dict) else {}; gate0=payload.get("gate0_preflight") if isinstance(payload.get("gate0_preflight"),dict) else {}
    if not truth or not prediction or lineup.get("status")!="READY" or not isinstance(result.get("packages"),list): return result.get("decision_trace") or {}
    packages={"status":"READY","model":result.get("package_model"),"hold":result.get("hold"),"packages":result.get("packages") or [],"candidate_pool":result.get("candidate_pool") or {},"local_legality_prevalidated":result.get("local_legality_prevalidated")}
    return build_trace(truth=truth,prediction=prediction,price=price,packages=packages,package_governance=package_governance,lineup=lineup,dss=dss,gate0_preflight=gate0)


def handle(operation:str,payload:dict[str,Any])->Any:
    result=core_handle(operation,payload)
    if operation=="status" and isinstance(result,dict):
        return {**result,"capabilities":sorted({*(result.get("capabilities") or []),"tactical_decision_consumption"}),"tactical_consumption_contract":"TACTICAL_DECISION_CONSUMPTION_V1"}
    if operation not in {"prepare","finalize","build"} or not isinstance(result,dict): return result
    prediction=payload.get("prediction") if isinstance(payload.get("prediction"),dict) else {}
    if not prediction: return result
    lineup=result.get("lineup") if isinstance(result.get("lineup"),dict) else {}
    overlaid=apply_lineup_overlay(lineup,prediction)
    result={**result,"lineup":overlaid}
    if isinstance(result.get("capabilities"),list): result["capabilities"]=sorted({*(result.get("capabilities") or []),"tactical_decision_consumption"})
    result["governance"]={**(result.get("governance") or {}),"tactical_consumption_contract":"TACTICAL_DECISION_CONSUMPTION_V1","tactical_close_call_only":True,"tactical_direct_xpts_mutation":False}
    if operation in {"finalize","build"}: result["decision_trace"]=_rebuild_trace(result,payload)
    return result
