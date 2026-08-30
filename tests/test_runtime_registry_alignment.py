from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v3 import module_batch_runner, registry_compiler

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _module_path(module: str) -> Path:
    return ROOT / (module.replace(".", "/") + ".py")


def test_module_batches_are_derived_from_capability_commands_exactly() -> None:
    services = _json("config/v3_service_registry.json")["services"]
    derived = registry_compiler.derived_batch_registry()
    expected = {
        service_name: spec["commands"]
        for service_name, spec in services.items()
        if len(spec.get("commands") or []) > 1
    }

    assert derived["registry"] == "V3_MODULE_BATCHES_DERIVED_V2"
    assert derived["generated_from"] == "config/v3_service_registry.json#services.*.commands"
    assert derived["batches"] == expected
    assert module_batch_runner._registry() == derived
    assert not (ROOT / "config/runtime/module_batches.json").exists()


def test_registry_compiler_is_deterministic_and_covers_the_runtime_control_plane() -> None:
    services = _json("config/v3_service_registry.json")["services"]
    domains = _json("config/runtime/execution_domains.json")
    first = registry_compiler.compile_runtime_plan()
    second = registry_compiler.compile_runtime_plan()

    assert first == second
    assert first["registry"] == "V3_COMPILED_EXECUTION_PLAN_V1"
    assert len(first["plan_sha256"]) == 64
    assert first["phase_count"] == 6
    assert first["domain_count"] == 11
    assert first["capability_count"] == 22
    assert list(first["capability_owner"]) == list(services)
    assert set(first["capability_owner"]) == set(services)
    assert first["capability_owner"]["weather_context"] == "football_context"
    assert first["domain_order"] == [
        name
        for phase in domains["canonical_phases"].values()
        for name in phase
    ]
    assert first["batch_capabilities"] == [
        "advanced_stats",
        "official_detail",
        "governance",
        "watchlist",
        "reporting",
        "report_materializer",
    ]
    assert set(first["multi_writer_artifacts"]) == {
        "prices.json",
        "user_report.json",
    }
    assert first["policy"]["module_batches_are_derived"] is True
    assert first["policy"]["human_maintained_module_batch_registry"] is False


def test_all_active_service_command_modules_exist_and_exclude_retired_business_modules() -> None:
    services = _json("config/v3_service_registry.json")["services"]
    ownership = _json("config/v3_architecture_ownership_registry.json")
    retired = set(ownership.get("legacy_business_implementations_to_retire") or [])

    active_modules = []
    for service_name, spec in services.items():
        for command in spec.get("commands") or []:
            module = str(command.get("module") or "")
            assert module, service_name
            assert _module_path(module).is_file(), (service_name, module)
            active_modules.append(module)

    assert retired.isdisjoint(active_modules)


def test_decision_snapshot_is_declared_across_producer_consumer_and_publish_contracts() -> None:
    services = _json("config/v3_service_registry.json")["services"]
    publish = _json("config/runtime/runtime_publish_registry.json")
    contracts = _json("config/runtime/artifact_contracts.json")["contracts"]

    reporting = services["reporting"]
    evaluation = services["prediction_evaluation"]
    snapshot_contract = contracts["decision_validation_snapshots.json"]

    assert {"module": "src.engines.prediction_decision_snapshot", "args": []} in reporting["commands"]
    assert "decision_validation_snapshots.json" in reporting["artifacts"]
    assert "decision_validation_snapshots.json" in reporting["inputs"]
    assert "decision_validation_snapshots.json" in evaluation["inputs"]
    assert "decision_validation_snapshots.json" in publish["hydrate_paths"]
    assert "decision_validation_snapshots.json" in publish["publish_paths"]
    assert snapshot_contract["equals"]["schema_version"] == 2
    assert snapshot_contract["equals"]["owner"] == "reporting.decision_snapshot_evidence"


def test_governance_service_declares_every_persisted_governance_artifact() -> None:
    service = _json("config/v3_service_registry.json")["services"]["governance"]
    expected_artifacts = {
        "framework_health_preflight.json",
        "framework_health.json",
        "external_consensus.json",
        "recent_competitive_load.json",
        "dss_operational_evidence.json",
    }
    expected_latest = {
        "source_health_summary",
        "external_consensus_summary",
        "competitive_load_summary",
        "dss_operationalization_summary",
        "dss_evidence_maturity",
    }
    assert set(service["artifacts"]) == expected_artifacts
    assert set(service["latest_keys"]) == expected_latest
    assert set(service["latest_file_keys"]) == {
        "external_consensus",
        "recent_competitive_load",
        "dss_operational_evidence",
    }


