from __future__ import annotations

import json

from src.engines import v4_quality_gate_legacy as legacy
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA


def _assert_orchestration(latest: dict) -> tuple[dict, list[dict]]:
    """Validate the simplified execution topology without weakening other gates."""
    orchestration = legacy._load("service_orchestration_v4.json")
    legacy._assert_version(
        orchestration,
        "orchestration",
        496,
        "v4.9.6-service-orchestrator-8-boundary",
    )
    assert orchestration.get("status") == "PASS"
    assert orchestration.get("stats_enabled") is True
    assert orchestration.get("deep_stats_enabled") is True
    assert orchestration.get("execution_model") == "process_isolated_dag_parallel_single_host"

    services = orchestration.get("services") or []
    ids = [row.get("id") for row in services]
    registry = json.loads((CONFIG / "service_registry.json").read_text(encoding="utf-8"))
    expected_ids = [row.get("id") for row in registry.get("services") or []]
    assert expected_ids == [
        "raw_snapshot",
        "enrichment",
        "prediction",
        "validation",
        "optimization",
        "user_decision_overlay",
        "personal_gw_scorecard",
        "governance",
    ]
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
        "validation_lifecycle_no_official_refetch",
        "deadline_snapshot_immutable",
        "retroactive_snapshot_rejected",
        "reconciliation_archive_immutable",
        "reconciliation_idempotent",
        "health_view_current_model_only",
        "personal_gw_scorecard_no_official_refetch",
        "finished_gw_archive_immutable",
        "scorecard_simulation_never_mutates_archive",
        "scorecard_projection_from_effective_plan_contract",
        "user_decision_overlay_process_isolated",
        "engine_is_advisory",
        "user_decision_is_final_authority",
        "engine_never_auto_overwrites_valid_user_override",
        "projection_default_baseline_previous_submitted_gw",
        "planning_override_requires_target_gw",
        "stale_planning_override_rejected",
        "optimizer_search_width_unchanged",
        "reconciliation_started_from_official_stats_starts",
        "minutes_never_infer_started",
        "missing_starts_excluded_from_brier",
        "effective_plan_legality_enforced_post_overlay",
        "engine_effective_plan_legality_reported_separately",
        "decision_compute_slo_excludes_external_network_io",
        "official_fpl_first_when_field_available",
        "dag_parallel_ready_services",
        "parallel_services_must_have_no_dependency_edge",
        "validation_and_optimization_may_parallelize_after_prediction",
        "governance_requires_validation_user_plan_and_scorecard",
        "human_report_language_governed",
        "technical_reason_codes_separate_from_human_report",
        "scheduled_checkpoint_recovery_enabled",
        "architecture_guard_runs_before_orchestration",
        "immutable_artifacts_declared_per_service",
        "validation_boundary_preserves_four_artifact_contracts",
        "governance_boundary_preserves_postflight_and_checkpoint_contracts",
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


# Keep the complete pre-existing prediction, legality, report, calibration and
# actionability gate suite unchanged; only replace the topology-specific check.
legacy._assert_orchestration = _assert_orchestration
_assert_version = legacy._assert_version
run = legacy.run


if __name__ == "__main__":
    run()
