from src.v5.intelligence.advanced_prediction import enrich_prediction

def test_advanced_prediction_never_replaces_base_xpts_and_defcon_prior_not_active():
    base={"players":[{"element":1,"current_season":{"minutes":90},"rates":{"xg90":0.3,"xa90":0.2,"dc90":0.4,"sources":{"dc90":"position_prior"}},"xmins":{"start_probability":0.8,"bench_probability":0.15,"dnp_probability":0.05,"starter_minutes_if_start":75,"bench_minutes_if_used":18},"uncertainty":2.0,"mean_xpts":5.0}]}
    out=enrich_prediction(base,{})
    row=out["players"][0]
    assert row["mean_xpts"]==5.0
    assert row["advanced"]["authoritative_xpts_replaced"] is False
    assert row["advanced"]["xmins_distribution"]["dnp_probability"]==0.05
    assert row["advanced"]["defcon_probability"] is None
    assert row["advanced"]["feature_bundle"]["states"]["defcon_probability"]["state"]=="UNAVAILABLE"
