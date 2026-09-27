from __future__ import annotations

import json
from pathlib import Path


PATH = Path(__file__).resolve().parents[1] / "config" / "performance" / "v12_cache_dependency_matrix.json"

CHANGE_CLASSES = {
    "UNCHANGED",
    "PRICE_ONLY",
    "INJURY_STATUS",
    "OWNED_AVAILABILITY",
    "XMINS",
    "ROLE",
    "SET_PIECE_ROLE",
    "FIXTURE",
    "TEAM_FINANCE",
    "MINI_LEAGUE_ONLY",
    "RUNTIME_CLASS",
    "SCENARIO_OVERRIDE",
    "CHALLENGER_ONLY",
}
LAYERS = {"Stage2", "P1.7", "MC", "scenario", "stability"}


def _matrix():
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_matrix_is_complete_and_binary_before_performance_ab():
    payload = _matrix()
    assert payload["authority"] == "FPL_V12_CACHE_DEPENDENCY_MATRIX"
    assert payload["frozen_before_ab"] is True
    assert set(payload["matrix"]) == CHANGE_CLASSES
    assert set(payload["layers"]) == LAYERS
    for change, row in payload["matrix"].items():
        assert set(row) == LAYERS, change
        assert set(row.values()) <= {"HIT", "MISS"}


def test_correctness_failure_semantics_are_fail_closed():
    semantics = _matrix()["semantics"]
    assert semantics["expected_miss_actual_hit"] == "CORRECTNESS_FAIL"
    assert semantics["expected_hit_actual_miss"] == "PERFORMANCE_OVER_INVALIDATION"
    assert semantics["warm_not_equal_canonical_cold"] == "CORRECTNESS_FAIL"


def test_public_private_and_challenger_boundaries_are_explicit():
    rows = _matrix()["matrix"]
    assert rows["OWNED_AVAILABILITY"]["Stage2"] == "HIT"
    assert rows["OWNED_AVAILABILITY"]["P1.7"] == "MISS"
    assert rows["MINI_LEAGUE_ONLY"]["MC"] == "HIT"
    assert rows["MINI_LEAGUE_ONLY"]["stability"] == "MISS"
    assert all(value == "HIT" for value in rows["CHALLENGER_ONLY"].values())


def test_runtime_class_and_model_semantic_changes_fail_closed():
    rows = _matrix()["matrix"]
    for change in ("RUNTIME_CLASS", "XMINS", "ROLE", "SET_PIECE_ROLE", "FIXTURE"):
        assert all(value == "MISS" for value in rows[change].values())
