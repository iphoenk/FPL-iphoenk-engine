from src.v5.decision.correlated_simulation import simulate_package_delta

def test_correlated_simulation_is_deterministic_shadow_only():
    hold={"score":{"robust_score":10.0,"uncertainty":1.0}}
    challenger={"score":{"robust_score":12.0,"uncertainty":1.0}}
    a=simulate_package_delta(challenger,hold,seed=42); b=simulate_package_delta(challenger,hold,seed=42)
    assert a==b
    assert a["decision_authority"] is False
    assert a["p_outperform_hold_correlated"]>0.5
    assert a["draws"]>=2000
