from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_module_batches_match_service_registry_entrypoints_exactly() -> None:
    services = _json("config/v3_service_registry.json")["services"]
    batches = _json("config/runtime/module_batches.json")["batches"]

    for service_name, batch_commands in batches.items():
        assert service_name in services, service_name
        assert services[service_name].get("commands") == batch_commands, service_name


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


def test_lineup_governance_latest_file_contract_is_preserved() -> None:
    service = _json("config/v3_service_registry.json")["services"]["lineup_governance"]
    assert service["latest_file_keys"] == ["lineup_decision", "package_decision"]


def test_active_v3_workflow_and_domains_have_single_runtime_owner() -> None:
    domains = _json("config/runtime/execution_domains.json")
    services = _json("config/v3_service_registry.json")["services"]
    assigned = [name for spec in domains["domains"].values() for name in spec.get("capabilities", [])]

    assert len(domains["domains"]) == 7
    assert len(services) == 21
    assert len(assigned) == len(set(assigned)) == len(services)
    assert set(assigned) == set(services)

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
    assert interactive["services"] == {
        "unified_fastpath": interactive["services"]["unified_fastpath"]
    }
    assert interactive["compatibility_entrypoints"]["decision_hotpath"] == "src.engines.decision_hotpath_service"
    assert "from src.runtime_v3.unified_fastpath import run as run_unified_fastpath" in source
    assert "build_lineup_decision" not in source
    assert "build_package_decision" not in source
