from src.models.v4_prediction import lineup_distribution,project_fixture,project_horizon,workload_factor,defcon_expected_points
from src.models.v4_calibration import eligible,backtest,champion_gate

def player():return {"id":1,"web_name":"Test","status":"a","minutes":270,"starts":3,"element_type":3,"expected_goals":"0.9","expected_assists":"0.6","bps":45}
def fixture(i=2):return {"event":i,"difficulty":3,"home":True}
def test_xmins_distribution_sums():
 d=lineup_distribution(player(),{"recent_starts":[1,1,1],"rest_days":7}); assert abs(d["start_probability"]+d["bench_probability"]+d["dnp_probability"]-1)<0.001; assert 0<=d["expected_minutes"]<=90
def test_workload_penalty(): assert workload_factor({"rest_days":2,"cup_minutes_last7":180})<workload_factor({"rest_days":7})
def test_projection_has_uncertainty_and_components():
 r=project_fixture(player(),fixture(),{"penalty_share":1}); assert r["xpts"]>=0 and r["upper80"]>=r["xpts"]>=r["lower80"]; assert "attack" in r["components"]
def test_defcon_is_threshold_points_not_raw_actions():
 assert 0 <= defcon_expected_points(100,90,2) <= 2.0
 assert defcon_expected_points(3,90,2) < defcon_expected_points(15,90,2)
def test_single_fixture_sanity():
 p=player(); p["defensive_contribution"]=250
 r=project_fixture(p,fixture(),{"recent_starts":[1,1,1]})
 assert r["components"]["defcon"] <= 2.0
 assert r["xpts"] < 25.0
def test_horizon():
 r=project_horizon(player(),[fixture(i) for i in range(2,17)]); assert len(r["fixtures"])==15; assert r["xpts_15"]>=r["xpts_5"]>=r["xpts_3"]
def test_point_in_time_gate(): assert eligible("2026-08-20T10:00:00Z","2026-08-20T11:00:00Z") and not eligible("2026-08-20T12:00:00Z","2026-08-20T11:00:00Z")
def test_backtest_rejects_leakage():
 rows=[{"actual":5,"predicted":4,"available_at":"2026-08-20T10:00:00Z"},{"actual":9,"predicted":9,"available_at":"2026-08-20T12:00:00Z"}]; r=backtest(rows,"2026-08-20T11:00:00Z"); assert r["n"]==1 and r["leakage_rejected"]==1
def test_champion_requires_sample(): assert not champion_gate({"mae":2},{"n":10,"mae":1})["promote"]
