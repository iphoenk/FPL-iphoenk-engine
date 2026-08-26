from src.models.v4_prediction import lineup_distribution,project_fixture,project_horizon,workload_factor,defcon_expected_points,rates,fixture_adjustment
from src.models.v4_calibration import eligible,backtest,champion_gate
from src.engines.v4_runner import minutes_contexts,opponent_defence_ratings,player_priors,set_piece_priors
from src.models.v4_prediction_inputs import aggregate_advanced,build_last_season_index

def player():return {"id":1,"web_name":"Test","status":"a","minutes":270,"starts":3,"element_type":3,"expected_goals":"0.9","expected_assists":"0.6","bps":45}
def fixture(i=2):return {"event":i,"difficulty":3,"home":True}
def test_xmins_distribution_sums():
 d=lineup_distribution(player(),{"recent_starts":[1,1,1],"rest_days":7}); assert abs(d["start_probability"]+d["bench_probability"]+d["dnp_probability"]-1)<0.001; assert 0<=d["expected_minutes"]<=90; assert 0<=d["p60"]<=d["start_probability"]
def test_workload_penalty(): assert workload_factor({"rest_days":2,"cup_minutes_last7":180})<workload_factor({"rest_days":7})
def test_projection_has_uncertainty_and_components():
 r=project_fixture(player(),fixture(),{"penalty_share":1}); assert r["xpts"]>=0 and r["upper80"]>=r["xpts"]>=r["lower80"]; assert "attack" in r["components"]
def test_defcon_is_threshold_points_not_raw_actions():
 assert 0 <= defcon_expected_points(100,90,2,1) <= 2.0
 assert defcon_expected_points(3,90,2,1) < defcon_expected_points(15,90,2,1)
def test_defcon_rate_is_shrunk_early_season():
 p={"id":2,"web_name":"CB","status":"a","minutes":90,"starts":1,"element_type":2,"defensive_contribution":30}
 r=rates(p); assert r["def_actions90"] < r["raw_def_actions90"]; assert r["defcon_weight"] < .2
def test_clean_sheet_requires_60_minute_probability():
 p={"id":3,"web_name":"Risky","status":"a","minutes":30,"starts":0,"element_type":2}
 r=project_fixture(p,fixture(),{"recent_starts":[0,0,0]}); assert r["components"]["clean_sheet"] < 0.5
def test_single_fixture_sanity():
 p=player(); p["defensive_contribution"]=250
 r=project_fixture(p,fixture(),{"recent_starts":[1,1,1]}); assert r["components"]["defcon"] <= 2.0; assert r["xpts"] < 25.0
def test_horizon():
 r=project_horizon(player(),[fixture(i) for i in range(2,17)]); assert len(r["fixtures"])==15; assert r["xpts_15"]>=r["xpts_5"]>=r["xpts_3"]
def test_point_in_time_gate(): assert eligible("2026-08-20T10:00:00Z","2026-08-20T11:00:00Z") and not eligible("2026-08-20T12:00:00Z","2026-08-20T11:00:00Z")
def test_backtest_rejects_leakage():
 rows=[{"actual":5,"predicted":4,"available_at":"2026-08-20T10:00:00Z"},{"actual":9,"predicted":9,"available_at":"2026-08-20T12:00:00Z"}]; r=backtest(rows,"2026-08-20T11:00:00Z"); assert r["n"]==1 and r["leakage_rejected"]==1
def test_champion_requires_sample(): assert not champion_gate({"mae":2},{"n":10,"mae":1})["promote"]

def test_advanced_stats_are_resolved_by_official_element_id_and_change_rates():
 adv=aggregate_advanced(
  [{"id":"1","minutes":"90","expected_goals_per_90":"0.2","expected_assists_per_90":"0.1","defensive_contribution_per_90":"5"}],
  [{"player_id":"1.0","xg":"0.8"}],
  [{"player_id":"1","minutes_played":"90","xg":"0.8","xa":"0.4","defensive_contributions":"9"}],
 )[1]
 assert adv["identity_match"]=="official_element_id" and "playermatchstats" in "+".join(adv["sources"])
 assert rates(player(),adv)["raw_xg90"]==0.8 and rates(player(),adv)["raw_xa90"]==0.4

def test_last_season_prior_uses_stable_code_and_is_blended():
 p=player()|{"code":99,"first_name":"Test","second_name":"Player"}
 idx=build_last_season_index([p],{"season":"2025-26","rows":[{"code":"99","first_name":"Old","second_name":"Name","minutes":"2700","starts":"32","expected_goals_per_90":"0.6","expected_assists_per_90":"0.3"}]})
 pri=player_priors(p,idx[1])
 assert idx[1]["identity_match"]=="stable_player_code" and pri["last_season_weight"]==0.65
 assert pri["xg90_prior"]>player_priors(p)["xg90_prior"]

def test_set_piece_and_penalty_orders_feed_projection():
 role=set_piece_priors({"corners_and_indirect_freekicks_order":1,"direct_freekicks_order":1,"penalties_order":1})
 assert role["set_piece_share"]==1 and role["penalty_share"]==1
 base=project_fixture(player(),fixture(),{})
 boosted=project_fixture(player(),fixture(),role)
 assert boosted["components"]["attack"]>base["components"]["attack"]

def test_stronger_opponent_defence_reduces_attack_adjustment():
 weak=fixture_adjustment(fixture(),True,1,0.2)
 strong=fixture_adjustment(fixture(),True,1,0.8)
 assert strong<weak

def test_official_overall_strength_is_dynamic_early_season_fallback():
 teams={1:{"strength_defence_home":0,"strength_defence_away":0,"strength_overall_home":2,"strength_overall_away":2},2:{"strength_defence_home":0,"strength_defence_away":0,"strength_overall_home":5,"strength_overall_away":5}}
 ratings=opponent_defence_ratings(teams)
 assert ratings[2]["home"]>ratings[1]["home"] and ratings[2]["metric"]=="overall_fallback"

def test_xmins_context_uses_last_season_and_competition_priors():
 rows=[player()|{"id":i,"team":1,"element_type":4,"starts":1,"now_cost":80} for i in range(1,5)]
 previous={i:{"starts":30,"start_rate":.79,"avg_minutes_when_start":82} for i in range(1,5)}
 ctx=minutes_contexts(rows,previous,1)
 assert ctx[1]["xmins_prior_source"]=="current_starts+last_season_starts"
 assert ctx[1]["nailed_prior"]>.8 and ctx[1]["competition_pressure"]>0
