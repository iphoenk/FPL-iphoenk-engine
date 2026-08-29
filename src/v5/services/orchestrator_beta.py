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
    live_summary=snapshot.get("live_summary") if isinstance(snapshot.get("live_summary"),dict) else {}
    embedded_match_state=live_summary.get("match_state") if isinstance(live_summary.get("match_state"),dict) else {}
    truth={"team":snapshot.get("team_summary") or {},"context":snapshot.get("phase") or {},"live":live_summary,"match_state":snapshot.get("match_state") if isinstance(snapshot.get("match_state"),dict) else embedded_match_state}
    price={"alerts":{"alerts":((snapshot.get("price_summary") or {}).get("alerts") or [])}}
    decision=snapshot.get("decision_summary") or {}
    governance=snapshot.get("framework_health") or {}
    match_state=truth.get("match_state") if isinstance(truth.get("match_state"),dict) else {}
    schedule_env=_invoke("schedule_resolve",{
        "context":truth["context"],
        "now":payload.get("now"),
        "official_deadline_time":payload.get("official_deadline_time"),
        "live_match_active":bool(payload.get("live_match_active",match_state.get("live_match_active",False))),
        "runtime_age_minutes":payload.get("runtime_age_minutes"),
        "material_native_state_may_have_changed":bool(payload.get("material_native_state_may_have_changed",False)),
        "price_actionable":bool(payload.get("price_actionable",False)),
        "permitted_emergency":bool(payload.get("permitted_emergency",False)),
        "source_observations":payload.get("source_observations") if isinstance(payload.get("source_observations"),dict) else {},
    },cid); schedule=schedule_env["data"]
    watch_env=_invoke("watchlist_build",{"truth":truth,"price":price,"prediction":prediction,"dss":decision.get("dss") or {}},cid); watchlist=watch_env["data"]
    comparator_env=_invoke("owned_challenger_compare",{
        "truth":truth,
        "prediction":prediction,
        "watchlist":watchlist,
        "emerging_candidates":payload.get("emerging_candidates") if isinstance(payload.get("emerging_candidates"),list) else [],
        "workload_context":payload.get("workload_context") if isinstance(payload.get("workload_context"),dict) else {},
        "transfer_state":payload.get("transfer_state") if isinstance(payload.get("transfer_state"),dict) else {},
        "external_consensus":payload.get("external_consensus") if isinstance(payload.get("external_consensus"),dict) else {},
    },cid); comparator=comparator_env["data"]
    request=payload.get("report_request") if isinstance(payload.get("report_request"),dict) else {}
    request={**request,"schedule_mode":schedule.get("active_mode"),"visible_authorized":schedule.get("visible_authorized")}
    report_payload={"truth":truth,"price":price,"prediction":prediction,"decision":decision,"governance":governance,"watchlist":watchlist,"owned_challenger_comparator":comparator,"previous_report_state":states["report_state"]["data"] or {},"performance":snapshot.get("service_performance") or {},"force_full_report":bool(payload.get("force_full_report",False) or schedule.get("force_full_report",False)),"report_request":request,"schedule_decision":schedule}
    report_env=_invoke("reporting_build",report_payload,cid); report=report_env["data"]
    write_service,write_operation=_route("artifact_write"); mapping=load_json_config(CONFIG).get("artifact_mapping") or {}
    writes=invoke_parallel_envelopes({"watchlist":(write_service,write_operation,{"name":mapping["watchlist"],"data":watchlist}),"owned_challenger_comparator":(write_service,write_operation,{"name":mapping["owned_challenger_comparator"],"data":comparator}),"user_report":(write_service,write_operation,{"name":mapping["user_report"],"data":report["user_report"]}),"technical_appendix":(write_service,write_operation,{"name":mapping["technical_appendix"],"data":report["technical_appendix"]}),"report_state":(write_service,write_operation,{"name":mapping["report_state"],"data":report["report_state"]})},correlation_id=cid)
    snapshot["schedule_decision"]=schedule
    snapshot["match_state"]=match_state
    snapshot["watchlist_summary"]={"status":watchlist.get("status"),"candidate_count":watchlist.get("candidate_count"),"screening_contract":watchlist.get("screening_contract")}
    snapshot["owned_challenger_comparator"]={"status":comparator.get("status"),"authority":comparator.get("authority"),"pair_count":comparator.get("pair_count"),"classification_counts":comparator.get("classification_counts"),"top_comparisons":comparator.get("top_comparisons")}
    snapshot["user_report"]=report["user_report"]
    snapshot["technical_appendix"]=report["technical_appendix"]
    snapshot["report_state"]=report["report_state"]
    snapshot.setdefault("service_performance",{})["beta_composition"]={"schedule":{"service_compute_ms":schedule_env.get("elapsed_ms"),"round_trip_ms":schedule_env.get("round_trip_ms")},"watchlist":{"service_compute_ms":watch_env.get("elapsed_ms"),"round_trip_ms":watch_env.get("round_trip_ms")},"owned_challenger_comparator":{"service_compute_ms":comparator_env.get("elapsed_ms"),"round_trip_ms":comparator_env.get("round_trip_ms")},"reporting":{"service_compute_ms":report_env.get("elapsed_ms"),"round_trip_ms":report_env.get("round_trip_ms")},"persistence":{k:{"service_compute_ms":v.get("elapsed_ms"),"round_trip_ms":v.get("round_trip_ms")} for k,v in writes.items()}}
    return snapshot
