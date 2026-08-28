from datetime import datetime, timezone

import pytest

from src.v5.services import orchestrator_beta


def test_beta_refresh_adds_watchlist_reporting_hot_materialization_and_persistence(monkeypatch):
    base={"mode":"daily","team_id":1,"correlation_id":"c1","team_summary":{"authority":"user_lock","team_value_ledger":[{"element":1}]},"phase":{"phase":"PRE_DEADLINE"},"price_summary":{"alerts":[]},"decision_summary":{"dss":{},"lineup":{},"selected_package_id":"HOLD"},"framework_health":{"go_allowed":False},"prediction_summary":{},"evaluation_summary":{},"service_performance":{}}
    monkeypatch.setattr(orchestrator_beta,"core_handle",lambda operation,payload:dict(base))
    monkeypatch.setattr(orchestrator_beta,"build_hot_bundle",lambda snapshot,watchlist,report:{"contract":"V5_DECISION_HOT_BUNDLE_V2","watchlist_summary":{"status":watchlist.get("status"),"candidate_count":watchlist.get("candidate_count"),"screening_contract":watchlist.get("screening_contract")}})
    persistence_order=[]
    def parallel(calls,correlation_id):
        if "prediction" in calls:return {"prediction":{"data":{"players":[]},"elapsed_ms":0,"round_trip_ms":1},"report_state":{"data":{},"elapsed_ms":0,"round_trip_ms":1}}
        persistence_order.append(("support", tuple(calls)))
        return {k:{"data":{"ok":True},"elapsed_ms":1,"round_trip_ms":2} for k in calls}
    monkeypatch.setattr(orchestrator_beta,"invoke_parallel_envelopes",parallel)
    def one(service,operation,payload,correlation_id):
        if service=="watchlist":return {"data":{"status":"INSUFFICIENT_EVIDENCE","candidate_count":0,"screening_contract":"FULL_DSS_SCREEN_V1","positions":{}},"elapsed_ms":1,"round_trip_ms":2}
        if service=="reporting":return {"data":{"user_report":{"layer":"USER_REPORT"},"technical_appendix":{"layer":"TECHNICAL_APPENDIX"},"report_state":{"state":{}}},"elapsed_ms":1,"round_trip_ms":2}
        if service=="snapshot" and operation=="write" and payload.get("name")=="decision_hot_bundle":
            persistence_order.append(("hot_commit", payload.get("name")))
            return {"data":{"ok":True},"elapsed_ms":1,"round_trip_ms":2,"transport_overhead_ms":1}
        raise AssertionError((service,operation,payload))
    monkeypatch.setattr(orchestrator_beta,"invoke_envelope",one)
    result=orchestrator_beta.handle("run",{"persist":False})
    assert result["watchlist_summary"]["screening_contract"]=="FULL_DSS_SCREEN_V1"
    assert result["user_report"]["layer"]=="USER_REPORT"
    assert result["technical_appendix"]["layer"]=="TECHNICAL_APPENDIX"
    assert result["execution_plane"]["current"]=="refresh"
    assert result["execution_plane"]["hot_materialization_commit_order"]=="AFTER_SUPPORTING_ARTIFACTS"
    assert persistence_order[0][0]=="support"
    assert set(persistence_order[0][1])=={"watchlist","user_report","technical_appendix","report_state"}
    assert persistence_order[1]==("hot_commit","decision_hot_bundle")
    assert "beta_composition" in result["service_performance"]
    assert result["service_performance"]["full_beta_contract"]["latency_release_blocking"] is False
    assert result["service_performance"]["full_beta_contract"]["hot_materialization_is_final_commit_marker"] is True


def test_supporting_persistence_failure_never_publishes_hot_materialization(monkeypatch):
    base={"mode":"daily","team_id":1,"correlation_id":"c1","team_summary":{"authority":"user_lock"},"phase":{"phase":"PRE_DEADLINE"},"price_summary":{"alerts":[]},"decision_summary":{"dss":{}},"framework_health":{"go_allowed":False},"prediction_summary":{},"evaluation_summary":{},"service_performance":{}}
    monkeypatch.setattr(orchestrator_beta,"core_handle",lambda operation,payload:dict(base))
    monkeypatch.setattr(orchestrator_beta,"build_hot_bundle",lambda snapshot,watchlist,report:{"contract":"V5_DECISION_HOT_BUNDLE_V2","watchlist_summary":{}})
    hot_commits=[]
    def parallel(calls,correlation_id):
        if "prediction" in calls:return {"prediction":{"data":{"players":[]},"elapsed_ms":0,"round_trip_ms":1},"report_state":{"data":{},"elapsed_ms":0,"round_trip_ms":1}}
        raise RuntimeError("supporting persistence failed")
    monkeypatch.setattr(orchestrator_beta,"invoke_parallel_envelopes",parallel)
    def one(service,operation,payload,correlation_id):
        if service=="watchlist":return {"data":{"status":"READY","candidate_count":0,"positions":{}},"elapsed_ms":1,"round_trip_ms":2}
        if service=="reporting":return {"data":{"user_report":{},"technical_appendix":{},"report_state":{}},"elapsed_ms":1,"round_trip_ms":2}
        if service=="snapshot" and payload.get("name")=="decision_hot_bundle":
            hot_commits.append(payload)
            return {"data":{},"elapsed_ms":1,"round_trip_ms":2}
        raise AssertionError((service,operation,payload))
    monkeypatch.setattr(orchestrator_beta,"invoke_envelope",one)
    with pytest.raises(RuntimeError, match="supporting persistence failed"):
        orchestrator_beta.handle("run",{})
    assert hot_commits==[]


def test_hot_run_reads_only_materialized_bundle_and_is_subsecond(monkeypatch):
    now=datetime.now(timezone.utc).isoformat()
    bundle={
        "schema_version":2,"contract":"V5_DECISION_HOT_BUNDLE_V2","generated_at":now,
        "runtime_fingerprint":"fp1","mode":"daily","phase":{"phase":"PRE_DEADLINE"},"team_id":1,
        "squad_authority":"user_lock","decision_summary":{"selected_package_id":"HOLD"},
        "framework_health":{"go_allowed":False},"watchlist_summary":{"candidate_count":20},
        "user_report":{"layer":"USER_REPORT"},"technical_appendix":{"layer":"TECHNICAL_APPENDIX"},"report_state":{"state":{}},
    }
    calls=[]
    def invoke(name,payload,cid):
        calls.append((name,payload))
        assert name=="artifact_read"
        return {"data":bundle,"elapsed_ms":0.1,"round_trip_ms":1.0,"transport_overhead_ms":0.9}
    monkeypatch.setattr(orchestrator_beta,"_invoke",invoke)
    monkeypatch.setattr(orchestrator_beta,"current_runtime_fingerprint",lambda:"fp1")
    result=orchestrator_beta.handle("hot_run",{"mode":"daily","team_id":1})
    assert result["governance"]["execution_plane"]=="hot"
    assert result["governance"]["hidden_synchronous_refresh"] is False
    assert result["service_performance"]["pass"] is True
    assert result["service_performance"]["hot_path_wall_ms"] < 950
    assert [name for name,_ in calls]==["artifact_read"]
