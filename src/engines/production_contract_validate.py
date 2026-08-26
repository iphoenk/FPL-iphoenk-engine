from __future__ import annotations

import json
from pathlib import Path

from src.engines.reliability import validate_snapshot
from src.rules import RULESET_ID, active_ruleset_fingerprint
from src.utils import DATA
from src.version import ENGINE_VERSION, SCHEMA_VERSION


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def run() -> dict:
    s = load("latest.json")
    p = load("prices.json")
    c = load("chips.json")
    d = load("official_detail.json")
    a = load("auth.json")
    t = load("price_trajectory.json")
    pa = load("price_alerts.json")
    rr = load("rules_compliance.json")
    fh = load("framework_health.json")
    u = load("universe.json")
    ts = load("team_strength.json")
    pr = load("projections.json")
    po = load("package_optimizer.json")
    pe = load("prediction_accuracy.json")
    pl = load("prediction_ledger.json")
    cs = load("challenger_scorecard.json")
    rp = load("runtime_performance.json")
    prior = load("prior_season.json")
    pq = load("prediction_quality.json")
    lineup = load("lineup_decision.json")
    package = load("package_decision.json")
    user = load("user_report.json")
    tech = load("technical_appendix.json")
    report_state = load("report_state.json")

    assert s["engine_version"] == ENGINE_VERSION
    assert s["schema_version"] == SCHEMA_VERSION
    runtime = s.get("runtime_architecture", {})
    assert runtime.get("id") == "v3-bounded-process-microservices-v1", runtime
    assert runtime.get("architecture") == "V3_BOUNDED_PROCESS_MICROSERVICES"
    assert runtime.get("dependency_aware_scheduling") is True
    assert runtime.get("shared_official_cache") is True
    assert s.get("files", {}).get("runtime_performance") == "data/runtime_performance.json"
    assert rp.get("architecture") == "V3_BOUNDED_PROCESS_MICROSERVICES"
    assert rp.get("shared_official_cache_entries", 0) > 0
    assert all(x.get("status") == "SUCCESS" for x in rp.get("services", {}).values()), rp

    assert s.get("snapshot_id")
    assert s.get("native", {}).get("entry")
    assert s.get("provenance", {}).get("entry", {}).get("source") == "official_fpl"
    assert s.get("ruleset", {}).get("id") == RULESET_ID
    assert s.get("ruleset", {}).get("fingerprint_sha256") == active_ruleset_fingerprint()
    assert (s.get("ruleset", {}).get("goal_points", {}).get("1") == 10 or s.get("ruleset", {}).get("goal_points", {}).get(1) == 10)
    assert s.get("chip_ledger", {}).get("ruleset_id") == RULESET_ID
    assert c.get("ruleset_id") == RULESET_ID
    assert rr.get("overall") == "PASS", rr
    assert rr.get("ruleset_id") == RULESET_ID
    assert rr.get("registry_integrity", {}).get("status") == "PASS"
    assert rr.get("ruleset_fingerprint_sha256") == active_ruleset_fingerprint()
    assert rr.get("governance", {}).get("remote_change_never_auto_mutates_rules") is True

    assert s.get("price_summary", {}).get("filter_policy", {}).get("min_ownership_pct") == 0.5
    assert all(x.get("ownership_pct", 0) >= 0.5 and abs(x.get("net_transfers", 0)) >= 5000 for x in p.get("top_buy_pressure", []))
    assert all(x.get("ownership_pct", 0) >= 0.5 and abs(x.get("net_transfers", 0)) >= 5000 for x in p.get("top_sell_pressure", []))
    assert p.get("official_price_predictor_health", {}).get("status") == "LIVE"
    assert p.get("players")
    assert any(x.get("official_progress_pct") is not None for x in p.get("players", []))
    assert s.get("price_summary", {}).get("trajectory_features", {}).get("predicted_change_date") is True
    assert s.get("price_summary", {}).get("trajectory_features", {}).get("acceleration_deceleration") is True
    assert t.get("players")
    assert pa.get("policy", {}).get("watch_capacity") == 50

    ods = s.get("official_detail_summary", {})
    assert ods.get("detail_requested", 0) >= 15
    assert d.get("owned_element_ids")
    assert d.get("official_health", {}).get("element_summary", {}).get("requested", 0) >= 15
    assert "fixture_stats" in d and "event_live_rich" in d and "dream_team" in d

    auth = s.get("authenticated_official", {})
    assert auth == a
    assert auth.get("state") in {"DISABLED", "MISCONFIGURED", "VALID", "EXPIRED_OR_REJECTED", "UNAVAILABLE", "ENTRY_MISMATCH", "PARTIAL", "PARTIAL_AUTH_REJECTED", "POLICY_BLOCKED"}
    assert auth.get("raw_authenticated_payload_persisted") is False
    assert auth.get("policy", {}).get("resource_methods") == ["GET"]

    assert ts.get("teams") and ts.get("matchups")
    assert len(ts.get("teams", [])) == len({x.get("team_id") for x in u.get("players", [])})
    assert len(pr.get("players", [])) == len(u.get("players", []))
    assert pr.get("horizon_gws") == 15
    assert pr.get("historical_prior_model")
    assert int(pr.get("historical_prior_players_used") or 0) > 0
    for row in pr.get("players", []):
        xm = row.get("xmins", {})
        prob = sum(float(xm.get(k, 0)) for k in ("start_probability", "bench_probability", "dnp_probability"))
        assert abs(prob - 1.0) < 0.002
        assert len(row.get("xpts_by_gw", [])) == 15
        assert len(xm.get("expected_minutes_interval", [])) == 2

    assert prior.get("players")
    assert float((prior.get("coverage") or {}).get("coverage_ratio") or 0) > 0
    assert prior.get("governance", {}).get("stable_player_code_is_primary_identity") is True
    assert pq.get("status") in {"HEALTHY", "DEGRADED"}
    assert pq.get("checks")
    assert pq.get("governance", {}).get("mechanical_validity_is_not_prediction_quality") is True

    assert po.get("status") == "READY", po
    assert po.get("gate0_prevalidated") is True
    assert po.get("hold", {}).get("legal") is True
    assert po.get("hold", {}).get("score", {}).get("valid") is True
    assert set(po.get("candidate_pool", {})) == {"GK", "DEF", "MID", "FWD"}
    assert po.get("governance", {}).get("final_go_requires_framework_governance_and_postflight_gate0") is True
    assert package.get("gate0_revalidated") is True
    assert lineup.get("main_starting_xi_battle") is not None
    assert lineup.get("captain") and lineup.get("vice_captain")

    assert pe.get("freeze_policy") == "last_pre_deadline_snapshot"
    assert isinstance(pl.get("records"), dict) and pl.get("records")
    assert pe.get("governance", {}).get("accuracy_claim_requires_settled_sample") is True
    provider_ids = {x.get("id") for x in cs.get("providers", [])}
    assert provider_ids == {"internal", "onefpl", "fffix", "ffhub"}
    assert cs.get("auto_scrape") is False
    assert cs.get("governance", {}).get("missing_provider_data_is_not_fabricated") is True

    assert fh.get("framework_schema") >= 3
    assert fh.get("registry_integrity") is True
    assert fh.get("rules_registry", {}).get("status") == "PASS"
    assert fh.get("gate0", {}).get("ruleset_id") == RULESET_ID
    assert fh.get("gate0", {}).get("counts", {}).get("FAIL", 0) == 0
    assert fh.get("dss_core", {}).get("declared") == 50
    assert fh.get("dss_extensions", {}).get("declared") == 16
    assert fh.get("enhancements", {}).get("declared") == 8
    assert fh.get("governance", {}).get("file_exists_is_not_sufficient_for_active") is True
    assert fh.get("governance", {}).get("rules_registry_precedes_gate0") is True
    assert fh.get("governance", {}).get("gate0_consumes_active_ruleset") is True
    assert fh.get("governance", {}).get("gate0_fail_blocks_go") is True
    assert fh.get("governance", {}).get("mechanical_gate0_pass_does_not_imply_prediction_quality") is True
    p0 = fh.get("p0_capabilities", {})
    assert p0.get("P0-1_prediction_calibration_backtest", {}).get("status") == "ACTIVE"
    assert p0.get("P0-2_xmins_role_v2", {}).get("status") in {"ACTIVE", "PARTIAL"}
    assert p0.get("P0-3_team_strength_fixture_probability", {}).get("status") == "ACTIVE"
    assert p0.get("P0-4_multi_horizon_package_optimizer", {}).get("status") == "ACTIVE"
    assert p0.get("P0-5_external_challenger_scorecard", {}).get("status") in {"ACTIVE", "PARTIAL"}
    assert fh.get("overall") in {"GREEN", "AMBER"}

    assert list(user)[0] == "decision"
    assert user.get("decision", {}).get("overall") in {"HOLD", "CHANGE", "REVIEW"}
    assert user.get("report_mode") in {"COMPACT_STABLE", "FULL_OR_DELTA"}
    assert len(user.get("action_board") or []) <= 8
    assert user.get("horizon_policy") == {"primary": [3, 5], "strategic": [10, 15]}
    assert (user.get("external_watchlist") or {}).get("status") in {"READY", "INSUFFICIENT_EVIDENCE"}
    serialized_user = json.dumps(user, ensure_ascii=False)
    for token in ("go_allowed", "SUSPECT_STATIC_OFFSET0", "DSS-", "Gate 0", "epistemik", "asset-value protection"):
        assert token not in serialized_user
    assert tech.get("framework_health", {}).get("gate0") is not None
    assert tech.get("framework_health", {}).get("dss_core") is not None
    assert tech.get("audit", {}).get("facts_models_decisions_separated") is True
    assert report_state.get("fingerprint") and report_state.get("state")
    assert s.get("report_summary", {}).get("model") == "decision_first_report_v1"
    assert s.get("files", {}).get("user_report") == "data/user_report.json"
    assert s.get("files", {}).get("technical_appendix") == "data/technical_appendix.json"

    reliability = validate_snapshot(s)
    if not reliability["ok"]:
        raise AssertionError(reliability)
    summary = {
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "runtime_ms": rp.get("total_wall_ms"),
        "framework": fh.get("overall"),
        "prediction_quality": pq.get("status"),
        "report_decision": user.get("decision", {}).get("overall"),
        "report_mode": user.get("report_mode"),
        "gate0": fh.get("gate0", {}).get("counts"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    run()
