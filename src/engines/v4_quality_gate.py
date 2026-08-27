from __future__ import annotations

import json
import statistics
from pathlib import Path

from src.engines.reliability import validate_snapshot
from src.services.contracts import file_digest
from src.utils import DATA


def _load(name: str) -> dict:
    path = DATA / name
    if not path.exists():
        raise AssertionError(f"missing required quality-gate input: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _assert_version(obj: dict, label: str, minimum: int, prefix: str, field: str = "engine") -> None:
    actual_schema = int(obj.get("schema_version", 0))
    actual_version = str(obj.get(field, ""))
    if actual_schema < minimum or not actual_version.startswith(prefix):
        raise AssertionError(
            f"stale or incompatible {label}: schema={actual_schema}, {field}={actual_version!r}; "
            f"expected schema>={minimum} and {field} prefix {prefix!r}. "
            "Run `python -m src.services.orchestrator daily --stats --deep-stats` "
            "before invoking the quality gate."
        )


def _assert_framework_health() -> tuple[dict, dict]:
    pre = _load("framework_health_preflight_v4.json")
    post = _load("framework_health_v4.json")

    for obj, phase in ((pre, "preflight"), (post, "postflight")):
        _assert_version(obj, f"{phase} framework health", 492, "v4.9.2-truthful-health")
        assert obj.get("phase") == phase, obj
        assert obj.get("registry_integrity") is True, obj
        assert obj.get("overall") == obj.get("pipeline_health"), obj
        assert obj.get("pipeline_health") in {"GREEN", "AMBER"}, obj
        assert obj.get("prediction_health") in {"GREEN", "AMBER"}, obj
        assert obj.get("capability_health") in {"GREEN", "AMBER"}, obj
        assert obj.get("recommendation_allowed") is True, obj
        assert obj.get("go_allowed") is (
            obj.get("pipeline_health") == "GREEN" and obj.get("prediction_health") == "GREEN"
        ), obj
        assert obj.get("gate0", {}).get("pass") is True, obj.get("gate0")
        assert obj.get("gate0", {}).get("counts", {}).get("FAIL", 0) == 0, obj.get("gate0")
        assert obj.get("dss_core", {}).get("declared") == 50 and obj["dss_core"].get("integrity_ok") is True
        assert obj.get("dss_extensions", {}).get("declared") == 16 and obj["dss_extensions"].get("integrity_ok") is True
        assert obj.get("enhancements", {}).get("declared") == 8 and obj["enhancements"].get("integrity_ok") is True
        assert not obj.get("critical_failed"), obj.get("critical_failed")
        governance = obj.get("governance", {})
        assert governance.get("file_exists_is_not_sufficient_for_active") is True
        assert governance.get("critical_partial_blocks_unqualified_go") is True
        assert governance.get("critical_warmup_blocks_unqualified_go") is True
        assert governance.get("pipeline_health_separate_from_prediction_health") is True
        assert governance.get("noncritical_partial_is_reported_not_hidden") is True
        assert governance.get("checkpoint_freshness_policy_enforced") is True
        checkpoint = obj.get("checkpoint_context", {})
        assert checkpoint.get("policy_id") and checkpoint.get("max_snapshot_age_minutes", 0) > 0, checkpoint
        freshness = obj.get("data_freshness", {}).get("detail", {})
        assert freshness.get("checkpoint_policy_id") == checkpoint.get("policy_id"), freshness
        performance = obj.get("performance", {})
        assert performance.get("prediction_snapshot_reads") == 1
        assert performance.get("audit_scoped_cache") is True

    pre_counts = pre["gate0"]["counts"]
    assert pre_counts.get("PASS", 0) + pre_counts.get("DEFERRED", 0) == 16, pre_counts
    assert pre.get("governance", {}).get("preflight_defers_postflight_outputs") is True, pre

    post_counts = post["gate0"]["counts"]
    assert post_counts.get("PASS", 0) == 16 and post_counts.get("DEFERRED", 0) == 0, post_counts
    governance = post.get("governance", {})
    assert governance.get("health_check_must_precede_recommendation") is True
    assert governance.get("raw_optimizer_is_not_final_decision") is True
    assert governance.get("gate0_fail_blocks_go") is True

    core = {row["id"]: row for row in post["dss_core"]["items"]}
    for module_id in ("DSS-05", "DSS-35"):
        assert core[module_id]["status"] == "ACTIVE", core[module_id]
    for module_id in ("DSS-07", "DSS-09", "DSS-10", "DSS-11", "DSS-12", "DSS-13", "DSS-24"):
        assert core[module_id]["status"] == "ACTIVE", core[module_id]
    extensions = {row["id"]: row for row in post["dss_extensions"]["items"]}
    assert extensions["DSS-X12"]["status"] in {"WARMUP", "ACTIVE"}, extensions["DSS-X12"]
    enhancements = {row["id"]: row for row in post["enhancements"]["items"]}
    assert enhancements["ENH-01"]["status"] == "ACTIVE", enhancements["ENH-01"]
    assert post.get("pipeline_health") == "GREEN", post
    assert post.get("capability_coverage", {}).get("declared") == 74, post
    critical_warmup = list(post.get("critical_warmup") or [])
    if critical_warmup:
        assert post.get("prediction_health") == "AMBER", post
        assert post.get("decision_engine") == "PROVISIONAL", post
        assert post.get("go_allowed") is False, post
    else:
        assert post.get("prediction_health") == "GREEN", post
        assert post.get("decision_engine") == "HEALTHY", post
        assert post.get("go_allowed") is True, post

    return pre, post


def run() -> dict:
    pre, health = _assert_framework_health()

    latest = _load("latest.json")
    reliability = validate_snapshot(latest)
    assert reliability["ok"], reliability
    assert latest.get("schema_version", 0) >= 40
    _assert_version(latest, "latest snapshot", 492, "4.9.2-independent-services", field="engine_version")
    assert latest.get("meta", {}).get("simulation_never_authorizes_action") is True
    assert latest.get("meta", {}).get("service_contract_compatible") is True
    assert latest.get("meta", {}).get("service_boundaries_registry_driven") is True
    assert latest.get("checkpoint_context", {}).get("policy_id")
    assert latest.get("files", {}).get("gw_scorecard") == "data/gw_scorecard_v4.json"
    service_performance = latest.get("performance") or {}
    for field in ("raw_snapshot_ms", "enrichment_ms", "prediction_ms", "engine_before_snapshot_write_ms"):
        assert service_performance.get(field, 0) > 0, service_performance
    component_total = sum(service_performance[field] for field in ("raw_snapshot_ms", "enrichment_ms", "prediction_ms"))
    assert abs(component_total - service_performance["engine_before_snapshot_write_ms"]) < 0.02, service_performance

    orchestration = _load("service_orchestration_v4.json")
    _assert_version(orchestration, "service orchestration", 492, "v4.9.3-service-orchestrator")
    assert orchestration.get("status") == "PASS", orchestration
    assert orchestration.get("stats_enabled") is True and orchestration.get("deep_stats_enabled") is True, orchestration
    services = orchestration.get("services") or []
    assert len(services) == 10 and all(row.get("status") == "PASS" for row in services), services
    assert [row.get("id") for row in services[:4]] == ["raw_snapshot", "enrichment", "prediction", "validation_lifecycle"], services
    assert "personal_gw_scorecard" in [row.get("id") for row in services], services
    assert all(row.get("boundary_state") == "INDEPENDENT" for row in services), services
    assert all(all(contract.get("valid") for contract in row.get("contracts") or []) for row in services), services
    assert orchestration.get("snapshot_identity", {}).get("sha256") == file_digest(DATA / "runtime/snapshot.v1.json"), orchestration
    assert latest.get("lineage", {}).get("snapshot_sha256") == file_digest(DATA / "runtime/snapshot.v1.json")
    assert latest.get("lineage", {}).get("enrichment_sha256") == file_digest(DATA / "runtime/enrichment.v1.json")
    og = orchestration.get("guardrails") or {}
    assert og.get("official_fpl_api_authority") == "raw_snapshot_only" and og.get("services_may_not_refetch_snapshot")
    assert og.get("validation_lifecycle_no_official_refetch") is True
    assert og.get("deadline_snapshot_immutable") and og.get("retroactive_snapshot_rejected")
    assert og.get("reconciliation_archive_immutable") and og.get("reconciliation_idempotent")
    assert og.get("health_view_current_model_only") is True
    assert og.get("personal_gw_scorecard_no_official_refetch") is True
    assert og.get("finished_gw_archive_immutable") is True
    assert og.get("scorecard_simulation_never_mutates_archive") is True
    assert og.get("scorecard_projection_from_lineup_contract") is True
    assert og.get("appearance_formula_regression_tested") and og.get("prediction_quality_inputs_consumed")
    assert og.get("truthful_competition_evidence") and og.get("critical_warmup_blocks_unqualified_go")
    assert og.get("optimizer_search_width_unchanged")
    assert og.get("gate0_checks_unchanged") == 16

    lifecycle = _load("validation/lifecycle_v4.json")
    _assert_version(lifecycle, "validation lifecycle", 493, "v4.9.3-validation-lifecycle")
    assert lifecycle.get("status") == "PASS", lifecycle
    lifecycle_guardrails = lifecycle.get("guardrails") or {}
    assert lifecycle_guardrails.get("raw_snapshot_only") is True
    assert lifecycle_guardrails.get("official_api_refetch") is False
    assert lifecycle_guardrails.get("retroactive_snapshot_rejected") is True
    assert lifecycle_guardrails.get("deadline_snapshot_immutable") is True
    assert lifecycle_guardrails.get("reconciliation_archive_immutable") is True
    assert lifecycle_guardrails.get("reconciliation_idempotent") is True
    assert lifecycle_guardrails.get("health_view_current_model_only") is True
    assert lifecycle_guardrails.get("simulation_never_mutates_store") is True

    compliance = _load("compliance_audit.json")
    assert compliance.get("overall") == "PASS", compliance

    predictions = _load("predictions_v4.json")
    players = predictions.get("players", [])
    coverage = predictions.get("input_coverage", {})
    _assert_version(predictions, "predictions", 492, "v4.9.2-truthful-health", field="model_version")
    assert predictions.get("point_in_time") is True and len(players) >= 500, predictions
    assert lifecycle.get("eligibility", {}).get("model_version") == predictions.get("model_version"), lifecycle
    eligible_samples = lifecycle.get("eligibility", {}).get("eligible_samples")
    if eligible_samples is not None:
        eligible_samples = int(eligible_samples)
        core = {row["id"]: row for row in health["dss_core"]["items"]}
        extensions = {row["id"]: row for row in health["dss_extensions"]["items"]}
        if eligible_samples == 0:
            assert core["DSS-44"]["status"] == "WARMUP", core["DSS-44"]
            assert extensions["DSS-X12"]["status"] == "WARMUP", extensions["DSS-X12"]
        else:
            assert core["DSS-44"]["status"] == "ACTIVE", core["DSS-44"]
            assert extensions["DSS-X12"]["status"] == "ACTIVE", extensions["DSS-X12"]
    assert coverage.get("advanced_matched", 0) > 0 and coverage.get("last_season_matched", 0) > 0, coverage
    assert 0 <= coverage.get("advanced_materially_distinct", -1) <= coverage.get("advanced_matched", 0), coverage
    assert coverage.get("advanced_decision_used_ratio", 0) >= .25, coverage
    assert predictions.get("capability_evidence", {}).get("dynamic_opponent_fixtures", 0) > 0
    competition_evidence = predictions.get("capability_evidence", {})
    assert 0 < competition_evidence.get("role_competition_adjustments", 0) < len(players), competition_evidence
    assert competition_evidence.get("role_competition_factor_variants", 0) > 1, competition_evidence

    wc = _load("wc_decision_v4.json")
    _assert_version(wc, "WC decision", 492, "v4.9.2-wc-optimizer-truthful-health")
    assert wc.get("screened_players", 0) >= 500 and len(wc.get("optimized_elements", [])) == 15
    assert wc.get("classification") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    wp = wc.get("performance", {})
    assert wp.get("fast_finalist_scoring") and wp.get("winner_only_legality_check")
    assert wp.get("beam_size_unchanged") and wp.get("packed_club_signature") and wp.get("counter_copy_eliminated")
    assert wp.get("direct_challenger_position_index")
    assert wp.get("value_term_consumed")
    assert wp.get("precomputed_club_bits") and wp.get("bounded_top_k_same_beam")
    wa = wc.get("affordability", {})
    assert wa.get("price_basis") == "owned_sell_cost_unowned_now_cost", wa
    assert wc.get("budget_tenths") == wa.get("available_budget_tenths"), wa

    packages = _load("wc_package_audit_v4.json")
    assert int(packages.get("schema_version", 0)) >= 472, packages
    assert str(packages.get("engine", "")).startswith("v4.7.2-wc-package-audit-performance-hotfix"), packages
    assert packages.get("max_replacements") == 4
    assert set(packages.get("best_by_replacement_count", {})) == {"1", "2", "3", "4"}
    assert packages.get("overall_verdict") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    assert packages.get("guardrails", {}).get("risk_penalty_enabled") is True
    assert packages.get("guardrails", {}).get("search_width_unchanged") is True
    pp = packages.get("performance", {})
    assert pp.get("metrics_cache_entries", 0) > 0
    assert pp.get("single_pass_metrics") and pp.get("compact_target_cache") and pp.get("score_only_hotloop")
    assert pp.get("redundant_target_validation_removed") and pp.get("candidate_reuse_supported")
    assert pp.get("packed_club_signature") and pp.get("top_packages_only_payload_materialization")
    pa = packages.get("affordability", {})
    assert pa.get("price_basis") == "owned_sell_cost_unowned_now_cost", pa
    assert packages.get("guardrails", {}).get("budget_tenths") == pa.get("available_budget_tenths"), pa

    lineup = _load("lineup_decision_v4.json")
    assert int(lineup.get("schema_version", 0)) >= 452, lineup
    assert str(lineup.get("engine", "")).startswith("v4.5.2-lineup-robust-governance"), lineup
    assert len(lineup.get("starting_xi", [])) == 11
    assert lineup.get("formation") in {"3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"}
    xi_ids = {x["element"] for x in lineup["starting_xi"]}
    captain_id = lineup["captain"]["element"]
    vice_id = lineup["vice_captain"]["element"]
    assert captain_id in xi_ids and vice_id in xi_ids and captain_id != vice_id
    assert len(lineup.get("bench", {}).get("order", [])) == 3 and lineup.get("bench", {}).get("gk")
    assert lineup.get("chip_context", {}).get("single_chip_rule_respected") is True
    lg = lineup.get("guardrails", {})
    assert lg.get("captain_risk_adjusted") and lg.get("captain_safe_pool_preferred")
    assert lg.get("manual_draft_not_overwritten_without_margin") and lg.get("prediction_interval_robustness")
    assert lineup.get("governance", {}).get("decision") in {"OPTIMIZER_ONLY", "HOLD_MANUAL_DRAFT", "CHANGE_RECOMMENDED"}

    scorecard = _load("gw_scorecard_v4.json")
    _assert_version(scorecard, "personal GW scorecard", 494, "v4.9.4-personal-gw-scorecard")
    assert scorecard.get("status") == "PASS", scorecard
    assert scorecard.get("snapshot_sha256") == file_digest(DATA / "runtime/snapshot.v1.json"), scorecard
    scg = scorecard.get("guardrails") or {}
    assert scg.get("raw_snapshot_only") is True and scg.get("official_api_refetch") is False
    assert scg.get("process_isolated_microservice") is True
    assert scg.get("finished_gw_archive_immutable") is True
    assert scg.get("simulation_never_mutates_archive") is True
    assert scg.get("projection_from_lineup_contract") is True
    assert scg.get("projection_is_estimate_not_actual") is True
    assert scg.get("player_intervals_not_naively_summed") is True
    assert (scorecard.get("archive") or {}).get("immutable") is True
    last_finished = (latest.get("phase") or {}).get("last_finished_gw")
    if last_finished and not latest.get("checkpoint_context", {}).get("is_simulation"):
        previous = scorecard.get("previous_gw") or {}
        assert previous.get("status") == "FINAL" and int(previous.get("gw") or 0) == int(last_finished), previous
        assert previous.get("net_points") is not None and previous.get("chip") is not None, previous
    planning_gw = (latest.get("phase") or {}).get("planning_gw")
    if planning_gw:
        planning = scorecard.get("planning_gw") or {}
        assert planning.get("status") == "PROJECTION" and int(planning.get("gw") or 0) == int(planning_gw), planning
        assert planning.get("estimated_points", 0) > 0 and planning.get("formation") == lineup.get("formation"), planning
        assert (planning.get("captain") or {}).get("element") == lineup.get("captain", {}).get("element"), planning
        assert (planning.get("uncertainty") or {}).get("player_intervals_not_naively_summed") is True, planning

    sanity = _load("recommendation_sanity_v4.json")
    assert int(sanity.get("schema_version", 0)) >= 460, sanity
    assert str(sanity.get("engine", "")).startswith("v4.6-evidence-fusion-sanity"), sanity
    assert sanity.get("point_in_time") is True
    assert sanity.get("final_verdict") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    sg = sanity.get("guardrails", {})
    assert sg.get("raw_optimizer_not_authoritative") and sg.get("rate_spike_detection")
    assert sg.get("team_cluster_penalty") and sg.get("outgoing_baseline_resistance")
    assert sg.get("early_season_multi_change_cap") and sg.get("point_in_time_required")

    pipeline = _load("decision_pipeline_v4.json")
    assert int(pipeline.get("schema_version", 0)) >= 473, pipeline
    assert str(pipeline.get("engine", "")).startswith("v4.7.3-unified-decision-pipeline-checkpoint-aware"), pipeline
    assert pipeline.get("checkpoint_context") == latest.get("checkpoint_context"), pipeline
    pg = pipeline.get("performance_guardrails", {})
    assert pg.get("shared_json_loaded_once") and pg.get("shared_candidates_built_once")
    assert pg.get("fork_copy_on_write") and pg.get("parallel_wc_package")
    assert pg.get("search_quality_reduction") is False
    assert pg.get("wc_beam_unchanged") and pg.get("package_frontier_beam_unchanged")
    assert pg.get("bounded_top_k_same_wc_beam") and pg.get("top_packages_only_payload_materialization")
    assert pg.get("checkpoint_action_deferred_until_postflight_health") is True
    timings = pipeline.get("timings", {})
    assert timings.get("total_pipeline_ms", 0) > 0

    checkpoint = _load("checkpoint_decision_v4.json")
    _assert_version(checkpoint, "checkpoint decision", 492, "v4.9.2-checkpoint-governance")
    assert checkpoint.get("checkpoint_context") == latest.get("checkpoint_context"), checkpoint
    action = checkpoint.get("action_state")
    assert action in {"HOLD", "REVIEW_REQUIRED", "GO", "EMERGENCY_UPDATE_ONLY", "REFRESH_REQUIRED", "BLOCKED", "SIMULATION_ONLY"}, checkpoint
    assert checkpoint.get("decision", {}).get("execution_authorized") is (action == "GO"), checkpoint
    guardrails = checkpoint.get("guardrails", {})
    assert guardrails.get("simulation_never_authorizes_action") is True
    assert guardrails.get("freshness_failure_blocks_action") is True
    assert guardrails.get("locked_15_separate_from_lineup_lock") is True
    assert guardrails.get("scorecard_is_reporting_only") is True
    checkpoint_scorecard = checkpoint.get("personal_gw_scorecard") or {}
    assert (checkpoint_scorecard.get("previous_gw") or {}).get("status") == (scorecard.get("previous_gw") or {}).get("status")
    assert (checkpoint_scorecard.get("planning_gw") or {}).get("status") == (scorecard.get("planning_gw") or {}).get("status")
    assert checkpoint_scorecard.get("headline") == scorecard.get("headline")
    if latest.get("checkpoint_context", {}).get("is_simulation"):
        assert action == "SIMULATION_ONLY", checkpoint
    if health.get("prediction_health") == "AMBER" and not latest.get("checkpoint_context", {}).get("is_simulation"):
        assert action == "HOLD", checkpoint

    all_x: list[float] = []
    strong_direct_evidence: list[float] = []
    no_direct_evidence: list[float] = []
    for row in players:
        assert len(row.get("fixtures", [])) <= 15 and row.get("xpts_5", 0) >= 0
        for fx in row.get("fixtures", []):
            x = fx["xpts"]
            all_x.append(x)
            assert 0 <= x < 25
            assert fx["components"].get("defcon", 0) <= 2.001
            if row.get("position") == "GK":
                assert fx["components"].get("defcon", 0) == 0
            assert fx["lower80"] <= x <= fx["upper80"]
            calibration = fx.get("calibration", {})
            provenance = fx.get("provenance", {})
            for field in ("nailed_prior", "current_start_rate", "current_minutes_rate", "competition_pressure", "set_piece_order_weight", "penalty_order_weight", "last_season_weight", "opponent_defence_resistance"):
                assert field in calibration, (row.get("element"), field)
            assert provenance.get("xmins_prior_source")
            assert provenance.get("set_piece_source") == "bayesian_official_order_plus_deep_events"
            assert provenance.get("role_scoring_mode") == "prior_reallocation_no_direct_double_count"
            assert calibration.get("set_piece_share") is not None and calibration.get("penalty_share") is not None
            assert str(provenance.get("opponent_defence_source", "")).startswith("official_fpl_")
            xm = fx["xmins"]
            assert abs(xm["start_probability"] + xm["bench_probability"] + xm["dnp_probability"] - 1) < 0.002
        if row.get("fixtures"):
            calibration = row["fixtures"][0]["calibration"]
            xm = row["fixtures"][0]["xmins"]
            priors = row.get("priors") or {}
            if xm.get("availability_probability", 0) >= .99 and calibration.get("nailed_prior", 0) >= .8 and calibration.get("current_start_rate", 0) >= .8:
                strong_direct_evidence.append(xm["start_probability"])
            if (
                xm.get("availability_probability", 0) >= .99
                and not priors.get("prior_season_available")
                and calibration.get("current_start_rate", 0) == 0
                and calibration.get("current_minutes_rate", 0) == 0
            ):
                no_direct_evidence.append(xm["expected_minutes"])
    assert strong_direct_evidence and min(strong_direct_evidence) >= .75, strong_direct_evidence
    assert no_direct_evidence and max(no_direct_evidence) <= 22, no_direct_evidence
    assert all_x and statistics.median(all_x) < 8
    assert sum(x > 15 for x in all_x) / len(all_x) < 0.03

    out = {
        "health": health["overall"],
        "preflight_gate0": pre["gate0"]["counts"],
        "postflight_gate0": health["gate0"]["counts"],
        "dss50": health["dss_core"]["counts"],
        "extensions": health["dss_extensions"]["counts"],
        "enhancements": health["enhancements"]["counts"],
        "recommendation": sanity["final_verdict"],
        "lineup_governance": lineup["governance"]["decision"],
        "formation": lineup["formation"],
        "captain": lineup["captain"]["name"],
        "previous_gw": (scorecard.get("headline") or {}).get("previous"),
        "planning_gw": (scorecard.get("headline") or {}).get("planning"),
        "checkpoint": checkpoint["checkpoint_context"]["policy_id"],
        "action": checkpoint["action_state"],
        "services": len(services),
        "eligible_calibration_samples": lifecycle.get("eligibility", {}).get("eligible_samples"),
        "orchestration_ms": orchestration.get("duration_ms"),
        "pipeline_ms": timings["total_pipeline_ms"],
    }
    print("V4.9.4 PERSONAL-GW-SCORECARD SERVICE GATE PASS", json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
