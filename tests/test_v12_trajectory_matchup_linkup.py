from src.engines.v12_trajectory_matchup_linkup import (
    build_trajectory, dependency_edge, marginalize_teammate, opponent_matchup,
)


def test_A_blank_twice_high_xg_not_strongly_adverse():
    rows=[{"minutes":90,"xg":0.8,"xa":0,"goals":0,"assists":0,"manager":"M","formation":"433","player_role":"9"} for _ in range(2)]
    out=opponent_matchup(rows,{"manager":"M","formation":"433","player_role":"9"},baseline_xgi90=0.65)
    assert out["classification"] != "ADVERSE"
    assert out["result_evidence"]["returns"] == 0
    assert out["process_evidence"]["observed_xgi90"] > out["process_evidence"]["posterior_xgi90"]


def test_B_repeated_process_suppression_can_be_adverse():
    rows=[{"minutes":90,"xg":0.05,"xa":0.01,"goals":0,"assists":0,"manager":"M","formation":"433","player_role":"9"} for _ in range(6)]
    out=opponent_matchup(rows,{"manager":"M","formation":"433","player_role":"9"},baseline_xgi90=0.65)
    assert out["classification"] == "ADVERSE"


def test_C_system_change_discounts_history():
    rows=[{"minutes":90,"xg":0.02,"xa":0,"manager":"OLD","formation":"442","player_role":"LW"} for _ in range(4)]
    changed=opponent_matchup(rows,{"manager":"NEW","formation":"343","player_role":"9"},baseline_xgi90=0.55)
    same=opponent_matchup(rows,{"manager":"OLD","formation":"442","player_role":"LW"},baseline_xgi90=0.55)
    assert changed["tactical_similarity"] < same["tactical_similarity"]
    assert changed["effective_sample"] < same["effective_sample"]


def test_D_one_match_haul_does_not_reset_trajectory():
    rows=[
      {"gw":1,"minutes":90,"xgi90":0.20,"role":"RW"},
      {"gw":2,"minutes":90,"xgi90":0.22,"role":"RW"},
      {"gw":3,"minutes":90,"xgi90":0.18,"role":"RW"},
      {"gw":4,"minutes":90,"xgi90":1.50,"role":"RW"},
    ]
    out=build_trajectory(rows)
    assert out["sample_size"] == 4
    assert out["weighted_xgi90"] < 1.0


def test_E_sustained_role_change_is_detected():
    rows=[{"gw":1,"role":"RW"},{"gw":2,"role":"RW"},{"gw":3,"role":"9"},{"gw":4,"role":"9"}]
    assert build_trajectory(rows)["role_transition_sustained"] is True


def test_F_creator_absence_reduces_finisher_when_dependency_positive():
    edge=dependency_edge({"shared_minutes":900,"direct_chances_created":12,"xa_to_xg":4,"tactical_complementarity":1,"with_without_xgi90_delta":0.25})
    m=marginalize_teammate(0.70,edge,1.0)
    absent=marginalize_teammate(0.70,edge,0.0)
    assert m["marginal_rate"] > absent["marginal_rate"]


def test_G_fifty_percent_start_is_probability_weighted():
    edge=dependency_edge({"shared_minutes":900,"direct_chances_created":12,"xa_to_xg":4,"tactical_complementarity":1,"with_without_xgi90_delta":0.25})
    mid=marginalize_teammate(0.70,edge,0.5)
    lo=marginalize_teammate(0.70,edge,0.0)["marginal_rate"]
    hi=marginalize_teammate(0.70,edge,1.0)["marginal_rate"]
    assert lo < mid["marginal_rate"] < hi


def test_H_correlation_without_process_connection_stays_weak():
    edge=dependency_edge({"shared_minutes":1200,"co_returns":20,"direct_chances_created":0,"xa_to_xg":0,"progressive_connections":0,"tactical_complementarity":0.5,"with_without_xgi90_delta":0.3})
    assert edge["confidence"] < 0.1


def test_I_chain_middle_absence_can_weaken_downstream_by_composition():
    e1=dependency_edge({"shared_minutes":800,"direct_chances_created":8,"xa_to_xg":2,"tactical_complementarity":1,"with_without_xgi90_delta":0.15})
    e2=dependency_edge({"shared_minutes":800,"direct_chances_created":10,"xa_to_xg":3,"tactical_complementarity":1,"with_without_xgi90_delta":0.20})
    intact=marginalize_teammate(marginalize_teammate(0.6,e1,1)["marginal_rate"],e2,1)["marginal_rate"]
    broken=marginalize_teammate(marginalize_teammate(0.6,e1,0)["marginal_rate"],e2,0)["marginal_rate"]
    assert intact > broken


def test_J_role_change_discounts_old_dependency_via_tactical_relevance():
    high=dependency_edge({"shared_minutes":900,"direct_chances_created":10,"xa_to_xg":3,"tactical_complementarity":1,"with_without_xgi90_delta":0.2})
    low=dependency_edge({"shared_minutes":900,"direct_chances_created":10,"xa_to_xg":3,"tactical_complementarity":0.1,"with_without_xgi90_delta":0.2})
    assert low["confidence"] < high["confidence"]


def test_haaland_sunderland_acceptance_never_uses_never_scored_rule():
    one=[{"minutes":90,"xg":1.1,"xa":0.05,"goals":0,"assists":0,"manager":"X","formation":"541","player_role":"9"}]
    out=opponent_matchup(one,{"manager":"X","formation":"541","player_role":"9"},baseline_xgi90=0.85)
    assert out["classification"] == "INSUFFICIENT SAMPLE"
    assert out["governance"]["raw_h2h_result_is_authority"] is False


def test_brobbey_le_fee_one_match_cannot_create_high_confidence_dependency():
    edge=dependency_edge({"shared_minutes":80,"direct_chances_created":2,"xa_to_xg":1,"progressive_connections":4,"tactical_complementarity":0.8,"with_without_xgi90_delta":0.3,"sample_size":1})
    assert edge["confidence"] < 0.5
