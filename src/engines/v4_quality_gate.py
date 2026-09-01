from __future__ import annotations

import json
import statistics

from src.engines import v4_quality_gate_legacy as legacy
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA


def _assert_capability_lifecycle_state(post: dict) -> None:
    """Accept only the two governed calibration lifecycle states.

    DSS-44 and DSS-X12 start in WARMUP and promote together only after the
    existing immutable reconciliation gate succeeds.  This verifier must not
    freeze production permanently at the pre-promotion state.
    """
    coverage = post.get("capability_coverage") or {}
    critical_warmup = list(post.get("critical_warmup") or [])
    assert post.get("critical_partial") == []
    if critical_warmup:
        assert critical_warmup == ["DSS-44", "DSS-X12"]
        assert coverage == {
            "active": 72,
            "warmup": 2,
            "partial": 0,
            "failed": 0,
            "declared": 74,
            "active_ratio": 0.973,
        }
        assert post.get("capability_maturity") == "WARMUP"
        assert post.get("decision_engine") == "PROVISIONAL"
        assert post.get("go_allowed") is False
        return

    assert coverage == {
        "active": 74,
        "warmup": 0,
        "partial": 0,
        "failed": 0,
        "declared": 74,
        "active_ratio": 1.0,
    }
    assert post.get("capability_maturity") == "MATURE"
    assert post.get("decision_engine") == "HEALTHY"
    assert post.get("go_allowed") is True


def _assert_framework_health() -> tuple[dict, dict]:
    """Preserve fail-closed operational health while keeping lifecycle maturity separate."""
    pre = legacy._load("framework_health_preflight_v4.json")
    post = legacy._load("framework_health_v4.json")
    for obj, phase in ((pre, "preflight"), (post, "postflight")):
        legacy._assert_version(obj, phase, 492, f"v{legacy.RELEASE_VERSION}-truthful-health")
        assert obj.get("phase") == phase
        assert obj.get("registry_integrity") is True
        assert obj.get("overall") == obj.get("pipeline_health")
        assert obj.get("pipeline_health") in {"GREEN", "AMBER"}
        assert obj.get("prediction_health") in {"GREEN", "AMBER"}
        assert obj.get("capability_health") in {"GREEN", "AMBER"}
        assert obj.get("gate0", {}).get("pass") is True
        assert obj.get("gate0", {}).get("counts", {}).get("FAIL", 0) == 0
        assert obj.get("dss_core", {}).get("declared") == 50
        assert obj.get("dss_extensions", {}).get("declared") == 16
        assert obj.get("enhancements", {}).get("declared") == 8
        assert not obj.get("critical_failed")
        governance = obj.get("governance") or {}
        assert governance.get("file_exists_is_not_sufficient_for_active") is True
        assert governance.get("critical_warmup_blocks_unqualified_go") is True
        assert governance.get("pipeline_health_separate_from_prediction_health") is True
        assert obj.get("checkpoint_context", {}).get("policy_id")

    assert pre["gate0"]["counts"].get("PASS", 0) + pre["gate0"]["counts"].get("DEFERRED", 0) == 16
    assert post["gate0"]["counts"].get("PASS", 0) == 16
    assert post.get("pipeline_health") == "GREEN"
    assert post.get("capability_health") == "GREEN"
    assert post.get("prediction_health") == "GREEN"
    _assert_capability_lifecycle_state(post)
    maturity = post.get("maturity_reconciliation") or {}
    assert maturity.get("failed_proof_demotes_active_to_partial") is True
    assert set(maturity.get("active_modules") or []) == {
        "DSS-08", "DSS-09", "DSS-30", "DSS-31", "DSS-32",
        "DSS-33", "DSS-34", "DSS-36", "DSS-41",
    }
    plan_truth = post.get("gate0", {}).get("plan_authority_validation") or {}
    assert (plan_truth.get("engine_plan") or {}).get("legal") is True
    assert (plan_truth.get("effective_plan") or {}).get("legal") is True
    assert plan_truth.get("both_required") is True
    assert (post.get("governance") or {}).get("effective_plan_legality_enforced") is True
    assert (post.get("governance") or {}).get("engine_and_effective_plan_legality_reported_separately") is True
    assert (post.get("governance") or {}).get("official_fpl_first_when_available") is True

    official_first = post.get("official_fpl_first") or {}
    assert official_first.get("status") == "PASS"
    assert official_first.get("promoted_count", 0) >= 6
    assert set(official_first.get("promoted_modules") or []) >= {"DSS-18", "DSS-20", "DSS-21", "DSS-22", "DSS-23", "DSS-38"}
    assert official_first.get("ownership_eo_limitation_disclosed") is True
    assert official_first.get("external_schedule_limitation_disclosed") is True

    core = {row["id"]: row for row in post["dss_core"]["items"]}
    for module_id in ("DSS-18", "DSS-20", "DSS-21", "DSS-22", "DSS-23", "DSS-38"):
        assert core[module_id]["status"] == "ACTIVE", (module_id, core[module_id])
    for module_id in ("DSS-08", "DSS-09", "DSS-30", "DSS-31", "DSS-32", "DSS-33", "DSS-34", "DSS-36", "DSS-41"):
        assert core[module_id]["status"] == "ACTIVE", (module_id, core[module_id])
        assert (core[module_id].get("detail") or {}).get("implementation_state") == "ACTIVE"
    for module_id in ("DSS-30", "DSS-31", "DSS-32"):
        assert (core[module_id].get("detail") or {}).get("evidence_state") in {"VERIFIED", "EVIDENCE_GATED"}
    assert (core["DSS-34"].get("detail") or {}).get("evidence_state") in {"VERIFIED", "EVIDENCE_GATED"}
    ownership_detail = core["DSS-41"].get("detail") or {}
    assert ownership_detail.get("effective_ownership_available_from_official_fpl") is False
    assert ownership_detail.get("effective_ownership_state") == "OPTIONAL_EXTERNAL_ADVISORY"
    assert int(ownership_detail.get("ownership_rows") or 0) == int(ownership_detail.get("players") or 0) > 0

    critical_partial = list(post.get("critical_partial") or [])
    critical_warmup = list(post.get("critical_warmup") or [])
    if critical_partial:
        assert post.get("prediction_health") == "AMBER"
        assert post.get("decision_engine") == "DEGRADED"
        assert post.get("go_allowed") is False
    elif critical_warmup:
        assert post.get("prediction_health") == "GREEN"
        assert post.get("capability_health") == "GREEN"
        assert post.get("capability_maturity") == "WARMUP"
        assert post.get("decision_engine") == "PROVISIONAL"
        assert post.get("go_allowed") is False
    else:
        assert post.get("prediction_health") == "GREEN"
        assert post.get("decision_engine") == "HEALTHY"
    return pre, post


