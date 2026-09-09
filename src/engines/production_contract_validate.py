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


def _validate_official_runtime_evidence(runtime_performance: dict) -> None:
    """Require real Official evidence reuse, not an HTTP-cache occupancy proxy."""
    services = runtime_performance.get("services") or {}
    official = services.get("official_snapshot") or {}
    status = official.get("status")

    if status == "SUCCESS":
        # A cold/fresh run owns the Official network fetch and should populate the
        # single-run HTTP cache used by downstream Official requests.
        assert int(runtime_performance.get("shared_official_cache_entries") or 0) > 0, {
            "reason": "fresh_official_run_without_shared_http_cache",
            "official_snapshot": official,
        }
        return

    assert status == "REUSED", {
        "reason": "official_snapshot_neither_fresh_success_nor_governed_reuse",
        "official_snapshot": official,
    }
    assert runtime_performance.get("execution_profile") == "fast_decision", runtime_performance
    profile = runtime_performance.get("profile_config") or {}
    reuse_cfg = (profile.get("reuse_services") or {}).get("official_snapshot") or {}
    max_age = float(reuse_cfg.get("max_age_seconds") or 0)
    age = float(official.get("reuse_age_seconds") or 0)

    assert 0 < max_age <= 60.0, {"reason": "official_reuse_ttl_not_bounded", "config": reuse_cfg}
    assert 0.0 <= age <= max_age, {"reason": "official_reuse_stale", "age": age, "max_age": max_age}
    assert official.get("reuse_mode") == "AGE_TTL", official
    assert official.get("reuse_freshness_source") == "SEMANTIC_TIMESTAMP", official
    assert official.get("reuse_freshness_artifact") == "official_snapshot.json", official
    assert official.get("reuse_freshness_field") == "generated_at", official
    assert official.get("workspace_retry_restored") is True, official
    assert official.get("workspace_retry_artifact") == "official_snapshot.retry.json", official
    assert reuse_cfg.get("workspace_retry_artifact") == official.get("workspace_retry_artifact"), {
        "reason": "official_retry_mirror_not_profile_owned",
        "config": reuse_cfg,
        "official_snapshot": official,
    }
    assert official.get("artifact_validation"), {
        "reason": "official_reuse_without_artifact_validation",
        "official_snapshot": official,
    }


def _validate_runtime_architecture(snapshot_runtime: dict, runtime_performance: dict) -> None:
    domain_registry = load_config("config/runtime/execution_domains.json")
    canonical_phases = domain_registry.get("canonical_phases") or {}
    canonical_domains = [
        str(name)
        for phase_domains in canonical_phases.values()
        for name in (phase_domains or [])
    ]
    expected_domain_count = int(domain_registry.get("domain_count") or 0)
    expected_phase_count = int(domain_registry.get("phase_count") or 0)
    assert expected_domain_count == len(canonical_domains) > 0
    assert expected_phase_count == len(canonical_phases) > 0
    assert canonical_domains == list((domain_registry.get("domains") or {}).keys())

    capability_registry = load_config("config/v3_service_registry.json")
    expected_capability_count = len(capability_registry.get("services") or {})
    assert expected_capability_count > 0

    assert snapshot_runtime.get("id") == "v3-domain-pipeline-v2", snapshot_runtime
    assert snapshot_runtime.get("architecture") == "V3_CANONICAL_DOMAIN_PIPELINE", snapshot_runtime
    assert snapshot_runtime.get("dependency_aware_scheduling") is True
    assert snapshot_runtime.get("shared_official_cache") is True
    assert snapshot_runtime.get("shared_canonical_domain_workspace") is True
    assert snapshot_runtime.get("cross_capability_copy_promotion") is False
    assert int(snapshot_runtime.get("execution_domain_count") or 0) == expected_domain_count
    assert int(snapshot_runtime.get("execution_phase_count") or 0) == expected_phase_count
    assert int(snapshot_runtime.get("service_count") or 0) == expected_domain_count
    assert int(snapshot_runtime.get("capability_owner_count") or 0) == expected_capability_count

    assert runtime_performance.get("runtime_id") == "v3-domain-pipeline-v2", runtime_performance
    assert runtime_performance.get("architecture") == "V3_CANONICAL_DOMAIN_PIPELINE", runtime_performance
    assert int(runtime_performance.get("execution_domain_count") or 0) == expected_domain_count
    assert int(runtime_performance.get("execution_phase_count") or 0) == expected_phase_count
    assert int(runtime_performance.get("capability_owner_count") or 0) == expected_capability_count
    assert runtime_performance.get("cross_capability_copy_promotion") is False
    assert runtime_performance.get("canonical_domain_order") == canonical_domains, runtime_performance
    domains = runtime_performance.get("execution_domains") or {}
    assert set(domains) == set(canonical_domains), domains
    assert all((row or {}).get("status") == "SUCCESS" for row in domains.values())
    phase_results = runtime_performance.get("execution_phase_results") or {}
    assert list(phase_results) == list(canonical_phases)
    assert all((row or {}).get("status") == "SUCCESS" for row in phase_results.values())
    assert len(runtime_performance.get("services") or {}) == expected_capability_count


