from pathlib import Path

from src.runtime_v6.architecture_independence_validate import validate_repository


def test_v6_is_standalone_from_v3_v4_and_uses_owned_runtime_contracts():
    assert validate_repository(Path(".")) == []
