from __future__ import annotations
import pytest
from src.engines.v12_player_minutes import estimate_player_minutes
from src.models.historical_projection import build as build_projection

def player():
    return {"id":1,"web_name":"P1","team":1,"element_type":3,"now_cost":70,"status":"a","selected_by_percent":"10","starts":4,"minutes":330,"chance_of_playing_next_round":100,"expected_goals":1.2,"expected_assists":1.5,"bonus":4,"saves":0}
def projection(scenario_overrides=None):
    bootstrap={"teams":[{"id":1,"name":"A"},{"id":2,"name":"B"}],"elements":[player()]}
    strength={"baseline":{"home_goals":1.3,"away_goals":1.3},"teams":[{"team_id":1,"matches_played":5},{"team_id":2,"matches_played":5}],"matchups":[{"event":5,"kickoff_time":"2026-09-20T12:00:00Z","team_h":1,"team_a":2,"home_expected_goals":1.4,"away_expected_goals":1.0,"home_clean_sheet_probability":0.35,"away_clean_sheet_probability":0.22}]}
    return build_projection(bootstrap,strength,planning_gw=5,prior_payload={"model":"prior","season":"2025/26","players":{}},horizon=15,scenario_overrides=scenario_overrides)
def test_unauthorized_direct_override_fails_closed():
    with pytest.raises(RuntimeError,match="explicit authorization"):
        estimate_player_minutes(player(),{"team_matches_played":5,"scenario_availability_probability_override":0.0})
@pytest.mark.parametrize("typ",["OWNED_UNAVAILABLE","CAPTAIN_UNAVAILABLE","VICE_UNAVAILABLE"])
def test_unavailable_scenario_is_canonical_p11_and_exact_zero(typ):
    normal=projection(); scenario=projection({"1":{"override_type":typ,"p_available":0.0}})
    x=scenario["players"][0]["xmins"]
    assert x["availability_source"]=="scenario_override"
    assert x["expected_minutes"]==pytest.approx(0.0)
    assert x["derived_probabilities"]["p_start"]==pytest.approx(0.0)
    assert x["derived_probabilities"]["p_dnp"]==pytest.approx(1.0)
    assert x["governance"]["scenario_override_applied"] is True
    assert scenario["governance"]["p4_scenario_override_count"]==1
    assert scenario["players"][0]["xpts_by_gw"][0]["mean"] < normal["players"][0]["xpts_by_gw"][0]["mean"]
def test_unknown_override_type_fails_closed():
    with pytest.raises(RuntimeError,match="unsupported P4 scenario override type"):
        projection({"1":{"override_type":"POSTHOC_XPTS_HACK","p_available":0.0}})
