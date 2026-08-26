from src.v5.services import orchestrator_beta


def test_beta_composition_adds_watchlist_reporting_and_persistence(monkeypatch):
    base={"correlation_id":"c1","team_summary":{"authority":"user_lock","team_value_ledger":[{"element":1}]},"phase":{"phase":"PRE_DEADLINE"},"price_summary":{"alerts":[]},"decision_summary":{"dss":{},"lineup":{},"selected_package_id":"HOLD"},"framework_health":{"go_allowed":False},"service_performance":{}}
    monkeypatch.setattr(orchestrator_beta,"core_handle",lambda operation,payload:dict(base))
    def parallel(calls,correlation_id):
        if "prediction" in calls:return {"prediction":{"data":{"players":[]}},"report_state":{"data":{}}}
        return {k:{"data":{"ok":True},"elapsed_ms":1,"round_trip_ms":2} for k in calls}
    monkeypatch.setattr(orchestrator_beta,"invoke_parallel_envelopes",parallel)
    def one(service,operation,payload,correlation_id):
        if service=="watchlist":return {"data":{"status":"INSUFFICIENT_EVIDENCE","candidate_count":0,"screening_contract":"FULL_DSS_SCREEN_V1","positions":{}},"elapsed_ms":1,"round_trip_ms":2}
        if service=="reporting":return {"data":{"user_report":{"layer":"USER_REPORT"},"technical_appendix":{"layer":"TECHNICAL_APPENDIX"},"report_state":{"state":{}}},"elapsed_ms":1,"round_trip_ms":2}
        raise AssertionError((service,operation))
    monkeypatch.setattr(orchestrator_beta,"invoke_envelope",one)
    result=orchestrator_beta.handle("run",{"persist":False})
    assert result["watchlist_summary"]["screening_contract"]=="FULL_DSS_SCREEN_V1"
    assert result["user_report"]["layer"]=="USER_REPORT"
    assert result["technical_appendix"]["layer"]=="TECHNICAL_APPENDIX"
    assert "beta_composition" in result["service_performance"]
