from pathlib import Path

import pytest

from src.engines.v3_architecture_ownership_guard import _ast_official_fetch_calls


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "module.py"
    path.write_text(text, encoding="utf-8")
    return path


def test_ast_guard_ignores_comments_and_string_literals(tmp_path: Path):
    path = _write(
        tmp_path,
        '''
# get_json("bootstrap-static/") must not count as a call.
EXAMPLE = 'src.sources.official_fpl.get_json("fixtures/")'

def local():
    return "get_json(event-status/)"
''',
    )
    assert _ast_official_fetch_calls(path) == []


def test_ast_guard_detects_module_alias_and_static_core_endpoint(tmp_path: Path):
    path = _write(
        tmp_path,
        '''
from src.sources import official_fpl as official

BOOT = "bootstrap-" + "static/"

def fetch():
    return official.get_json(BOOT)
''',
    )
    calls = _ast_official_fetch_calls(path)
    assert len(calls) == 1
    assert calls[0]["endpoint"] == "bootstrap-static/"
    assert calls[0]["target"] == "official.get_json"


def test_ast_guard_detects_direct_import_alias_and_function_alias(tmp_path: Path):
    path = _write(
        tmp_path,
        '''
from src.sources.official_fpl import get_json as official_get
fetch = official_get

def run(endpoint):
    return fetch(endpoint)
''',
    )
    calls = _ast_official_fetch_calls(path)
    assert len(calls) == 1
    assert calls[0]["endpoint"] == "<dynamic>"
    assert calls[0]["target"] == "fetch"


def test_ast_guard_detects_fully_qualified_import_call(tmp_path: Path):
    path = _write(
        tmp_path,
        '''
import src.sources.official_fpl

def run():
    return src.sources.official_fpl.get_json("fixtures/")
''',
    )
    calls = _ast_official_fetch_calls(path)
    assert len(calls) == 1
    assert calls[0]["endpoint"] == "fixtures/"


def test_ast_guard_fails_closed_on_wildcard_import(tmp_path: Path):
    path = _write(
        tmp_path,
        '''
from src.sources.official_fpl import *
''',
    )
    with pytest.raises(RuntimeError, match="wildcard import"):
        _ast_official_fetch_calls(path)