def _assert_competition_evidence(players: list[dict], evidence: dict) -> None:
    """Validate competition evidence without requiring an artificial mixed population.

    Every player must expose the competition inputs. Zero adjustments are valid only
    when the current data contains no governed competition/squad-depth pressure.
    Conversely, if pressure exists, at least one adjustment must be applied. It is
    legitimate for every player to receive a bounded adjustment when every team has
    non-zero squad-depth pressure, so the gate must not require an unadjusted player.
    """
    assert players
    priors = [row.get("priors") or {} for row in players]
    assert all("competition_factor" in row for row in priors)
    assert all("competition_pressure" in row for row in priors)
    assert all("squad_depth_pressure" in row for row in priors)
    assert all(0.72 <= float(row.get("competition_factor") or 0) <= 1.0 for row in priors)
    assert all(0.0 <= float(row.get("competition_pressure") or 0) <= 1.0 for row in priors)
    assert all(0.0 <= float(row.get("squad_depth_pressure") or 0) <= 0.3 for row in priors)

    adjustments = int(evidence.get("role_competition_adjustments", 0) or 0)
    variants = int(evidence.get("role_competition_factor_variants", 0) or 0)
    pressure_rows = sum(
        float(row.get("competition_pressure") or 0) > 0
        or float(row.get("squad_depth_pressure") or 0) > 0
        for row in priors
    )
    assert 0 <= adjustments <= len(players)
    assert variants >= 1
    if pressure_rows:
        assert adjustments > 0
    else:
        assert adjustments == 0
        assert variants == 1


