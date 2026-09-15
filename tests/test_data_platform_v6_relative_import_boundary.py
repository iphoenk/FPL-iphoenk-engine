import ast

from src.runtime_v6.architecture_independence_validate import _relative_import_escapes_runtime_v6


def _import_from(statement: str) -> ast.ImportFrom:
    node = ast.parse(statement).body[0]
    assert isinstance(node, ast.ImportFrom)
    return node


def test_one_dot_relative_import_stays_inside_runtime_v6():
    assert _relative_import_escapes_runtime_v6(_import_from("from .health import build_source_health")) is False


def test_two_dot_relative_import_escapes_runtime_v6_boundary():
    assert _relative_import_escapes_runtime_v6(_import_from("from ..platform import governance")) is True


def test_three_dot_relative_import_escapes_runtime_v6_boundary():
    assert _relative_import_escapes_runtime_v6(_import_from("from ...other import helper")) is True
