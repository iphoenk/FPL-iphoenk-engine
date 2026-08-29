import src.models.v4_prediction as prediction_model
from src.models.v4_prediction import lineup_distribution,project_fixture,project_horizon,workload_factor,defcon_expected_points,rates,fixture_adjustment
from src.models.v4_calibration import eligible,backtest,champion_gate
from src.engines.v4_runner import advanced_materially_distinct,minutes_contexts,opponent_defence_ratings,player_priors,set_piece_priors,team_role_priors
from src.models.v4_prediction_inputs import aggregate_advanced,build_last_season_index
from src.models.projection import project_points

def player():return {"id":1,"web_name":"Test","status":"a","minutes":270,"starts":3,"element_type":3,"expected_goals":"0.9","expected_assists":"0.6","bps":45}
def fixture(i=2):return {"event":i,"difficulty":3,"home":True}
def test_xmins_distribution_sums():
 d=lineup_distribution(player(),{"recent_starts":[1,1,1],"rest_days":7}); assert abs(d["start_probability"]+d["bench_probability"]+d["dnp_probability"]-1)<0.001; assert 0<=d["expected_minutes"]<=90; assert 0<=d["p60"]<=d["start_probability"]; assert 0<=d["start_probability_confidence"]<=1
def test_workload_penalty(): assert workload_factor({"rest_days":2,"cup_minutes_last7":180})<workload_factor({"rest_days":7})
def test_projection_has_uncertainty_and_components():
 r=project_fixture(player(),fixture(),{"penalty_share":1}); assert r["xpts"]>=0 and r["upper80"]>=r["xpts"]>=r["lower80"]; assert "attack" in r["components"]; assert "ablation" in r
def test_appearance_uses_unconditional_p60_without_double_rotation_penalty(monkeypatch):
 monkeypatch.setattr(prediction_model,"lineup_distribution",lambda *_args,**_kwargs:{"start_probability":.6,"start_probability_confidence":.5,"bench_probability":.1,"dnp_probability":.3,"expected_minutes":60,"p60":.6,"availability_probability":1,"workload_factor":1,"competition_factor":1,"competition_uncertainty":1})
 r=prediction_model.project_fixture(player(),fixture())
 assert r["components"]["appearance"]==1.3
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

def test_set_piece_and_penalty_orders_do_not_double_count_existing_xg_xa():
 role=set_piece_priors({"corners_and_indirect_freekicks_order":1,"direct_freekicks_order":1,"penalties_order":1})
 assert role["set_piece_share"] is None and role["penalty_share"] is None
 assert role["set_piece_order_weight"]==1 and role["penalty_order_weight"]==1
 base=project_fixture(player(),fixture(),{})
 metadata=project_fixture(player(),fixture(),role)
 assert metadata["components"]["attack"]==base["components"]["attack"]
 assert metadata["components"]["set_piece_penalty_adjustment"]==0
 assert metadata["provenance"]["role_scoring_mode"]=="prior_reallocation_no_direct_double_count"

def test_stronger_opponent_defence_reduces_attack_adjustment():
 weak=fixture_adjustment(fixture(),True,1,0.2)
 strong=fixture_adjustment(fixture(),True,1,0.8)
 assert strong<weak

def test_official_overall_strength_is_diagnostic_only_early_season_fallback():
 teams={1:{"strength_defence_home":0,"strength_defence_away":0,"strength_overall_home":2,"strength_overall_away":2},2:{"strength_defence_home":0,"strength_defence_away":0,"strength_overall_home":5,"strength_overall_away":5}}
 ratings=opponent_defence_ratings(teams)
 assert ratings[2]["home"]==ratings[1]["home"]==.5
 assert ratings[2]["diagnostic_home"]>ratings[1]["diagnostic_home"]
 assert ratings[2]["metric"]=="overall_fallback_diagnostic_only"