def _assert_prediction_and_validation(health: dict) -> tuple[dict, dict]:
    lifecycle = legacy._load("validation/lifecycle_v4.json")
    readiness = legacy._load("validation/reconciliation_readiness_v4.json")
    predictions = legacy._load("predictions_v4.json")
    assert readiness.get("status") == "PASS"
    assert readiness.get("blockers") == []
    assert (readiness.get("checks") or {}).get("snapshot_integrity", {}).get("pass") is True
    assert (readiness.get("checks") or {}).get("ownership_chain", {}).get("pass") is True
    assert (readiness.get("guardrails") or {}).get("read_only_audit") is True
    assert (readiness.get("guardrails") or {}).get("official_api_refetch") is False
    assert (readiness.get("guardrails") or {}).get("reconciliation_truth_not_reimplemented") is True
    legacy._assert_version(lifecycle, "validation lifecycle", 4943, "v4.9.3-validation-lifecycle")
    legacy._assert_version(predictions, "predictions", 492, "v4.9.2-truthful-health", field="model_version")
    assert lifecycle.get("status") == "PASS"
    lifecycle_guardrails = lifecycle.get("guardrails") or {}
    assert lifecycle_guardrails.get("started_from_official_stats_starts_only") is True
    assert lifecycle_guardrails.get("minutes_never_infer_started") is True
    assert lifecycle_guardrails.get("missing_starts_excluded_from_start_brier") is True
    assert predictions.get("point_in_time") is True
    players = predictions.get("players") or []
    assert len(players) >= 500
    assert lifecycle.get("eligibility", {}).get("model_version") == predictions.get("model_version")
    core = {row["id"]: row for row in health["dss_core"]["items"]}
    extensions = {row["id"]: row for row in health["dss_extensions"]["items"]}
    assert core["DSS-16"]["status"] == "ACTIVE", core["DSS-16"]
    assert core["DSS-29"]["status"] == "ACTIVE", core["DSS-29"]
    eligible = lifecycle.get("eligibility", {}).get("eligible_samples")
    if eligible is not None:
        if int(eligible) == 0:
            assert core["DSS-44"]["status"] == "WARMUP"
            assert extensions["DSS-X12"]["status"] == "WARMUP"
        else:
            assert core["DSS-44"]["status"] == "ACTIVE"
            assert extensions["DSS-X12"]["status"] == "ACTIVE"
    coverage = predictions.get("input_coverage") or {}
    assert coverage.get("advanced_matched", 0) > 0
    assert coverage.get("last_season_matched", 0) > 0
    assert coverage.get("advanced_decision_used_ratio", 0) >= 0.25
    evidence = predictions.get("capability_evidence") or {}
    assert evidence.get("dynamic_opponent_fixtures", 0) > 0
    _assert_competition_evidence(players, evidence)
    fixture_run_complete = sum(
        (row.get("fixture_run") or {}).get("source") == "official_fpl_fixture_adjustment"
        and (row.get("fixture_run") or {}).get("decision_usage") == "multi_horizon_projection_context"
        for row in players
    )
    assert fixture_run_complete == len(players)
    all_x = [fx["xpts"] for row in players for fx in row.get("fixtures", [])]
    assert all_x and statistics.median(all_x) < 8
    assert sum(x > 15 for x in all_x) / len(all_x) < 0.03
    return lifecycle, predictions


