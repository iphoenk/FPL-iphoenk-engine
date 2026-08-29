from src.v5.price_service import build_transfer_momentum_evidence
from src.v5.services.price import handle as price_handle


def _bootstrap(count=20, *, missing_counts=0):
    elements=[]
    for eid in range(1,count+1):
        row={"id":eid,"web_name":f"P{eid}","now_cost":50+eid,"selected_by_percent":"1.0","transfers_in_event":eid*10,"transfers_out_event":eid*3,"cost_change_event":0,"cost_change_start":0,"transfers_in":100,"transfers_out":50,"status":"a"}
        if eid<=missing_counts:
            row["transfers_in_event"]=None
            row["transfers_out_event"]=None
        elements.append(row)
    return {"total_players":1000000,"elements":elements}


def _price_rows(bootstrap, keep=None, mismatch=False):
    rows=[]
    elements=bootstrap["elements"] if keep is None else bootstrap["elements"][:keep]
    for row in elements:
        cost=int(row["now_cost"]) + (1 if mismatch else 0)
        rows.append({"element":row["id"],"now_cost":cost})
    return rows


def test_transfer_momentum_available_from_official_counts_and_current_price_linkage():
    bootstrap=_bootstrap()
    evidence=build_transfer_momentum_evidence(bootstrap,_price_rows(bootstrap))
    assert evidence["evidence_state"]=="AVAILABLE"
    assert evidence["transfer_count_coverage_ratio"]==1.0
    assert evidence["price_snapshot_linkage_ratio"]==1.0
    assert evidence["current_price_match_ratio"]==1.0
    assert evidence["net_transfers_event"]==sum(e*10-e*3 for e in range(1,21))
    assert evidence["external_threshold_invented"] is False
    assert evidence["predicted_price_change_invented"] is False


def test_transfer_momentum_fails_closed_when_linkage_below_contract_threshold():
    bootstrap=_bootstrap()
    evidence=build_transfer_momentum_evidence(bootstrap,_price_rows(bootstrap,keep=18))
    assert evidence["evidence_state"]=="INSUFFICIENT"
    assert evidence["price_snapshot_linkage_ratio"]==0.9


def test_transfer_momentum_fails_closed_when_official_transfer_counts_missing():
    bootstrap=_bootstrap(missing_counts=2)
    evidence=build_transfer_momentum_evidence(bootstrap,_price_rows(bootstrap))
    assert evidence["evidence_state"]=="INSUFFICIENT"
    assert evidence["transfer_count_coverage_ratio"]==0.9


def test_transfer_momentum_fails_closed_when_current_price_does_not_match():
    bootstrap=_bootstrap()
    evidence=build_transfer_momentum_evidence(bootstrap,_price_rows(bootstrap,mismatch=True))
    assert evidence["evidence_state"]=="INSUFFICIENT"
    assert evidence["current_price_match_ratio"]==0.0


def test_price_service_advertises_dss42_only_when_operational_evidence_available(monkeypatch):
    good={"transfer_momentum":{"evidence_state":"AVAILABLE"}}
    bad={"transfer_momentum":{"evidence_state":"INSUFFICIENT"}}
    import src.v5.services.price as service
    monkeypatch.setattr(service,"build_price_snapshot",lambda *args,**kwargs:good)
    result=price_handle("build",{"bootstrap":{"elements":[]}})
    assert "transfer_momentum" in result["capabilities"]
    monkeypatch.setattr(service,"build_price_snapshot",lambda *args,**kwargs:bad)
    result=price_handle("build",{"bootstrap":{"elements":[]}})
    assert "transfer_momentum" not in result["capabilities"]
    assert "price_intelligence" in result["capabilities"]
