from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.runtime_v3 import module_batch_runner, registry_compiler

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_orchestrator_consumes_compiled_execution_plan() -> None:
    source = (ROOT / "src/runtime_v3/domain_orchestrator.py").read_text(encoding="utf-8")

    assert "from src.runtime_v3 import registry_compiler" in source
    assert "service_registry = registry_compiler.load_capability_registry()" in source
    assert "domain_registry = registry_compiler.load_domain_registry()" in source
    assert "compiled_plan = registry_compiler.compile_runtime_plan(" in source
    assert 'pending = list(compiled_plan["domain_order"])' in source
    assert 'compiled_execution_plan_sha256' in source
    assert 'compiled_domain_waves' in source
    assert '"V3_MODULE_BATCHES_V1"' not in source


def test_canonical_orchestrator_has_no_secondary_topology_or_dag_authority() -> None:
    source = (ROOT / "src/runtime_v3/domain_orchestrator.py").read_text(encoding="utf-8")

    assert "_CANONICAL_PHASES" not in source
    assert "_CANONICAL_DOMAINS" not in source
    assert "def _validate_domain_coverage" not in source
    assert "legacy._validate_dag(service_registry)" not in source
    assert "def _load_domains" not in source


def test_runtime_batch_metadata_uses_derived_registry() -> None:
    registry = module_batch_runner._registry()
    plan = registry_compiler.compile_runtime_plan()

    assert registry["registry"] == registry_compiler.DERIVED_BATCH_REGISTRY_ID
    assert plan["source_registries"]["module_batches"] == registry["registry"]
    assert plan["batch_capabilities"] == list(registry["batches"])
    assert plan["policy"]["module_batches_are_derived"] is True


def test_registry_compiler_fails_closed_on_domain_cycle() -> None:
    domains = copy.deepcopy(registry_compiler.load_domain_registry())
    services = registry_compiler.load_capability_registry()
    domains["domains"]["official_state"]["depends_on"] = ["serving"]

    with pytest.raises(RuntimeError, match="dependency cycle"):
        registry_compiler.compile_runtime_plan(domains, services)


def test_registry_compiler_fails_closed_on_undeclared_multi_writer_artifact() -> None:
    domains = copy.deepcopy(registry_compiler.load_domain_registry())
    services = registry_compiler.load_capability_registry()
    domains["artifact_writer_exceptions"].pop("user_report.json")

    with pytest.raises(RuntimeError, match="multi-writer artifact exception drift"):
        registry_compiler.compile_runtime_plan(domains, services)


def test_registry_compiler_fails_closed_on_duplicate_capability_assignment() -> None:
    domains = copy.deepcopy(registry_compiler.load_domain_registry())
    services = registry_compiler.load_capability_registry()
    domains["domains"]["market_context"]["capabilities"].append("prediction")

    with pytest.raises(RuntimeError, match="multiple execution domains"):
        registry_compiler.compile_runtime_plan(domains, services)
