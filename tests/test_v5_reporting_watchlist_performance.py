from time import perf_counter

from src.v5.config_cache import load_json_config
from src.v5.decision.watchlist import build_watchlist
from src.v5.reporting import build_report


def _players(n=700):
    positions = ["GK", "DEF", "MID", "FWD"]
    return [{"element":i,"name":f"P{i}","position":positions[i % 4],"team_id":(i % 20)+1,"now_cost":50+(i%50),"ownership_pct":5,"projection_confidence":"MEDIUM","xmins":{"start_probability":.88,"expected_minutes":78,"dnp_probability":.05},"role":{"confidence":.75},"current_season":{"expected_goals":.3,"expected_assists":.2},"historical_prior":{"minutes":2000,"xg_per90":.25,"xa_per90":.15,"set_piece_role":"some"},"xpts_5":20+(i%15),"xpts_15":60+(i%30)} for i in range(1,n+1)]


def test_watchlist_and_reporting_stay_within_advanced_alpha_budgets():
    budgets = load_json_config("config/v5_performance_budgets.json")["budgets"]
    prediction = {"players": _players(), "prediction_quality": {"status":"HEALTHY"}, "model_version":"perf"}
    team = {"team_value_ledger": [{"element": i} for i in range(1,16)], "authority":"user_lock"}
    started = perf_counter(); watchlist = build_watchlist(prediction, team); watch_ms = (perf_counter()-started)*1000
    assert watch_ms <= float(budgets["watchlist_700_players_ms"]), watch_ms
    decision = {"selected_package_id":"HOLD","selected_package":{"id":"HOLD"},"ruleset_id":"FPL_2026_27","model":"perf","decision_trace":{"confidence":"MEDIUM"},"watchlist":watchlist,"lineup":{"formation":"3-4-3","starting_xi":[{"element":i} for i in range(1,12)],"bench":[],"captain":{"element":3,"start_probability":.9,"expected_minutes":80},"vice_captain":{"element":4},"captain_safe_pool":[{"captain_score":6},{"captain_score":5}],"main_starting_xi_battle":{"status":"CLEAR","margin":1.0}}}
    payload = {"decision":decision,"truth":{"team":team},"prediction":prediction,"price":{},"governance":{"overall":"GREEN","go_allowed":True}}
    started = perf_counter(); build_report(payload); report_ms = (perf_counter()-started)*1000
    assert report_ms <= float(budgets["reporting_build_ms"]), report_ms