def _validate_price_predictor_contract(snapshot: dict, prices: dict, trajectory: dict, alerts: dict, watchlist: dict, price_policy: dict) -> None:
    market_policy = price_policy["market_filter"]
    serving_policy = price_policy["serving"]
    min_ownership = float(market_policy["minimum_ownership_pct"])
    min_abs_net = int(market_policy["minimum_abs_net_transfers"])

    assert snapshot.get("price_summary", {}).get("filter_policy", {}).get("min_ownership_pct") == min_ownership
    assert all(x.get("ownership_pct", 0) >= min_ownership and abs(x.get("net_transfers", 0)) >= min_abs_net for x in prices.get("top_buy_pressure", []))
    assert all(x.get("ownership_pct", 0) >= min_ownership and abs(x.get("net_transfers", 0)) >= min_abs_net for x in prices.get("top_sell_pressure", []))

    health = prices.get("official_price_predictor_health") or {}
    contract = prices.get("official_price_predictor_contract") or {}
    raw_contract = prices.get("official_predictor_raw_contract") or {}
    rows = list(prices.get("players") or [])

    health_status = str(health.get("status") or "")
    schema_invalid = int(health.get("schema_invalid_players") or 0)
    stale_players = int(health.get("stale_players") or 0)
    calibrating_players = int(health.get("calibrating_players") or 0)
    assert health_status in {"PASS", "PARTIAL"}, health
    assert health.get("source") == "OFFICIAL_FPL"
    assert health.get("auth_required") is False
    assert health.get("ui_scraping") is False
    assert health.get("dedicated_predictor_endpoint") is False
    assert health.get("threshold_is_official_rule") is False
    assert health.get("no_intra_cycle_crossing_eta") is True
    assert schema_invalid == 0
    assert stale_players == 0

    # Official FPL may explicitly mark individual predictor rows as CALIBRATING.
    # That is a valid, non-fabricated evidence state: the unavailable projection
    # must stay unavailable rather than being coerced to zero. Production may
    # therefore be PARTIAL only when calibration is the sole reason.
    if health_status == "PARTIAL":
        assert 0 < calibrating_players < len(rows), health
    else:
        assert calibrating_players == 0, health

    assert contract.get("model_id") == price_policy.get("model_id")
    assert contract.get("current_progress_field") == "price_change_percent"
    assert contract.get("projected_progress_field") == "price_change_projections"
    assert contract.get("likelihood_preserved_raw") is True
    assert contract.get("threshold_is_official_rule") is False
    assert contract.get("no_intra_cycle_crossing_eta") is True
    assert contract.get("official_update_clock") == "00:00 Europe/London"
    assert contract.get("display_timezone") == "Asia/Jakarta"

    assert raw_contract.get("source") == "OFFICIAL_FPL"
    assert raw_contract.get("endpoint") == "bootstrap-static/"
    assert raw_contract.get("field_names_preserved") is True
    assert raw_contract.get("auth_required") is False
    assert raw_contract.get("ui_scraping") is False

    assert rows
    assert all(row.get("element_id") is not None for row in rows)
    assert all(row.get("current_price") is not None for row in rows)
    assert all(row.get("ownership_percent") is not None for row in rows)
    assert all(row.get("source") == "OFFICIAL_FPL" for row in rows)
    assert any(row.get("current_progress_percent") is not None for row in rows)
    assert all("projection_offset_0_percent" in row and "projection_offset_0_likelihood" in row for row in rows)
    assert all(row.get("trajectory_eta_hours") is None for row in rows)
    assert all(row.get("trajectory_predicted_change_deadline") is None for row in rows)
    assert all(row.get("predicted_change_cycle") in {"NEXT_UPDATE", "PLUS_1_UPDATE", "PLUS_2_UPDATE", "NONE"} for row in rows)

    calibration_rows = [row for row in rows if row.get("evidence_state") == "CALIBRATING"]
    assert len(calibration_rows) == calibrating_players, {"health": health, "calibration_rows": len(calibration_rows)}
    assert all(row.get("price_change_calibrating") is True for row in calibration_rows)
    assert all(row.get("fallback_reason") == "CALIBRATING" for row in calibration_rows)
    assert all(row.get("confidence") == "MEDIUM" for row in calibration_rows)

    governance = snapshot.get("price_summary", {}).get("governance") or {}
    assert governance.get("likelihood_raw_only") is True
    assert governance.get("no_false_crossing_eta") is True
    assert governance.get("next_update_is_london_midnight_dst_safe") is True
    assert governance.get("confirmed_and_predicted_are_separate") is True

    assert trajectory.get("players")
    assert alerts.get("policy", {}).get("watch_capacity") == int(serving_policy["market_watch_capacity"])
    assert alerts.get("owned_price_radar_count") == int((alerts.get("policy") or {}).get("owned_coverage_required") or 15)
    assert all(row.get("source") == "OFFICIAL_FPL" for row in alerts.get("owned_price_radar") or [])

    price_evidence = watchlist.get("price_evidence_summary") or {}
    published = int(price_evidence.get("published_watchlist_rows") or 0)
    official = int(price_evidence.get("official_price_evidence_rows") or 0)
    assert published > 0
    assert official == published
    assert price_evidence.get("complete") is True


def run() -> dict:
    s = load("latest.json")
    p = load("prices.json")
    c = load("chips.json")
    d = load("official_detail.json")
    a = load("auth.json")
    t = load("price_trajectory.json")
    pa = load("price_alerts.json")
    dw = load("dss_watchlist.json")
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
    _validate_runtime_service_states(rp)
    _validate_official_runtime_evidence(rp)

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

    _validate_price_predictor_contract(s, p, t, pa, dw, price_policy)

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
    xmins_contract = (load_config("config/intelligence/xmins_v2.json").get("contract_validation") or {})
    probability_tolerance = float(xmins_contract["probability_sum_tolerance"])
    for row in pr.get("players", []):
        xm = row.get("xmins", {})
        prob = sum(float(xm.get(k, 0)) for k in ("start_probability", "bench_probability", "dnp_probability"))
        assert abs(prob - 1.0) < probability_tolerance
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
        "price_predictor": (p.get("official_price_predictor_health") or {}).get("status"),
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
