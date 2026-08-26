from __future__ import annotations
from typing import Any
from src.v5.config_cache import load_json_config
from src.v5.service_client import invoke_envelope, invoke_parallel_envelopes
from src.v5.services.orchestrator import handle as core_handle

CONFIG="config/v5_orchestrator_registry.json"

def _route(name:str)->tuple[str,str]:
    row=(load_json_config(CONFIG).get("routing") or {}).get(name)
    if not isinstance(row,dict):raise KeyError(name)
    return str(row["service"]),str(row["operation"])

def _invoke(name:str,payload:dict[str,Any],cid:str)->dict[str,Any]:
    service,operation=_route(name); return invoke_envelope(service,operation,payload,correlation_id=cid)

def handle(operation:str,payload:dict[str,Any])->Any:
    if operation!="run":return core_handle(operation,payload)
    run_payload={**payload,"persist":True}
    snapshot=core_handle("run",run_payload)
    cid=str(snapshot.get("correlation_id") or payload.get("correlation_id") or "")
    read_service,read_operation=_route("artifact_read")
    states=invoke_parallel_envelopes({"prediction":(read_service,read_operation,{"name":"predictions","default":{}}),"report_state":(read_service,read_operation,{"name":"report_state","default":{}})},correlation_id=cid)
    prediction=states["prediction"]["data"] or {}
    truth={"team":snapshot.get("team_summary") or {},"context":snapshot.get("phase") or {}}
    price={"alerts":{"alerts":((snapshot.get("price_summary") or {}).get("alerts") or [])}}
    decision=snapshot.get("decision_summary") or {}
    governance=snapshot.get("framework_health") or {}
    watch_env=_invoke("watchlist_build",{"truth":truth,"price":price,"prediction":prediction,"dss":decision.get("dss") or {}},cid); watchlist=watch_env["data"]
    report_payload={"truth":truth,"price":price,"prediction":prediction,"decision":decision,"governance":governance,"watchlist":watchlist,"previous_report_state":states["report_state"]["data"] or {},"performance":snapshot.get("service_performance") or {},"force_full_report":bool(payload.get("force_full_report",False)),"report_request":payload.get("report_request") if isinstance(payload.get("report_request"),dict) else {}}
    report_env=_invoke("reporting_build",report_payload,cid); report=report_env["data"]
    write_service,write_operation=_route("artifact_write"); mapping=load_json_config(CONFIG).get("artifact_mapping") or {}
    writes=invoke_parallel_envelopes({"watchlist":(write_service,write_operation,{"name":mapping["watchlist"],"data":watchlist}),"user_report":(write_service,write_operation,{"name":mapping["user_report"],"data":report["user_report"]}),"technical_appendix":(write_service,write_operation,{"name":mapping["technical_appendix"],"data":report["technical_appendix"]}),"report_state":(write_service,write_operation,{"name":mapping["report_state"],"data":report["report_state"]})},correlation_id=cid)
    snapshot["watchlist_summary"]={"status":watchlist.get("status"),"candidate_count":watchlist.get("candidate_count"),"screening_contract":watchlist.get("screening_contract")}
    snapshot["user_report"]=report["user_report"]
    snapshot["technical_appendix"]=report["technical_appendix"]
    snapshot["report_state"]=report["report_state"]
    snapshot.setdefault("service_performance",{})["beta_composition"]={"watchlist":{"service_compute_ms":watch_env.get("elapsed_ms"),"round_trip_ms":watch_env.get("round_trip_ms")},"reporting":{"service_compute_ms":report_env.get("elapsed_ms"),"round_trip_ms":report_env.get("round_trip_ms")},"persistence":{k:{"service_compute_ms":v.get("elapsed_ms"),"round_trip_ms":v.get("round_trip_ms")} for k,v in writes.items()}}
    return snapshot
