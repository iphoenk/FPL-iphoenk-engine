from src.v5.team_review import build_team_review

def test_team_review_is_read_only_and_isolated():
    truth={"team":{"squad":[{"element":1,"team_id":2}]}}; pred={"players":[{"element":1,"name":"A","projection_confidence":"LOW","xpts_3":3,"xpts_5":5,"xpts_10":10,"xpts_15":15,"xmins":{"dnp_probability":0.25}}]}; decision={"status":"READY","selected_package_id":"HOLD"}
    out=build_team_review(truth,pred,decision,{"candidate_count":20}); assert out["read_only"] is True; assert out["may_mutate_decision"] is False; assert out["squad_risk_summary"]["risk_count"]==1; assert out["horizon_exposure"][5]==5.0