def test_finished_results_create_shrunk_dynamic_opponent_defence_for_every_team():
 teams={1:{"strength_defence_home":0,"strength_defence_away":0,"strength_overall_home":2,"strength_overall_away":2},2:{"strength_defence_home":0,"strength_defence_away":0,"strength_overall_home":5,"strength_overall_away":5},3:{"strength_defence_home":0,"strength_defence_away":0,"strength_overall_home":3,"strength_overall_away":3}}
 fixtures=[{"finished":True,"team_h":1,"team_a":2,"team_h_score":0,"team_a_score":3}]
 ratings=opponent_defence_ratings(teams,fixtures)
 assert all(row["metric"]=="dynamic_bayesian_results" for row in ratings.values())
 assert ratings[1]["home"]<ratings[2]["away"]
 assert ratings[3]["result_games_home"]==0

def test_role_prior_is_team_normalized_and_zero_centred():
 players=[{"id":1,"team":1,"element_type":3,"corners_and_indirect_freekicks_order":1,"penalties_order":1},{"id":2,"team":1,"element_type":3}]
 priors=team_role_priors(players,{1:{"set_piece_xg":.4,"penalty_events":1},2:{}})
 assert round(sum(row["set_piece_share"] for row in priors.values()),6)==1
 assert round(sum(row["penalty_share"] for row in priors.values()),6)==1
 assert priors[1]["role_attack_multiplier"]>1>priors[2]["role_attack_multiplier"]

def test_legacy_projection_uses_canonical_goalkeeper_goal_points():
 p={"element_type":1,"status":"a","minutes":90,"starts":1}
 result=project_points(p,{"start_probability":1,"xg_per90":1,"clean_sheet_probability":0,"saves_per90":0,"bonus_per90":0})
 assert result["components"]["attack"]==10

def test_xmins_context_uses_direct_evidence_and_tactical_role_competition():
 rows=[player()|{"id":i,"team":1,"element_type":4,"starts":1,"now_cost":80} for i in range(1,5)]
 previous={i:{"starts":30,"start_rate":.79,"avg_minutes_when_start":82} for i in range(1,5)}
 ctx=minutes_contexts(rows,previous,1)
 assert ctx[1]["xmins_prior_source"]=="current_starts+last_season_starts"
 assert ctx[1]["nailed_prior"]>.8 and ctx[1]["competition_pressure"]>0
 assert ctx[1]["competition_source"]=="inferred_tactical_role_peer_group"
 assert ctx[1]["competition_adjustment_applied"] is True
 assert ctx[1]["competition_factor"]<1
 assert 0<lineup_distribution(rows[0],ctx[1])["competition_factor"]<=1

def test_competition_flag_is_false_when_factor_is_neutral():
 p={"id":10,"web_name":"Uncontested","status":"a","minutes":270,"starts":3,"team":1,"element_type":4,"now_cost":80}
 ctx=minutes_contexts([p],{},1)[10]
 assert ctx["competition_pressure"]==0
 assert ctx["squad_depth_pressure"]==0
 assert ctx["competition_factor"]==1
 assert ctx["competition_adjustment_applied"] is False
 assert lineup_distribution(p,ctx)["competition_factor"]==1

def test_xmins_no_evidence_has_no_mechanical_start_or_bench_floor():
 p={"id":10,"web_name":"Unknown","status":"a","minutes":0,"starts":0,"element_type":3,"now_cost":45}
 ctx=minutes_contexts([p],{},1)[10]
 d=lineup_distribution(p,ctx)
 assert d["start_probability"]<.1
 assert d["bench_probability"]<.15
 assert d["expected_minutes"]<10
 assert d["dnp_probability"]>.75

def test_advanced_materiality_requires_deep_values_distinct_from_official():
 p=player()
 mirrored={"xg_per90":.3,"xa_per90":.2,"defensive_contribution_per90":0,"sources":["fpl_core_insights:players"]}
 distinct=mirrored|{"xg_per90":.8,"sources":["fpl_core_insights:playermatchstats"]}
 assert not advanced_materially_distinct(p,mirrored)
 assert advanced_materially_distinct(p,distinct)