def _assert_orchestration(latest: dict) -> tuple[dict, list[dict]]:
    """Validate the simplified execution topology without weakening other gates."""
    orchestration = legacy._load("service_orchestration_v4.json")
    legacy._assert_version(orchestration, "orchestration", 496, "v4.9.6-service-orchestrator-8-boundary")
    assert orchestration.get("status") == "PASS"
    assert orchestration.get("stats_enabled") is True
    assert orchestration.get("deep_stats_enabled") is True
    assert orchestration.get("execution_model") == "process_isolated_dag_parallel_single_host"

    services = orchestration.get("services") or []
    ids = [row.get("id") for row in services]
    registry = json.loads((CONFIG / "service_registry.json").read_text(encoding="utf-8"))
    expected_ids = [row.get("id") for row in registry.get("services") or []]
    assert expected_ids == ["raw_snapshot", "enrichment", "prediction", "validation", "optimization", "user_decision_overlay", "personal_gw_scorecard", "governance"]
    assert len(services) == len(expected_ids) == 8
    assert set(ids) == set(expected_ids), (ids, expected_ids)
    assert all(row.get("status") == "PASS" for row in services), services
    assert all(row.get("boundary_state") == "INDEPENDENT" for row in services)
    assert all(all(contract.get("valid") for contract in row.get("contracts") or []) for row in services)

    assurance = orchestration.get("startup_assurance") or {}
    assert assurance.get("service") == "architecture_guard"
    assert assurance.get("status") == "PASS"
    assert assurance.get("runtime_microservice") is False
    assert "architecture_guard" not in ids

    levels = orchestration.get("execution_levels") or []
    assert levels and levels[0] == ["raw_snapshot"]
    level_index = {service_id: idx for idx, level in enumerate(levels) for service_id in level}
    for row in registry.get("services") or []:
        for dependency in row.get("depends_on") or []:
            assert level_index[dependency] < level_index[row["id"]], (dependency, row["id"], levels)
    assert level_index["validation"] == level_index["optimization"]
    assert level_index["governance"] > level_index["validation"]
    assert level_index["governance"] > level_index["personal_gw_scorecard"]

    summary = orchestration.get("summary") or {}
    assert summary.get("services_passed") == 8
    assert summary.get("services_total") == 8
    assert summary.get("runtime_boundaries_reduced_from") == 13
    assert summary.get("runtime_boundaries_reduced_to") == 8
    assert summary.get("scheduler_barrier_free") is True
    assert summary.get("fail_closed") is True

    assert orchestration.get("snapshot_identity", {}).get("sha256") == file_digest(DATA / "runtime/snapshot.v1.json")
    assert latest.get("lineage", {}).get("snapshot_sha256") == file_digest(DATA / "runtime/snapshot.v1.json")
    assert latest.get("lineage", {}).get("enrichment_sha256") == file_digest(DATA / "runtime/enrichment.v1.json")

    guardrails = orchestration.get("guardrails") or {}
    required_true = (
        "validation_lifecycle_no_official_refetch", "deadline_snapshot_immutable", "retroactive_snapshot_rejected",
        "reconciliation_archive_immutable", "reconciliation_idempotent", "health_view_current_model_only",
        "personal_gw_scorecard_no_official_refetch", "finished_gw_archive_immutable", "scorecard_simulation_never_mutates_archive",
        "scorecard_projection_from_effective_plan_contract", "user_decision_overlay_process_isolated", "engine_is_advisory",
        "user_decision_is_final_authority", "engine_never_auto_overwrites_valid_user_override",
        "projection_default_baseline_previous_submitted_gw", "planning_override_requires_target_gw", "stale_planning_override_rejected",
        "optimizer_search_width_unchanged", "reconciliation_started_from_official_stats_starts", "minutes_never_infer_started",
        "missing_starts_excluded_from_brier", "effective_plan_legality_enforced_post_overlay",
        "engine_effective_plan_legality_reported_separately", "decision_compute_slo_excludes_external_network_io",
        "official_fpl_first_when_field_available", "dag_parallel_ready_services", "parallel_services_must_have_no_dependency_edge",
        "validation_and_optimization_may_parallelize_after_prediction", "governance_requires_validation_user_plan_and_scorecard",
        "human_report_language_governed", "technical_reason_codes_separate_from_human_report", "scheduled_checkpoint_recovery_enabled",
        "architecture_guard_runs_before_orchestration", "immutable_artifacts_declared_per_service",
        "validation_boundary_preserves_four_artifact_contracts", "governance_boundary_preserves_postflight_and_checkpoint_contracts",
    )
    for key in required_true:
        assert guardrails.get(key) is True, (key, guardrails.get(key))
    assert guardrails.get("reconciliation_readiness_process_isolated") is False
    assert guardrails.get("reconciliation_readiness_read_only") is True
    assert guardrails.get("decision_compute_slo_ms") == 5000
    assert guardrails.get("official_fpl_api_authority") == "raw_snapshot_only"
    assert guardrails.get("gate0_checks_unchanged") == 16
    assert guardrails.get("service_count") == 8

    target = orchestration.get("runtime_target") or {}
    assert float(target.get("target_ms") or 0) == 5000.0
    assert target.get("hard_gate") is False

    architecture = legacy._load("architecture_ownership_v4.json")
    assert architecture.get("status") == "PASS"
    assert all(row.get("pass") for row in (architecture.get("checks") or {}).values())
    return orchestration, services


legacy._assert_framework_health = _assert_framework_health
legacy._assert_prediction_and_validation = _assert_prediction_and_validation
legacy._assert_orchestration = _assert_orchestration
_assert_version = legacy._assert_version
run = legacy.run


if __name__ == "__main__":
    run()
