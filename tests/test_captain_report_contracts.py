from src.engines.v12_captain_report_contracts import validate_captain_report_contracts

def section(c, v, state="COMPLETE"):
    return {"state": state, "content": {"captain": {"element_id": c}, "vice_captain": {"element_id": v}}}

def test_s08_s18_s19_consume_one_pair():
    sections = {"S08": section(11, 22), "S18": section(11, 22), "S19": section(11, 22), "S15B": {"state": "COMPLETE", "content": {"evidence": [{"player_id": 11}]}}}
    result = validate_captain_report_contracts(sections)
    assert result["valid"] is True
    assert result["canonical_pair"] == (11, 22)
    assert result["independent_winner"] is False

def test_mismatch_is_rejected():
    sections = {"S08": section(11, 22), "S18": section(12, 22), "S19": section(11, 22), "S15B": {"state": "COMPLETE", "content": {"evidence": []}}}
    result = validate_captain_report_contracts(sections)
    assert result["valid"] is False
    assert "CANONICAL_CVC_MISMATCH" in result["errors"]

def test_incomplete_s15b_degrades_without_fabrication():
    result = validate_captain_report_contracts({"S08": section(11, 22), "S18": section(11, 22), "S19": section(11, 22), "S15B": {"state": "DEGRADED", "content": {}}})
    assert result["degradation_state"] == "DEGRADED"
    assert result["canonical_pair"] is None

def test_s15b_cannot_contain_decision():
    result = validate_captain_report_contracts({"S08": section(11, 22), "S18": section(11, 22), "S19": section(11, 22), "S15B": {"state": "COMPLETE", "content": {"winner": 11}}})
    assert result["valid"] is False
    assert result["s15b_evidence_only"] is False
