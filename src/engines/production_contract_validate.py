from __future__ import annotations

import json

from src.engines.reliability import validate_snapshot
from src.rules import RULESET_ID, active_ruleset_fingerprint
from src.settings import STRATEGIC_HORIZON_GWS
from src.utils import DATA, ROOT
from src.version import ENGINE_VERSION, SCHEMA_VERSION


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def load_config(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _validate_runtime_service_states(runtime_performance: dict) -> None:
    services = runtime_performance.get("services", {})
    reusable = set(((runtime_performance.get("profile_config") or {}).get("reuse_services") or {}).keys())
    for name, row in services.items():
        status = row.get("status")
        if status == "SUCCESS":
            continue
        if status == "REUSED":
            assert name in reusable, {"service": name, "reason": "reuse_not_declared_by_profile", "runtime": runtime_performance}
            assert row.get("artifact_validation"), {"service": name, "reason": "reused_without_artifact_validation", "runtime": runtime_performance}
            continue
        raise AssertionError({"service": name, "status": status, "runtime": runtime_performance})


def _validate_runtime_architecture(snapshot_runtime: dict, runtime_performance: dict) -> None:
    canonical_domains = [
        "official_state",
        "personal_team_state",
        "football_context",
        "market_context",
        "prediction",
        "squad_decision",
        "challenger_analysis",
        "framework_governance",
        "prediction_validation",
        "reporting",
        "serving",
    ]
    assert snapshot_runtime.get("id") == "v3-domain-pipeline-v2", snapshot_runtime
    assert snapshot_runtime.get("architecture") == "V3_CANONICAL_DOMAIN_PIPELINE", snapshot_runtime
    assert snapshot_runtime.get("dependency_aware_scheduling") is True
    assert snapshot_runtime.get("shared_official_cache") is True
    assert snapshot_runtime.get("shared_canonical_domain_workspace") is True
    assert snapshot_runtime.get("cross_capability_copy_promotion") is False
    assert int(snapshot_runtime.get("execution_domain_count") or 0) == 11
    assert int(snapshot_runtime.get("execution_phase_count") or 0) == 6
    assert int(snapshot_runtime.get("service_count") or 0) == 11
    assert int(snapshot_runtime.get("capability_owner_count") or 0) == 21

    assert runtime_performance.get("runtime_id") == "v3-domain-pipeline-v2", runtime_performance
    assert runtime_performance.get("architecture") == "V3_CANONICAL_DOMAIN_PIPELINE", runtime_performance
    assert int(runtime_performance.get("execution_domain_count") or 0) == 11
    assert int(runtime_performance.get("execution_phase_count") or 0) == 6
    assert int(runtime_performance.get("capability_owner_count") or 0) == 21
    assert runtime_performance.get("cross_capability_copy_promotion") is False
    assert runtime_performance.get("canonical_domain_order") == canonical_domains, runtime_performance
    domains = runtime_performance.get("execution_domains") or {}
    assert set(domains) == set(canonical_domains), domains
    assert all((row or {}).get("status") == "SUCCESS" for row in domains.values())
    phase_results = runtime_performance.get("execution_phase_results") or {}
    assert list(phase_results) == ["ACQUIRE", "ENRICH", "MODEL", "DECISION", "GOVERNANCE", "PUBLISH"]
    assert all((row or {}).get("status") == "SUCCESS" for row in phase_results.values())
    assert len(runtime_performance.get("services") or {}) == 21


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

    price_policy = load_config("config/intelligence/price_radar.json")
    challenger_registry = load_config("config/intelligence/challenger_registry.json")
    reporting = load_config("config/intelligence/reporting.json")
    dss_core = load_config("config/dss_core_registry.json")
    dss_extensions = load_config("config/dss_extension_registry.json")
    enhancements = load_config("config/enhancement_layers_registry.json")
    gate0_registry = load_config("config/gate0_registry.json")

    assert s["engine_version"] == ENGINE_VERSION
    assert s["schema_version"] == SCHEMA_VERSION
    runtime = s.get("runtime_architecture", {})
    _validate_runtime_architecture(runtime, rp)
    assert s.get("files", {}).get("runtime_performance") == "data/runtime_performance.json"
    assert rp.get("shared_official_cache_entries", 0) > 0
    _validate_runtime_service_states(rp)

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

    market_policy = price_policy["market_filter"]
    serving_policy = price_policy["serving"]
    min_ownership = float(market_policy["minimum_ownership_pct"])
    min_abs_net = int(market_policy["minimum_abs_net_transfers"])
    assert s.get("price_summary", {}).get("filter_policy", {}).get("min_ownership_pct") == min_ownership
    assert all(x.get("ownership_pct", 0) >= min_ownership and abs(x.get("net_transfers", 0)) >= min_abs_net for x in p.get("top_buy_pressure", []))
    assert all(x.get("ownership_pct", 0) >= min_ownership and abs(x.get("net_transfers", 0)) >= min_abs_net for x in p.get("top_sell_pressure", []))
    assert p.get("official_price_predictor_health", {}).get("status") == "LIVE"
    assert p.get("players")
    assert any(x.get("official_progress_pct") is not None for x in p.get("players", []))
    assert s.get("price_summary", {}).get("trajectory_features", {}).get("predicted_change_date") is True
    assert s.get("price_summary", {}).get("trajectory_features", {}).get("acceleration_deceleration") is True
    assert t.get("players")
    assert pa.get("policy", {}).get("watch_capacity") == int(serving_policy["market_watch_capacity"])

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
    assert int(pr.get("horizon_gws") or 0) == STRATEGIC_HORIZON_GWS
    assert pr.get("historical_prior_model")
    assert int(pr.get("historical_prior_players_used") or 0) > 0
    for row in pr.get("players", []):
        xm = row.get("xmins", {})
        prob = sum(float(xm.get(k, 0)) for k in ("start_probability", "bench_probability", "dnp_probability"))
        assert abs(prob - 1.0) < 0.002
        assert len(row.get("xpts_by_gw", [])) == STRATEGIC_HORIZON_GWS
        assert len(xm.get("expected_minutes_interval", [])) == 2

    assert prior.get("players")
    assert float((prior.get("coverage") or {}).get("coverage_ratio") or 0) > 0
    assert prior.get("governance", {}).get("stable_player_code_preferred") is True
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
    expected_provider_ids = {x.get("id") for x in challenger_registry.get("providers", []) if x.get("enabled", True)}
    assert provider_ids == expected_provider_ids
    assert cs.get("auto_scrape") is False
    assert cs.get("governance", {}).get("missing_provider_data_is_not_fabricated") is True

    assert fh.get("framework_schema") >= 3
    assert fh.get("registry_integrity") is True
    assert fh.get("rules_registry", {}).get("status") == "PASS"
    assert fh.get("gate0", {}).get("ruleset_id") == RULESET_ID
    assert fh.get("gate0", {}).get("counts", {}).get("FAIL", 0) == 0
    assert fh.get("gate0", {}).get("declared") == int(gate0_registry["expected_count"])
    assert fh.get("dss_core", {}).get("declared") == int(dss_core["expected_count"])
    assert fh.get("dss_extensions", {}).get("declared") == int(dss_extensions["expected_count"])
    assert fh.get("enhancements", {}).get("declared") == int(enhancements["expected_count"])
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
    assert user.get("decision", {}).get("overall") in set(reporting["decision_states"])
    assert user.get("report_mode") in {"COMPACT_STABLE", "FULL_OR_DELTA"}
    assert len(user.get("action_board") or []) <= int(reporting["action_board"]["max_items"])
    expected_horizon_policy = {
        "primary": list(reporting["governance"]["primary_horizon_gws"]),
        "strategic": list(reporting["governance"]["strategic_horizon_gws"]),
    }
    assert user.get("horizon_policy") == expected_horizon_policy
    assert (user.get("external_watchlist") or {}).get("status") in {"READY", "INSUFFICIENT_EVIDENCE"}
    serialized_user = json.dumps(user, ensure_ascii=False)
    for token in reporting["language"]["forbidden_user_report_tokens"]:
        assert token not in serialized_user
    assert tech.get("framework_health", {}).get("gate0") is not None
    assert tech.get("framework_health", {}).get("dss_core") is not None
    assert tech.get("audit", {}).get("facts_models_decisions_separated") is True
    assert report_state.get("fingerprint") and report_state.get("state")
    assert s.get("report_summary", {}).get("model") == reporting["model_id"]
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
        "execution_domains": rp.get("execution_domain_count"),
        "capability_owners": rp.get("capability_owner_count"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    run()