def test_lineup_governance_latest_file_contract_is_preserved() -> None:
    service = _json("config/v3_service_registry.json")["services"]["lineup_governance"]
    assert service["latest_file_keys"] == ["lineup_decision", "package_decision"]


def test_active_v3_workflow_and_domains_have_single_runtime_owner() -> None:
    domains = _json("config/runtime/execution_domains.json")
    services = _json("config/v3_service_registry.json")["services"]
    assigned = [name for spec in domains["domains"].values() for name in spec.get("capabilities", [])]

    assert domains["phase_count"] == 6
    assert len(domains["domains"]) == 11
    assert len(services) == 22
    assert len(assigned) == len(set(assigned)) == len(services)
    assert set(assigned) == set(services)
    assert "weather_context" in domains["domains"]["football_context"]["capabilities"]
    assert domains["control_plane"]["compiler"] == "src.runtime_v3.registry_compiler"
    assert domains["control_plane"]["module_batch_registry"] == "DERIVED_FROM_CAPABILITY_COMMANDS"
    assert domains["control_plane"]["human_maintained_module_batch_registry"] is False

    runtime = (ROOT / ".github/workflows/v3-runtime.yml").read_text(encoding="utf-8")
    compat = (ROOT / ".github/workflows/fpl-engine.yml").read_text(encoding="utf-8")
    assert "python -m src.runtime_v3.domain_orchestrator" in runtime
    assert "schedule:" in runtime
    assert "schedule:" not in compat
    assert "Inert compatibility marker" in compat


def test_decision_arbitration_is_reporting_owned_helper_not_service() -> None:
    services = _json("config/v3_service_registry.json")["services"]
    ownership = _json("config/v3_architecture_ownership_registry.json")
    source = (ROOT / "src/engines/report_enrichment.py").read_text(encoding="utf-8")
    primitives = {row["id"]: row for row in ownership["shared_primitives"]}

    assert "decision_arbitration" not in services
    assert "from src.engines.decision_arbitration import arbitrate_decisions, assert_decision_consistency" in source
    assert primitives["FINAL_DECISION_ARBITRATION"]["owner"] == "reporting"
    assert primitives["FINAL_DECISION_ARBITRATION"]["implementation"] == "src.engines.decision_arbitration"


def test_prediction_snapshot_and_xmins_have_explicit_canonical_owners() -> None:
    ownership = _json("config/v3_architecture_ownership_registry.json")
    primitives = {row["id"]: row for row in ownership["shared_primitives"]}

    snapshot = primitives["PREDEADLINE_DECISION_SNAPSHOT_EVIDENCE"]
    assert snapshot["owner"] == "reporting"
    assert snapshot["implementation"] == "src.engines.prediction_decision_snapshot"
    assert "prediction_evaluation" in snapshot["consumers"]

    xmins = primitives["XMINS_DISTRIBUTION"]
    assert xmins["owner"] == "prediction"
    assert xmins["implementation"] == "src.models.xmins_v3"


def test_decision_hotpath_compatibility_path_delegates_to_unified_owner() -> None:
    ownership = _json("config/v3_architecture_ownership_registry.json")
    interactive = _json("config/runtime/interactive_service_registry.json")
    source = (ROOT / "src/engines/decision_hotpath_service.py").read_text(encoding="utf-8")

    assert "src.engines.decision_hotpath_service" in ownership["compatibility_only_modules"]
    assert set(interactive["services"]) == {"unified_fastpath"}
    assert interactive["compatibility_entrypoints"]["decision_hotpath"] == "src.engines.decision_hotpath_service"
    assert "from src.runtime_v3.unified_fastpath import run as run_unified_fastpath" in source
    assert "build_lineup_decision" not in source
    assert "build_package_decision" not in source


def test_active_framework_health_service_overrides_legacy_formula_probes() -> None:
    service = (ROOT / "src/engines/framework_health_service.py").read_text(encoding="utf-8")
    legacy = (ROOT / "src/engines/framework_health_audit.py").read_text(encoding="utf-8")

    # Historical fallbacks may remain in the compatibility audit core, but active
    # framework health must replace all three before audit_engine.run().
    assert "from src.models.projection import xmins_distribution" in legacy
    assert "from src.models.projection import project_points" in legacy
    assert "from src.models.optimizer import legal_counts" in legacy
    assert "def activate_canonical_probe_contracts()" in service
    assert "audit_engine._probe_xmins = canonical_xmins_probe" in service
    assert "audit_engine._probe_projection = canonical_projection_probe" in service
    assert "audit_engine._probe_structural = canonical_structural_probe" in service
    assert service.index("activate_canonical_probe_contracts()", service.index("def run()")) < service.index("audit_engine.run()", service.index("def run()"))
