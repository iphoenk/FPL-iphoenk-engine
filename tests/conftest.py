from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Wave 1 retires the automatic V3/V4/V5 workflow control plane. These tests
# assert details of workflows that are intentionally absent. Keep the tests in
# history, but skip only these exact obsolete assertions while retirement is
# active. All source/model/runtime tests in the same files continue to run.
RETIRED_WORKFLOW_NODEIDS = {
    "tests/test_checkpoint_precompute.py::test_policy_and_workflow_keep_logical_30_precompute_15_and_recovery_only_wakeups",
    "tests/test_default_branch_workflow_runtime.py::test_v3_runtime_code_publication_requires_successful_main_ci",
    "tests/test_default_branch_workflow_runtime.py::test_v3_runtime_no_longer_directly_triggers_on_main_push",
    "tests/test_default_branch_workflow_runtime.py::test_v3_runtime_publication_provenance_uses_verified_source_commit",
    "tests/test_default_branch_workflow_runtime.py::test_default_branch_v4_workflows_use_node24_compatible_immutable_actions",
    "tests/test_default_branch_workflow_runtime.py::test_default_branch_v4_publishers_keep_shared_non_cancelling_lock",
    "tests/test_default_branch_workflow_runtime.py::test_default_branch_v4_publish_callers_inherit_governed_secrets_and_stay_read_only",
    "tests/test_domain_runtime_simplification.py::test_unified_runtime_is_only_scheduled_v3_runtime_workflow",
    "tests/test_final_runtime_closeout.py::test_sharded_workflow_consumes_target_execution_outputs_instead_of_reimplementing_mapping",
    "tests/test_gw2_user_authority_reporting.py::test_scheduler_separates_precompute_and_recovery_wakeups_from_master_30",
    "tests/test_package_optimizer_sharded_runtime.py::test_sharded_workflow_uses_dynamic_matrix_and_registry_resume_not_business_module_list",
    "tests/test_release_metadata.py::test_release_metadata_surfaces_are_consistent",
    "tests/test_report_user_presentation.py::test_normal_report_slots_are_selected_inside_master_hourly_checkpoint_without_duplicate_crons",
    "tests/test_runtime_operational_policy.py::test_dispatcher_literals_are_guarded_against_policy_drift",
    "tests/test_runtime_optimization.py::test_workflows_are_unified_shallow_and_runtime_data_is_rolling",
    "tests/test_runtime_publication_atomicity.py::test_runtime_workflow_orders_every_candidate_gate_before_publication",
    "tests/test_runtime_publication_atomicity.py::test_runtime_publication_uses_exact_source_and_branch_leases",
    "tests/test_runtime_registry_alignment.py::test_active_v3_workflow_and_domains_have_single_runtime_owner",
    "tests/test_runtime_warm_retry_contract.py::test_fast_runtime_retry_is_bounded_and_keeps_hard_slo",
    "tests/test_runtime_warm_retry_contract.py::test_warm_retry_revalidates_production_contracts_before_publication",
    "tests/test_scheduler_runtime_recovery.py::test_01_scheduler_is_the_only_default_branch_master_cron_owner",
    "tests/test_scheduler_runtime_recovery.py::test_02_no_duplicate_v4_master_cron_in_recovery_or_timing_probe",
    "tests/test_scheduler_runtime_recovery.py::test_03_scheduler_targets_current_canonical_v4_sha",
    "tests/test_scheduler_runtime_recovery.py::test_04_scheduler_production_evaluation_publishes",
    "tests/test_scheduler_runtime_recovery.py::test_07_in_progress_production_is_serialized_before_recovery_recheck",
    "tests/test_scheduler_runtime_recovery.py::test_08_recovery_preserves_internal_visibility_semantics",
    "tests/test_scheduler_runtime_recovery.py::test_09_recovery_has_one_engine_path_and_cannot_add_a_second_report_path",
    "tests/test_scheduler_runtime_recovery.py::test_10_runtime_branch_target_remains_runtime_data_v4",
    "tests/test_scheduler_runtime_recovery.py::test_11_all_production_capable_dispatchers_share_deterministic_lock",
    "tests/test_scheduler_runtime_recovery.py::test_12_workflow_yaml_has_required_github_actions_shape",
    "tests/test_scheduler_runtime_recovery.py::test_13_recovery_watchdog_is_off_checkpoint_and_stale_only",
    "tests/test_supply_chain_hardening.py::test_runtime_compute_is_read_only_and_publication_is_isolated",
    "tests/test_supply_chain_hardening.py::test_runtime_publication_uses_exact_dedicated_github_app_identity",
    "tests/test_supply_chain_hardening.py::test_workflows_use_full_sha_pins_and_locked_dependencies",
}

RETIRED_AUTOMATIC_WORKFLOWS = (
    "v3-runtime.yml",
    "v3-package-precompute.yml",
    "v4-prediction.yml",
    "v4-timing-probe.yml",
    "fpl-engine-recovery.yml",
    "v5-evidence-dispatcher.yml",
)


def _legacy_automatic_workflows_retired() -> bool:
    workflow_dir = ROOT / ".github" / "workflows"
    return all(not (workflow_dir / name).exists() for name in RETIRED_AUTOMATIC_WORKFLOWS)


def pytest_collection_modifyitems(items):
    if not _legacy_automatic_workflows_retired():
        return

    marker = pytest.mark.skip(
        reason="WAVE1_RETIRED_LEGACY_WORKFLOW_CONTRACT: automatic V3/V4/V5 workflow is intentionally absent"
    )
    for item in items:
        if item.nodeid in RETIRED_WORKFLOW_NODEIDS:
            item.add_marker(marker)
