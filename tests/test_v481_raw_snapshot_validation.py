import pytest

from src.services.raw_snapshot_service import _normalize_endpoint_health, _projection_baseline_authority, _validate_authoritative_squad

POSITION_TYPE = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}

def valid_squad():
    rows=[]; by_id={}; element=1
    for position,count in {"GK":2,"DEF":5,"MID":5,"FWD":3}.items():
        for _ in range(count):
            team=((element-1)//3)+1; rows.append({"element":element,"position":position}); by_id[element]={"id":element,"element_type":POSITION_TYPE[position],"team":team}; element+=1
    return rows,by_id

def test_authoritative_squad_accepts_legal_structure():
    squad,by_id=valid_squad(); _validate_authoritative_squad(squad,by_id)

@pytest.mark.parametrize("failure",["count","duplicate","identity","composition","club"])
def test_authoritative_squad_fails_closed_on_invalid_structure(failure):
    squad,by_id=valid_squad()
    if failure=="count": squad.pop()
    elif failure=="duplicate": squad[-1]["element"]=squad[0]["element"]
    elif failure=="identity": squad[-1]["position"]="MID"
    elif failure=="composition": squad[-1]["position"]="MID"; by_id[squad[-1]["element"]]["element_type"]=POSITION_TYPE["MID"]
    else:
        for element in range(1,5): by_id[element]["team"]=1
    with pytest.raises(RuntimeError,match="FAIL CLOSED"): _validate_authoritative_squad(squad,by_id)

def test_endpoint_health_normalization_is_truthful():
    health={"picks":{"status":"ERROR"},"event_live":{"status":"LIVE"}}; _normalize_endpoint_health(health,{"picks":None},1,1,False)
    assert health["picks"]["status"]=="NOT_YET_AVAILABLE"; assert health["event_live"]["status"]=="IDLE"

def test_projection_defaults_to_public_official_submitted_squad():
    a=_projection_baseline_authority({}, {"submitted_gw":2,"planning_gw":3})
    assert a["effective_authority"]=="OFFICIAL_SUBMITTED"; assert a["authority_source"]=="OFFICIAL_FPL_PICKS"; assert a["authority_model"]=="PUBLIC_OFFICIAL_PLUS_USER_CAPTURE"; assert a["public_official_role"]=="UNIVERSAL_FACTUAL_BACKBONE"; assert a["authenticated_official_role"]=="OPTIONAL_PRIVATE_ENRICHMENT"; assert a["authenticated_official_production_blocking"] is False

def test_targeted_user_capture_override_applies_only_to_target_gw():
    a=_projection_baseline_authority({"planning_override_active":True,"target_gw":3,"authority_source":"USER_CAPTURED_PREDEADLINE_DRAFT"},{"submitted_gw":2,"planning_gw":3})
    assert a["override_applied"] is True; assert a["effective_authority"]=="USER_CAPTURE_PREDEADLINE"; assert a["user_capture_role"]=="PRIVATE_PREDEADLINE_OVERRIDE"

def test_targeted_wildcard_capture_remains_supported():
    a=_projection_baseline_authority({"wildcard_active":True,"target_gw":2,"authority_source":"USER_CAPTURED_WC_DRAFT"},{"submitted_gw":1,"planning_gw":2})
    assert a["override_applied"] is True; assert a["effective_authority"]=="USER_CAPTURE_PREDEADLINE"

def test_stale_user_capture_cannot_leak_into_next_gw():
    a=_projection_baseline_authority({"planning_override_active":True,"target_gw":2},{"submitted_gw":2,"planning_gw":3})
    assert a["override_applied"] is False; assert a["stale_override_rejected"] is True; assert a["effective_authority"]=="OFFICIAL_SUBMITTED"

def test_postdeadline_official_reclaims_authority():
    a=_projection_baseline_authority({"planning_override_active":True,"target_gw":2},{"submitted_gw":2,"planning_gw":2})
    assert a["override_applied"] is False; assert a["effective_authority"]=="OFFICIAL_SUBMITTED"; assert a["authority_source"]=="OFFICIAL_FPL_PICKS"

def test_active_override_without_target_gw_fails_closed():
    with pytest.raises(RuntimeError,match="missing target_gw"): _projection_baseline_authority({"planning_override_active":True},{"submitted_gw":1,"planning_gw":2})
