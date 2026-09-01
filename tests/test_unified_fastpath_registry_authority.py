from __future__ import annotations

import copy

import pytest

from src.runtime_v3 import unified_fastpath


def test_unified_fastpath_inputs_are_derived_from_interactive_registry():
    registry = unified_fastpath._registry()
    data_names, config_paths = unified_fastpath._service_inputs(registry)
    service = registry["services"][unified_fastpath.SERVICE_NAME]
    declared = [str(value) for value in service["consumes"]]

    expected_data = tuple(value.removeprefix("data/") for value in declared if not value.startswith("config/"))
    expected_config = tuple(unified_fastpath.ROOT / value for value in declared if value.startswith("config/"))

    assert data_names == expected_data
    assert config_paths == expected_config
    assert any(path.name == "locked_squad.json" for path in config_paths)


def test_unified_fastpath_new_declared_data_input_needs_no_code_list_change():
    registry = copy.deepcopy(unified_fastpath._registry())
    registry["services"][unified_fastpath.SERVICE_NAME]["consumes"].append("future_runtime_contract.json")

    data_names, _ = unified_fastpath._service_inputs(registry)

    assert "future_runtime_contract.json" in data_names


def test_unified_fastpath_rejects_duplicate_declared_inputs():
    registry = copy.deepcopy(unified_fastpath._registry())
    registry["services"][unified_fastpath.SERVICE_NAME]["consumes"].append("latest.json")

    with pytest.raises(RuntimeError, match="duplicate declared inputs"):
        unified_fastpath._service_inputs(registry)


def test_unified_fastpath_source_has_no_secondary_runtime_artifact_tuple():
    source = unified_fastpath.__file__
    text = open(source, encoding="utf-8").read()
    assert 'names = ("latest.json"' not in text
    assert 'CONFIG / "locked_squad.json"' not in text
