from src.v5.intelligence.observed_tactical_context import build_context, percentile, player_return_routes
from src.v5.services.prediction import _observed_as_tactical_context


def _payloads():
    elements=[{"id":1,"team":1},{"id":2,"team":1},{"id":3,"team":2},{"id":4,"team":2}]
    match={"gw":1,"source":"FPL-Core-Insights","dataset":"playermatchstats","fetched_at":"2026-08-28T00:00:00Z","rows":[
        {"player_id":"1","match_id":"m1","total_shots":"6","xg":"1.4","xa":"0.5","touches_opposition_box":"18","chances_created":"5","final_third_passes":"20","accurate_crosses":"4","corners":"5","recoveries":"8","tackles":"3","interceptions":"2"},
        {"player_id":"2","match_id":"m1","total_shots":"3","xg":"0.6","xa":"0.2","touches_opposition_box":"9","chances_created":"2","final_third_passes":"15","accurate_crosses":"2","recoveries":"6","tackles":"2","interceptions":"1"},
        {"player_id":"3","match_id":"m1","total_shots":"2","xg":"0.2","xa":"0.1","touches_opposition_box":"5","chances_created":"1","final_third_passes":"8","accurate_crosses":"1","recoveries":"5","tackles":"2","interceptions":"1"},
        {"player_id":"4","match_id":"m1","total_shots":"1","xg":"0.1","xa":"0","touches_opposition_box":"2","chances_created":"0","final_third_passes":"5","recoveries":"4","tackles":"2","interceptions":"1"},
    ]}
    shots={"dataset":"shots","fetched_at":"2026-08-28T00:00:00Z","rows":[
        {"match_id":"m1","player_id":"1","is_home":"True","start_x":"8","start_y":"50","situation":"regular"},
        {"match_id":"m1","player_id":"1","is_home":"True","start_x":"15","start_y":"20","situation":"corner"},
        {"match_id":"m1","player_id":"3","is_home":"False","start_x":"25","start_y":"50","situation":"regular"},
    ]}
    return elements,match,shots


def test_midrank_percentile_avoids_false_top_zero_signal():
    assert percentile(0,[0,0,0,0])==0.5
    assert percentile(2,[0,1,2,3])==0.625


def test_observed_context_is_event_evidence_not_fake_pressing_or_possession():
    elements,match,shots=_payloads(); out=build_context(elements,match,shots)
    assert out["contract"]=="TACTICAL_OBSERVED_CONTEXT_V1"
    assert set(out["teams"])=={"1","2"}
    row=out["teams"]["1"]["recent"][0]
    assert row["pressing_pattern"] is None
    assert row["possession_pattern"] is None
    assert row["confidence"]=="LOW"
    assert row["evidence"]["true_pressing_not_inferred"] is True
    assert row["evidence"]["true_possession_not_inferred"] is True
    assert row["observed_style_proxies"]
    assert all(float(x["observed_value"])>0 for x in row["observed_style_proxies"])


def test_observed_adapter_never_invents_coach_or_pressing_and_explicit_context_wins():
    elements,match,shots=_payloads(); observed=build_context(elements,match,shots)
    enrichment={"observed_tactical_context":observed}
    adapted=_observed_as_tactical_context(enrichment,None)
    assert adapted["team_profiles"]["1"]["coach"] is None
    assert adapted["team_profiles"]["1"]["pressing"] is None
    explicit={"team_profiles":{"1":{"team_id":1,"coach":"Verified Coach","pressing":"verified high press"}}}
    merged=_observed_as_tactical_context(enrichment,explicit)
    assert merged["team_profiles"]["1"]["coach"]=="Verified Coach"
    assert merged["team_profiles"]["1"]["pressing"]=="verified high press"


def test_player_return_routes_only_claim_observed_events():
    routes=player_return_routes({"box_touches":8,"shots":3,"xg":.7,"chances_created":4,"xa":.4,"corners":2,"penalties_scored":0,"penalties_missed":0})
    assert routes["progression_route"]=="box_pressure"
    assert {"box_pressure","shot_volume","chance_creation","set_piece_activity"} <= set(routes["return_routes"])
    assert "penalty_route" not in routes["return_routes"]
