from src.v5.services import orchestrator_beta


def test_beta_composition_adds_watchlist_comparator_reporting_and_persistence(monkeypatch):
    base={"correlation_id":"c1","team_summary":{"authority":"user_capture","owned_ids":[1],"team_value_ledger":[{"element":1}]},"phase":{"phase":"PRE_DEADLINE","planning_gw":2,"deadline_time":"2026-09-04T17:30:00Z"},"price_summary":{"alerts":[]},"decision_summary":{"dss":{},"lineup":{},"selected_package_id":"HOLD"},"framework_health":{"go_allowed":False},"service_performance":{}}
    monkeypatch.setattr(orchestrator_beta,"core_handle",lambda operation,payload:dict(base))
    persisted=[]
    def parallel(calls,correlation_id):
        if "prediction" in calls:
            return {
                "prediction":{"data":{"planning_gw":2,"players":[],"full_core_enrichment":{"competitive_load":{"status":"ACTIVE","contract":"V5_COMPETITIVE_LOAD_PRIMITIVE_V1","players":{},"player_count":0,"state_counts":{}}}}},
                "prices":{"data":{}},
                "prediction_ledger":{"data":{"schema_version":1,"records":{}}},
                "prediction_accuracy":{"data":{"overall":{"sample_size":0,"status":"NO_SETTLED_SAMPLE"},"settled_gameweeks":[]}},
                "report_state":{"data":{}},
                "decision_validation":{"data":{}},
            }
        persisted.extend(calls.keys())
        return {k:{"data":{"ok":True},"elapsed_ms":1,"round_trip_ms":2} for k in calls}
    monkeypatch.setattr(orchestrator_beta,"invoke_parallel_envelopes",parallel)
    def one(service,operation,payload,correlation_id):
        if service=="governance" and operation=="schedule":return {"data":{"active_mode":"INTERNAL_ONLY","visible_authorized":False,"force_full_report":False},"elapsed_ms":1,"round_trip_ms":2}
        if service=="watchlist":return {"data":{"status":"INSUFFICIENT_EVIDENCE","candidate_count":0,"screening_contract":"FULL_DSS_SCREEN_V1","positions":{}},"elapsed_ms":1,"round_trip_ms":2}
        if service=="price" and operation=="bind_watchlist_evidence":
            assert payload["owned_ids"]==[1]
            return {"data":dict(payload["watchlist"]),"elapsed_ms":1,"round_trip_ms":2}
        if service=="evaluation" and operation=="normalize_external_consensus":return {"data":{"contract":"V5_EXTERNAL_CONSENSUS_V1","overall":"INSUFFICIENT_EVIDENCE","observations":[],"requires_official_refresh":False,"governance":{"advisory_only":True,"majority_vote_used":False}},"elapsed_ms":1,"round_trip_ms":2}
        if service=="evaluation" and operation=="compare_owned_challenger":
            assert payload["external_consensus"]["governance"]["advisory_only"] is True
            assert payload["workload_context"]["contract"]=="V5_COMPETITIVE_LOAD_PRIMITIVE_V1"
            return {"data":{"model":"v5_owned_challenger_comparator_v1","status":"ACTIVE_ALPHA","authority":"ADVISORY_ONLY","pair_count":0,"classification_counts":{},"top_comparisons":[]},"elapsed_ms":1,"round_trip_ms":2}
        if service=="price" and operation=="annotate_comparator":
            assert payload["comparator"]["authority"]=="ADVISORY_ONLY"
            return {"data":dict(payload["comparator"]),"elapsed_ms":1,"round_trip_ms":2}
        if service=="evaluation" and operation=="capture_decision_validation":return {"data":{"contract":"V5_DECISION_VALIDATION_SNAPSHOTS_V1","records":{"2":{"status":"PREDEADLINE_CAPTURED"}},"last_capture":{"status":"PREDEADLINE_CAPTURED","planning_gw":2}},"elapsed_ms":1,"round_trip_ms":2}
        if service=="evaluation" and operation=="promotion_evidence":
            assert payload["ledger"]["records"]=={}
            assert payload["decision_validation"]["contract"]=="V5_DECISION_VALIDATION_SNAPSHOTS_V1"
            return {"data":{"model":"v5_prediction_promotion_evidence_v1","decision_metrics":{"captain_regret":{"status":"NO_GENUINE_PREDEADLINE_SAMPLE","sample_size":0,"mean":None},"xi_regret":{"status":"NO_GENUINE_PREDEADLINE_SAMPLE","sample_size":0,"mean":None},"transfer_comparator_realized_net_gain":{"status":"NO_GENUINE_PREDEADLINE_SAMPLE","sample_size":0,"mean":None}},"flattened_metrics":{"captain_regret":None,"xi_regret":None,"transfer_comparator_realized_net_gain":None},"settled_gameweeks_checked":[],"governance":{"postdeadline_reconstruction_forbidden":True}},"elapsed_ms":1,"round_trip_ms":2}
        if service=="reporting":
            assert payload["owned_challenger_comparator"]["authority"]=="ADVISORY_ONLY"
            assert payload["external_consensus"]["overall"]=="INSUFFICIENT_EVIDENCE"
            return {"data":{"user_report":{"layer":"USER_REPORT"},"technical_appendix":{"layer":"TECHNICAL_APPENDIX"},"report_state":{"state":{}}},"elapsed_ms":1,"round_trip_ms":2}
        raise AssertionError((service,operation))
    monkeypatch.setattr(orchestrator_beta,"invoke_envelope",one)
    result=orchestrator_beta.handle("run",{"persist":False})
    assert result["watchlist_summary"]["screening_contract"]=="FULL_DSS_SCREEN_V1"
    assert result["owned_challenger_comparator"]["authority"]=="ADVISORY_ONLY"
    assert result["competitive_load"]["contract"]=="V5_COMPETITIVE_LOAD_PRIMITIVE_V1"
    assert result["external_consensus"]["advisory_only"] is True
    assert result["decision_validation"]["last_capture"]["status"]=="PREDEADLINE_CAPTURED"
    assert result["decision_validation"]["promotion_evidence"]["captain_regret"]["sample_size"]==0
    assert result["user_report"]["layer"]=="USER_REPORT"
    assert result["technical_appendix"]["layer"]=="TECHNICAL_APPENDIX"
    assert "prediction_accuracy" in persisted
    assert "owned_challenger_comparator" in persisted
    assert "competitive_load" in persisted
    assert "external_consensus" in persisted
    assert "decision_validation_snapshots" in persisted
    assert "prediction_promotion_evidence" in result["service_performance"]["beta_composition"]
