from __future__ import annotations

from pathlib import Path

from src.runtime_v3 import module_batch_runner, registry_compiler

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_orchestrator_consumes_compiled_execution_plan() -> None:
    source = (ROOT / "src/runtime_v3/domain_orchestrator.py").read_text(encoding="utf-8")

    assert "from src.runtime_v3 import registry_compiler" in source
    assert "compiled_plan = registry_compiler.compile_runtime_plan(" in source
    assert 'pending = list(compiled_plan["domain_order"])' in source
    assert 'compiled_execution_plan_sha256' in source
    assert 'compiled_domain_waves' in source
    assert '"V3_MODULE_BATCHES_V1"' not in source


def test_runtime_batch_metadata_uses_derived_registry() -> None:
    registry = module_batch_runner._registry()
    plan = registry_compiler.compile_runtime_plan()

    assert registry["registry"] == registry_compiler.DERIVED_BATCH_REGISTRY_ID
    assert plan["source_registries"]["module_batches"] == registry["registry"]
    assert plan["batch_capabilities"] == list(registry["batches"])
    assert plan["policy"]["module_batches_are_derived"] is True
